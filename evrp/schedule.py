"""Exact energy scheduling for a fixed route (linear / mixed-integer program).

Routing and energy scheduling decompose naturally.  Once the *sequence* of
stops is fixed, deciding how much to charge at each charger -- and, if the
fleet sells energy back (V2G), how much to discharge and when -- is a small
optimisation problem that is **linear**, and therefore solvable to proven
optimality rather than by a rule of thumb.  That is what this module does,
using the linear-solver wrapper shipped with OR-Tools.

Why it is linear
----------------
With the sequence fixed, the energy drawn on each arc is a constant, and the
schedule is governed by two recursions that are affine in the decisions:

    soc[k+1] = soc[k] + charge[k] - discharge[k] - arc_energy[k]
    arr[k+1] = start[k] + service[k] + plug_time[k] + travel[k]

Waiting for a time window, which is a ``max``, is handled the standard way by
splitting arrival from service start (``start[k] >= arr[k]``,
``start[k] >= ready[k]``) -- the optimiser will never wait longer than it must
because waiting only tightens the remaining windows.

Objective:  maximise  ``v2g_price * sum(discharge) - energy_price * sum(charge)``
with a small tie-break penalty on the finish time, so that among schedules of
equal money the earliest one wins.

Time-of-use windows
-------------------
If a station carries an explicit peak window, selling into it is only worth
money while the vehicle is actually plugged in during that window.  That makes
the decision "does this stop operate in V2G mode?" a binary, and the model
becomes a small MILP (big-M linking the service start to the peak window).
Routes have a handful of stops, so this stays cheap.  Windows are opt-in --
``Scenario.peak_start_min`` / ``peak_end_min``, or ``--peak-window`` on the
CLI -- and with none declared the peak binaries disappear.

Nothing here is taken on trust downstream: the plan this module returns is
replayed by :mod:`evrp.feasibility`, which re-checks the V2G floor, the peak
window and the resulting time windows against the exact charging curve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from evrp.config import ChargingConfig, EnergyConfig
from evrp.energy import ChargingCurve, EnergyModel
from evrp.instance import Instance

try:  # pragma: no cover - exercised implicitly
    from ortools.linear_solver import pywraplp
except ImportError:  # pragma: no cover
    pywraplp = None  # type: ignore[assignment]


class ScheduleError(RuntimeError):
    """Raised when the schedule model cannot be built or solved."""


@dataclass
class ScheduleResult:
    """Outcome of scheduling one route."""

    feasible: bool
    status: str
    charge_kwh: dict[int, float] = field(default_factory=dict)
    discharge_kwh: dict[int, float] = field(default_factory=dict)
    arrival: list[float] = field(default_factory=list)
    service_start: list[float] = field(default_factory=list)
    soc: list[float] = field(default_factory=list)
    total_charged: float = 0.0
    total_discharged: float = 0.0
    energy_cost: float = 0.0
    v2g_revenue: float = 0.0
    finish_time: float = 0.0
    solver: str = "none"

    @property
    def net_revenue(self) -> float:
        return self.v2g_revenue - self.energy_cost


def _payload_profile(instance: Instance, body: Sequence[int]) -> list[float]:
    demands = [instance.nodes[n].demand for n in body]
    remaining = sum(demands)
    out = []
    for d in demands:
        out.append(remaining)
        remaining -= d
    out.append(remaining)
    return out


def optimise_schedule(
    instance: Instance,
    route: Sequence[int],
    energy_config: EnergyConfig | None = None,
    charging_config: ChargingConfig | None = None,
    time_penalty: float = 1e-4,
) -> ScheduleResult:
    """Optimal charge / discharge plan for a fixed stop sequence.

    ``route`` is a node-index sequence without depot sentinels.  Returns the
    plan together with the resulting trajectory; ``feasible=False`` means no
    charging plan exists that satisfies the windows and the battery bounds for
    this sequence, which is itself useful information (the sequence must change).
    """
    if pywraplp is None:  # pragma: no cover
        raise ScheduleError("ortools.linear_solver is unavailable")

    energy_config = energy_config or EnergyConfig()
    charging_config = charging_config or ChargingConfig()
    vehicle = instance.vehicle
    model = EnergyModel(energy_config, vehicle)

    body = [int(n) for n in route if int(n) != 0]
    if not body:
        return ScheduleResult(feasible=True, status="empty", solver="none")

    seq = [0, *body, 0]
    payload = _payload_profile(instance, body)
    arc_energy = [
        model.consumption(float(instance.distance[seq[k]][seq[k + 1]]), payload[k])
        for k in range(len(seq) - 1)
    ]
    arc_time = [float(instance.travel_time[seq[k]][seq[k + 1]]) for k in range(len(seq) - 1)]

    station_positions = [k for k, n in enumerate(seq) if n != 0 and instance.is_station(n)]
    # A stop either buys energy or sells it, never both: without that switch
    # the LP would "arbitrage" a single plug-in whenever the sell price beats
    # the buy price, which is not a thing a charger lets you do.  The switch
    # is a binary, so enabling V2G turns the LP into a small MILP.
    needs_mip = charging_config.v2g_enabled and bool(station_positions)

    solver = None
    for backend in (["SCIP", "CBC"] if needs_mip else ["GLOP", "SCIP", "CBC"]):
        solver = pywraplp.Solver.CreateSolver(backend)
        if solver is not None:
            break
    if solver is None:  # pragma: no cover
        raise ScheduleError("no linear solver backend available in this OR-Tools build")

    horizon = float(instance.horizon)
    battery = vehicle.battery_kwh
    reserve = vehicle.min_soc_kwh
    v2g_floor = max(reserve, battery * charging_config.v2g_min_soc)

    n = len(seq)
    arr = [solver.NumVar(0.0, horizon, f"arr{k}") for k in range(n)]
    start = [solver.NumVar(0.0, horizon, f"start{k}") for k in range(n)]
    soc = [solver.NumVar(reserve, battery, f"soc{k}") for k in range(n)]
    charge = [solver.NumVar(0.0, 0.0, f"ch{k}") for k in range(n)]
    discharge = [solver.NumVar(0.0, 0.0, f"dis{k}") for k in range(n)]
    plug = [solver.NumVar(0.0, horizon, f"plug{k}") for k in range(n)]

    # depot start
    solver.Add(arr[0] == float(instance.depot.ready_time))
    solver.Add(start[0] == arr[0])
    solver.Add(soc[0] == battery)
    solver.Add(plug[0] == 0.0)

    v2g_flags: dict[int, object] = {}
    big_m = horizon + 1.0

    for k in range(1, n - 1):
        node = instance.nodes[seq[k]]
        solver.Add(start[k] >= arr[k])
        solver.Add(start[k] >= float(node.ready_time))
        solver.Add(arr[k] <= float(min(node.due_time, horizon)))

        if k in station_positions:
            station = instance.station_for_node(seq[k])
            curve = ChargingCurve(station.power_kw, vehicle, charging_config)
            power = (
                curve.taper_power_kw
                if charging_config.curve == "piecewise"
                else curve.power_kw
            )
            charge[k].SetUb(battery)
            solver.Add(plug[k] >= charge[k] * (60.0 / power) + charging_config.fixed_time_min)
            if charging_config.v2g_enabled and station.v2g_capable:
                discharge[k].SetUb(battery)
                solver.Add(plug[k] >= discharge[k] * (60.0 / power))
                mode = solver.IntVar(0, 1, f"buy{k}")  # 1 = buying, 0 = selling
                solver.Add(charge[k] <= battery * mode)
                solver.Add(discharge[k] <= battery * (1 - mode))
                # Only what sits above the V2G floor may be sold.  The `+ battery
                # * mode` term relaxes the bound at stops that are buying, so
                # turning V2G on can never remove a schedule that was feasible
                # with it off.
                solver.Add(discharge[k] <= soc[k] - v2g_floor + battery * mode)
                if station.peak_start is not None and station.peak_end is not None:
                    y = solver.IntVar(0, 1, f"v2g{k}")
                    v2g_flags[k] = y
                    solver.Add(discharge[k] <= battery * y)
                    solver.Add(start[k] >= float(station.peak_start) - big_m * (1 - y))
                    solver.Add(
                        start[k] + plug[k] <= float(station.peak_end) + big_m * (1 - y)
                    )
        else:
            solver.Add(plug[k] == 0.0)

        solver.Add(soc[k] + charge[k] - discharge[k] <= battery)
        solver.Add(soc[k] + charge[k] - discharge[k] >= reserve)
        solver.Add(
            arr[k + 1]
            == start[k] + float(node.service_time) + plug[k] + arc_time[k]
        )
        solver.Add(
            soc[k + 1] == soc[k] + charge[k] - discharge[k] - arc_energy[k]
        )

    solver.Add(arr[1] == arr[0] + arc_time[0])
    solver.Add(soc[1] == soc[0] - arc_energy[0])
    solver.Add(arr[n - 1] <= float(instance.depot.due_time))
    solver.Add(start[n - 1] == arr[n - 1])
    solver.Add(plug[n - 1] == 0.0)
    if vehicle.max_route_duration is not None:
        solver.Add(arr[n - 1] - arr[0] <= float(vehicle.max_route_duration))

    objective = solver.Objective()
    for k in range(1, n - 1):
        if k in station_positions:
            objective.SetCoefficient(charge[k], -charging_config.energy_price)
            if charging_config.v2g_enabled:
                objective.SetCoefficient(discharge[k], charging_config.v2g_price)
    objective.SetCoefficient(arr[n - 1], -time_penalty)
    objective.SetMaximization()

    status = solver.Solve()
    names = {
        pywraplp.Solver.OPTIMAL: "optimal",
        pywraplp.Solver.FEASIBLE: "feasible",
        pywraplp.Solver.INFEASIBLE: "infeasible",
        pywraplp.Solver.UNBOUNDED: "unbounded",
        pywraplp.Solver.ABNORMAL: "abnormal",
        pywraplp.Solver.NOT_SOLVED: "not_solved",
    }
    label = names.get(status, str(status))
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return ScheduleResult(feasible=False, status=label, solver=solver.SolverVersion())

    ch = {k - 1: charge[k].solution_value() for k in station_positions
          if charge[k].solution_value() > 1e-9}
    dis = {k - 1: discharge[k].solution_value() for k in station_positions
           if discharge[k].solution_value() > 1e-9}
    total_ch = sum(ch.values())
    total_dis = sum(dis.values())

    return ScheduleResult(
        feasible=True,
        status=label,
        charge_kwh=ch,
        discharge_kwh=dis,
        arrival=[v.solution_value() for v in arr],
        service_start=[v.solution_value() for v in start],
        soc=[v.solution_value() for v in soc],
        total_charged=total_ch,
        total_discharged=total_dis,
        energy_cost=total_ch * charging_config.energy_price,
        v2g_revenue=total_dis * charging_config.v2g_price,
        finish_time=arr[n - 1].solution_value(),
        solver=solver.SolverVersion(),
    )
