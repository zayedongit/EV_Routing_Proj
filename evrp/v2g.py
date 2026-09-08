"""Vehicle-to-grid: routing detours that pay for themselves.

The original project treated "discharge back to the grid during peak hours" as
a bonus term bolted onto a cost function.  That version could not answer the
question a fleet operator actually asks, which is *whether it is worth driving
somewhere to do it*.

This module answers it explicitly.  For every route it prices the best V2G
detour:

    net gain = (V2G revenue - energy bought) - detour_km * cost_per_km

The revenue side is not guessed: for each candidate (station, position) the
resulting stop sequence is handed to the exact schedule optimiser in
:mod:`evrp.schedule`, which decides how much can really be sold given the
battery reserve, the charging power and the time windows that the detour has
just made tighter.  A detour is accepted only if it clears the bar and the
route still simulates clean.

The result is a measurable comparison -- routing with grid discharge versus
without -- rather than an assertion that V2G helps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from evrp.config import ChargingConfig, EnergyConfig
from evrp.feasibility import simulate_route
from evrp.instance import Instance
from evrp.schedule import ScheduleResult, optimise_schedule
from evrp.solution import Solution


@dataclass
class V2GDecision:
    """What happened to one route."""

    route_index: int
    accepted: bool
    station: int | None = None
    position: int | None = None
    detour_km: float = 0.0
    detour_cost: float = 0.0
    revenue: float = 0.0
    energy_cost: float = 0.0
    discharged_kwh: float = 0.0
    net_gain: float = 0.0
    route: list[int] = field(default_factory=list)
    schedule: ScheduleResult | None = None


@dataclass
class V2GReport:
    decisions: list[V2GDecision] = field(default_factory=list)
    baseline_distance: float = 0.0
    distance: float = 0.0
    total_discharged_kwh: float = 0.0
    total_revenue: float = 0.0
    total_energy_cost: float = 0.0
    total_detour_cost: float = 0.0

    @property
    def accepted(self) -> list[V2GDecision]:
        return [d for d in self.decisions if d.accepted]

    @property
    def net_gain(self) -> float:
        return self.total_revenue - self.total_energy_cost - self.total_detour_cost

    @property
    def extra_km(self) -> float:
        return self.distance - self.baseline_distance

    def to_dict(self) -> dict:
        return {
            "routes_with_v2g": len(self.accepted),
            "baseline_distance_km": round(self.baseline_distance, 3),
            "distance_km": round(self.distance, 3),
            "extra_km": round(self.extra_km, 3),
            "discharged_kwh": round(self.total_discharged_kwh, 3),
            "revenue": round(self.total_revenue, 3),
            "energy_cost": round(self.total_energy_cost, 3),
            "detour_cost": round(self.total_detour_cost, 3),
            "net_gain": round(self.net_gain, 3),
        }


def best_v2g_detour(
    instance: Instance,
    route: Sequence[int],
    energy_config: EnergyConfig,
    charging_config: ChargingConfig,
    max_candidates: int | None = None,
) -> V2GDecision:
    """Price the most profitable single V2G stop for one route."""
    body = [int(n) for n in route if int(n) != 0]
    baseline = V2GDecision(route_index=-1, accepted=False, route=list(body))
    if not body or not instance.station_indices:
        return baseline

    v2g_cfg = ChargingConfig(**{**charging_config.__dict__, "v2g_enabled": True})
    dist = instance.distance
    cost_per_km = charging_config.distance_cost_per_km

    candidates: list[tuple[float, int, int]] = []
    seq = [0, *body, 0]
    for pos in range(1, len(seq)):
        a, b = seq[pos - 1], seq[pos]
        for s in instance.station_indices:
            station = instance.station_for_node(s)
            if not station.v2g_capable:
                continue
            detour = float(dist[a][s] + dist[s][b] - dist[a][b])
            candidates.append((detour, s, pos - 1))
    candidates.sort(key=lambda t: t[0])
    if max_candidates is not None:
        candidates = candidates[:max_candidates]

    best = baseline
    for detour, s, insert_at in candidates:
        detour_cost = detour * cost_per_km
        # The revenue of one stop is bounded by selling the whole usable pack;
        # once the detour costs more than that, no later candidate can win.
        ceiling = instance.vehicle.battery_kwh * v2g_cfg.v2g_price
        if detour_cost >= ceiling:
            break
        candidate = body[:insert_at] + [s] + body[insert_at:]
        sim = simulate_route(
            instance,
            candidate,
            energy_config=energy_config,
            charging_config=v2g_cfg,
            charge_policy="minimal",
        )
        if not sim.feasible:
            continue
        sched = optimise_schedule(instance, candidate, energy_config, v2g_cfg)
        if not sched.feasible or sched.total_discharged <= 1e-6:
            continue
        gain = sched.v2g_revenue - sched.energy_cost - detour_cost
        if gain > best.net_gain + 1e-9:
            best = V2GDecision(
                route_index=-1,
                accepted=gain > 0,
                station=s,
                position=insert_at,
                detour_km=detour,
                detour_cost=detour_cost,
                revenue=sched.v2g_revenue,
                energy_cost=sched.energy_cost,
                discharged_kwh=sched.total_discharged,
                net_gain=gain,
                route=candidate,
                schedule=sched,
            )
    return best


def apply_v2g(
    instance: Instance,
    solution: Solution,
    energy_config: EnergyConfig | None = None,
    charging_config: ChargingConfig | None = None,
    max_candidates: int | None = 12,
) -> tuple[Solution, V2GReport]:
    """Return a copy of ``solution`` with profitable V2G detours inserted."""
    energy_config = energy_config or EnergyConfig()
    charging_config = charging_config or ChargingConfig()
    v2g_cfg = ChargingConfig(**{**charging_config.__dict__, "v2g_enabled": True})

    report = V2GReport(baseline_distance=solution.metrics.total_distance)
    new_routes: list[list[int]] = []
    plans: list[dict[int, float]] = []

    for i, route in enumerate(solution.routes):
        decision = best_v2g_detour(
            instance, route, energy_config, charging_config, max_candidates
        )
        decision.route_index = i
        report.decisions.append(decision)
        if decision.accepted and decision.schedule is not None:
            new_routes.append(decision.route)
            plans.append(dict(decision.schedule.charge_kwh))
            report.total_discharged_kwh += decision.discharged_kwh
            report.total_revenue += decision.revenue
            report.total_energy_cost += decision.energy_cost
            report.total_detour_cost += decision.detour_cost
        else:
            new_routes.append(list(route))
            plans.append({})

    out = Solution(
        instance_name=solution.instance_name,
        solver=f"{solution.solver}+v2g",
        routes=new_routes,
        runtime_s=solution.runtime_s,
        status=solution.status,
        meta={**solution.meta, "v2g": report.to_dict()},
    )
    out.evaluate(
        instance,
        energy_config=energy_config,
        charging_config=v2g_cfg,
        charge_plans=plans,
        charge_policy="minimal",
    )
    # The simulator does not model selling, so fold the scheduler's decisions in.
    out.metrics.energy_discharged_kwh = report.total_discharged_kwh
    out.metrics.v2g_revenue = report.total_revenue
    report.distance = out.metrics.total_distance
    out.meta["v2g"] = report.to_dict()
    return out, report
