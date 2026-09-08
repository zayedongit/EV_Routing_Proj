"""Independent route simulator -- the ground truth for feasibility.

Every solver in this project is checked against this module rather than
against its own internal bookkeeping.  That separation matters: a routing
model expressed in OR-Tools dimensions is easy to get subtly wrong (an
off-by-one in a transit callback, a unit mismatch in a scaled integer), and a
solver that grades its own homework will happily report an infeasible route as
optimal.  The simulator here shares no code with any solver.

What it does
------------
Walks a route stop by stop and reproduces the physical trajectory of the
vehicle: payload, clock, state of charge, charging events.  It returns the
complete trace plus a list of typed violations, so a caller can ask both "is
this legal?" and "where exactly did it break, and by how much?".

Payload convention
------------------
Deliveries.  The vehicle leaves the depot carrying the whole route demand and
sheds each customer's demand on service.  Consumption on an arc therefore uses
the payload carried *along that arc*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

from evrp.config import ChargingConfig, EnergyConfig
from evrp.energy import ChargingCurve, EnergyModel
from evrp.instance import Instance, NodeKind

EPS = 1e-6


class ViolationKind(str, Enum):
    CAPACITY = "capacity"
    TIME_WINDOW = "time_window"
    BATTERY = "battery"
    DURATION = "duration"
    STATION_WINDOW = "station_window"
    BAD_NODE = "bad_node"


@dataclass(frozen=True)
class Violation:
    kind: ViolationKind
    node: int
    magnitude: float
    message: str

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"[{self.kind.value}] node {self.node}: {self.message}"


@dataclass
class Stop:
    """One visited node with the full vehicle state around it."""

    node: int
    kind: NodeKind
    arrival: float
    wait: float
    service_start: float
    service_time: float
    charge_time: float
    departure: float
    soc_arrival: float
    soc_departure: float
    charged_kwh: float
    discharged_kwh: float
    payload_on_arrival: float
    distance_from_prev: float
    energy_from_prev: float


@dataclass
class RouteSimulation:
    """Complete trace of one route."""

    route: tuple[int, ...]
    stops: list[Stop] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    distance: float = 0.0
    drive_time: float = 0.0
    wait_time: float = 0.0
    service_time: float = 0.0
    charge_time: float = 0.0
    energy_consumed: float = 0.0
    energy_charged: float = 0.0
    energy_discharged: float = 0.0
    load: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def feasible(self) -> bool:
        return not self.violations

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def n_customers(self) -> int:
        return sum(1 for s in self.stops if s.kind is NodeKind.CUSTOMER)

    @property
    def n_charging_stops(self) -> int:
        return sum(1 for s in self.stops if s.kind is NodeKind.STATION)

    @property
    def min_soc(self) -> float:
        return min((s.soc_arrival for s in self.stops), default=0.0)

    def violations_of(self, kind: ViolationKind) -> list[Violation]:
        return [v for v in self.violations if v.kind is kind]

    def soc_profile(self) -> list[tuple[float, float]]:
        """``(cumulative_distance_km, soc_kwh)`` points for plotting."""
        pts: list[tuple[float, float]] = []
        d = 0.0
        for s in self.stops:
            d += s.distance_from_prev
            pts.append((d, s.soc_arrival))
            if s.soc_departure != s.soc_arrival:
                pts.append((d, s.soc_departure))
        return pts


def _clean_route(instance: Instance, route: Sequence[int]) -> tuple[int, ...]:
    """Strip depot sentinels so callers may pass ``[0, 3, 7, 0]`` or ``[3, 7]``."""
    body = [int(n) for n in route]
    while body and body[0] == 0:
        body.pop(0)
    while body and body[-1] == 0:
        body.pop()
    return tuple(body)


def simulate_route(
    instance: Instance,
    route: Sequence[int],
    energy_config: EnergyConfig | None = None,
    charging_config: ChargingConfig | None = None,
    charge_plan: Mapping[int, float] | None = None,
    charge_policy: str = "minimal",
) -> RouteSimulation:
    """Replay ``route`` on ``instance`` and report the resulting trajectory.

    ``route`` is a sequence of node indices; leading/trailing depot entries are
    optional.  ``charge_plan`` maps a *position in the route* to an explicit
    amount of energy in kWh to add there, overriding ``charge_policy``.

    ``charge_policy`` is used at station stops with no explicit plan:

    ``"minimal"``  add exactly enough to reach the next station (or the depot)
                   with the reserve intact.  Cheapest in time; this is what a
                   dispatcher would do.
    ``"full"``     charge to 100 %.  Robust but pays the CV-taper penalty.
    ``"none"``     visit the station without charging (used to price detours).
    ``"explicit"`` charge only what ``charge_plan`` says; a station not named in
                   the plan is passed through.  Used to replay a solver's own
                   charging decisions exactly as it made them.
    """
    energy_config = energy_config or EnergyConfig()
    charging_config = charging_config or ChargingConfig()
    if charge_policy not in ("minimal", "full", "none", "explicit"):
        raise ValueError(
            "charge_policy must be 'minimal', 'full', 'none' or 'explicit'"
        )

    vehicle = instance.vehicle
    model = EnergyModel(energy_config, vehicle)
    body = _clean_route(instance, route)
    sim = RouteSimulation(route=body)

    for n in body:
        if not 0 <= n < instance.n_nodes:
            sim.violations.append(
                Violation(ViolationKind.BAD_NODE, n, 1.0, f"node index {n} out of range")
            )
    if sim.violations:
        return sim
    if not body:
        return sim

    # -- payload profile -------------------------------------------------
    demands = [instance.nodes[n].demand for n in body]
    total_demand = sum(demands)
    sim.load = total_demand
    if total_demand > vehicle.payload_capacity + EPS:
        sim.violations.append(
            Violation(
                ViolationKind.CAPACITY,
                0,
                total_demand - vehicle.payload_capacity,
                f"route load {total_demand:.1f} exceeds capacity {vehicle.payload_capacity:.1f}",
            )
        )

    # payload_on_arc[k] is what is carried on the arc arriving at body[k]
    payload_on_arc: list[float] = []
    remaining = total_demand
    for d in demands:
        payload_on_arc.append(remaining)
        remaining -= d
    payload_return = remaining  # should be ~0

    # -- energy needed from each stop onwards (for "minimal" charging) ----
    seq = [0, *body, 0]
    arc_energy: list[float] = []
    for k in range(len(seq) - 1):
        dist = float(instance.distance[seq[k]][seq[k + 1]])
        payload = payload_on_arc[k] if k < len(payload_on_arc) else payload_return
        arc_energy.append(model.consumption(dist, payload))

    # energy_to_next_charge[k] = energy needed leaving stop k (1-based into seq)
    # until the next station in the route, or the depot.
    n_arcs = len(arc_energy)
    need_after = [0.0] * (n_arcs + 1)
    for k in range(n_arcs - 1, -1, -1):
        node = seq[k + 1]
        is_station = node != 0 and instance.is_station(node)
        need_after[k] = arc_energy[k] + (0.0 if is_station else need_after[k + 1])

    # -- walk the route ---------------------------------------------------
    soc = vehicle.battery_kwh
    clock = float(instance.depot.ready_time)
    sim.start_time = clock
    max_duration = vehicle.max_route_duration

    for pos, node in enumerate(body):
        prev = seq[pos]
        dist = float(instance.distance[prev][node])
        drive = float(instance.travel_time[prev][node])
        energy = arc_energy[pos]

        soc_arrival = soc - energy
        arrival = clock + drive
        sim.distance += dist
        sim.drive_time += drive
        sim.energy_consumed += energy

        if soc_arrival < vehicle.min_soc_kwh - EPS:
            sim.violations.append(
                Violation(
                    ViolationKind.BATTERY,
                    node,
                    vehicle.min_soc_kwh - soc_arrival,
                    f"arrives with {soc_arrival:.2f} kWh, below the "
                    f"{vehicle.min_soc_kwh:.2f} kWh reserve",
                )
            )

        info = instance.nodes[node]
        wait = max(0.0, info.ready_time - arrival)
        service_start = arrival + wait
        if arrival > info.due_time + EPS:
            kind = (
                ViolationKind.STATION_WINDOW
                if info.kind is NodeKind.STATION
                else ViolationKind.TIME_WINDOW
            )
            sim.violations.append(
                Violation(
                    kind,
                    node,
                    arrival - info.due_time,
                    f"arrives at {arrival:.1f}, {arrival - info.due_time:.1f} min after "
                    f"the window closes at {info.due_time:.1f}",
                )
            )

        charged = 0.0
        charge_time = 0.0
        soc_departure = soc_arrival
        if info.kind is NodeKind.STATION:
            station = instance.station_for_node(node)
            curve = ChargingCurve(station.power_kw, vehicle, charging_config)
            base = max(soc_arrival, 0.0)
            if charge_plan is not None and pos in charge_plan:
                target = min(vehicle.battery_kwh, base + max(0.0, float(charge_plan[pos])))
            elif charge_policy == "full":
                target = vehicle.battery_kwh
            elif charge_policy in ("none", "explicit"):
                target = base
            else:  # minimal
                required = need_after[pos + 1] + vehicle.min_soc_kwh
                target = min(vehicle.battery_kwh, max(base, required))
            charged = max(0.0, target - base)
            if charged > EPS:
                charge_time = curve.time_for(base, target)
            soc_departure = base + charged
            sim.energy_charged += charged
            sim.charge_time += charge_time

        departure = service_start + info.service_time + charge_time
        sim.wait_time += wait
        sim.service_time += info.service_time

        sim.stops.append(
            Stop(
                node=node,
                kind=info.kind,
                arrival=arrival,
                wait=wait,
                service_start=service_start,
                service_time=info.service_time,
                charge_time=charge_time,
                departure=departure,
                soc_arrival=soc_arrival,
                soc_departure=soc_departure,
                charged_kwh=charged,
                discharged_kwh=0.0,
                payload_on_arrival=payload_on_arc[pos],
                distance_from_prev=dist,
                energy_from_prev=energy,
            )
        )

        soc = soc_departure
        clock = departure

    # -- return leg -------------------------------------------------------
    last = body[-1]
    dist = float(instance.distance[last][0])
    drive = float(instance.travel_time[last][0])
    energy = arc_energy[-1]
    sim.distance += dist
    sim.drive_time += drive
    sim.energy_consumed += energy
    soc -= energy
    clock += drive
    sim.end_time = clock

    if soc < vehicle.min_soc_kwh - EPS:
        sim.violations.append(
            Violation(
                ViolationKind.BATTERY,
                0,
                vehicle.min_soc_kwh - soc,
                f"returns to depot with {soc:.2f} kWh, below the "
                f"{vehicle.min_soc_kwh:.2f} kWh reserve",
            )
        )
    if clock > instance.depot.due_time + EPS:
        sim.violations.append(
            Violation(
                ViolationKind.DURATION,
                0,
                clock - instance.depot.due_time,
                f"returns at {clock:.1f}, after the depot closes at "
                f"{instance.depot.due_time:.1f}",
            )
        )
    if max_duration is not None and sim.duration > max_duration + EPS:
        sim.violations.append(
            Violation(
                ViolationKind.DURATION,
                0,
                sim.duration - max_duration,
                f"route lasts {sim.duration:.1f} min, over the "
                f"{max_duration:.1f} min shift limit",
            )
        )

    sim.stops.append(
        Stop(
            node=0,
            kind=NodeKind.DEPOT,
            arrival=clock,
            wait=0.0,
            service_start=clock,
            service_time=0.0,
            charge_time=0.0,
            departure=clock,
            soc_arrival=soc,
            soc_departure=soc,
            charged_kwh=0.0,
            discharged_kwh=0.0,
            payload_on_arrival=payload_return,
            distance_from_prev=dist,
            energy_from_prev=energy,
        )
    )
    return sim


def route_is_feasible(instance: Instance, route: Sequence[int], **kwargs) -> bool:
    """Convenience wrapper returning only the verdict."""
    return simulate_route(instance, route, **kwargs).feasible
