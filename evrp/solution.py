"""Solution container and the metrics used to compare approaches."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from evrp.config import ChargingConfig, EnergyConfig
from evrp.feasibility import RouteSimulation, Violation, simulate_route
from evrp.instance import Instance


@dataclass
class SolutionMetrics:
    """Everything a comparison table needs, all measured from the simulator."""

    total_distance: float = 0.0
    total_duration: float = 0.0
    total_drive_time: float = 0.0
    total_wait_time: float = 0.0
    total_charge_time: float = 0.0
    energy_consumed_kwh: float = 0.0
    energy_charged_kwh: float = 0.0
    energy_discharged_kwh: float = 0.0
    vehicles_used: int = 0
    customers_served: int = 0
    customers_total: int = 0
    charging_stops: int = 0
    min_soc_kwh: float = 0.0
    energy_cost: float = 0.0
    v2g_revenue: float = 0.0
    n_violations: int = 0

    @property
    def served_all(self) -> bool:
        return self.customers_served == self.customers_total

    @property
    def net_energy_cost(self) -> float:
        return self.energy_cost - self.v2g_revenue

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["served_all"] = self.served_all
        d["net_energy_cost"] = self.net_energy_cost
        return d


@dataclass
class Solution:
    """A set of routes plus its verified metrics.

    ``routes`` are node-index sequences without the depot sentinels.  Nothing
    in this class trusts the solver that produced it: :meth:`evaluate` replays
    every route through :mod:`evrp.feasibility` and records what actually
    happens.
    """

    instance_name: str
    solver: str
    routes: list[list[int]] = field(default_factory=list)
    simulations: list[RouteSimulation] = field(default_factory=list)
    metrics: SolutionMetrics = field(default_factory=SolutionMetrics)
    runtime_s: float = 0.0
    status: str = "unknown"
    meta: dict[str, Any] = field(default_factory=dict)

    # -- verification -----------------------------------------------------
    def evaluate(
        self,
        instance: Instance,
        energy_config: EnergyConfig | None = None,
        charging_config: ChargingConfig | None = None,
        charge_policy: str = "minimal",
        charge_plans: Sequence[dict[int, float]] | None = None,
    ) -> "Solution":
        """Re-simulate every route and refresh :attr:`metrics`."""
        charging_config = charging_config or ChargingConfig()
        self.simulations = []
        m = SolutionMetrics(customers_total=instance.n_customers)
        served: set[int] = set()
        min_soc = float("inf")

        for i, route in enumerate(self.routes):
            plan = charge_plans[i] if charge_plans is not None and i < len(charge_plans) else None
            sim = simulate_route(
                instance,
                route,
                energy_config=energy_config,
                charging_config=charging_config,
                charge_plan=plan,
                charge_policy=charge_policy,
            )
            self.simulations.append(sim)
            # Count violations first: a route rejected before it starts (an
            # out-of-range node index, say) produces no stops but must not be
            # allowed to disappear from the report.
            m.n_violations += len(sim.violations)
            if not sim.stops:
                continue
            m.total_distance += sim.distance
            m.total_duration += sim.duration
            m.total_drive_time += sim.drive_time
            m.total_wait_time += sim.wait_time
            m.total_charge_time += sim.charge_time
            m.energy_consumed_kwh += sim.energy_consumed
            m.energy_charged_kwh += sim.energy_charged
            m.energy_discharged_kwh += sim.energy_discharged
            m.charging_stops += sim.n_charging_stops
            m.vehicles_used += 1
            served.update(n for n in sim.route if instance.nodes[n].kind.value == "customer")
            min_soc = min(min_soc, sim.min_soc)

        m.customers_served = len(served)
        m.min_soc_kwh = 0.0 if min_soc == float("inf") else min_soc
        m.energy_cost = m.energy_charged_kwh * charging_config.energy_price
        m.v2g_revenue = m.energy_discharged_kwh * charging_config.v2g_price
        self.metrics = m
        return self

    # -- queries ----------------------------------------------------------
    @property
    def feasible(self) -> bool:
        return (
            self.metrics.n_violations == 0
            and self.metrics.served_all
            and bool(self.routes)
        )

    @property
    def violations(self) -> list[Violation]:
        return [v for sim in self.simulations for v in sim.violations]

    def unserved(self, instance: Instance) -> list[int]:
        served = {n for r in self.routes for n in r}
        return [c for c in instance.customer_indices if c not in served]

    # -- serialisation ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "instance": self.instance_name,
            "solver": self.solver,
            "status": self.status,
            "runtime_s": round(self.runtime_s, 4),
            "feasible": self.feasible,
            "routes": [list(r) for r in self.routes],
            "metrics": self.metrics.to_dict(),
            "violations": [
                {"kind": v.kind.value, "node": v.node, "magnitude": v.magnitude,
                 "message": v.message}
                for v in self.violations
            ],
            "meta": self.meta,
        }

    def to_json(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, default=str) + "\n")

    def summary(self) -> str:
        m = self.metrics
        head = (
            f"{self.solver} on {self.instance_name}: "
            f"{m.total_distance:.2f} km, {m.vehicles_used} vehicles, "
            f"{m.customers_served}/{m.customers_total} customers, "
            f"{m.charging_stops} charging stops, {self.runtime_s:.2f}s"
        )
        if not self.feasible:
            reasons = []
            if m.n_violations:
                reasons.append(f"{m.n_violations} constraint violation(s)")
            if not m.served_all:
                reasons.append(
                    f"{m.customers_total - m.customers_served} customer(s) unserved"
                )
            if not self.routes:
                reasons.append("no routes")
            head += "  [INFEASIBLE: " + "; ".join(reasons) + "]"
        return head
