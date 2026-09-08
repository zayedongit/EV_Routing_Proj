"""Common solver interface."""

from __future__ import annotations

import abc
import time
from contextlib import contextmanager

from evrp.config import ChargingConfig, EnergyConfig, SolverConfig
from evrp.instance import Instance
from evrp.solution import Solution


class SolverError(RuntimeError):
    """Raised when a solver cannot produce any solution at all."""


class Solver(abc.ABC):
    """Base class for every routing backend.

    Subclasses implement :meth:`_solve`, which returns raw routes.  The public
    :meth:`solve` wraps that with timing and -- crucially -- with an
    independent feasibility evaluation, so no solver reports its own verdict.
    """

    name = "solver"

    def __init__(
        self,
        solver_config: SolverConfig | None = None,
        energy_config: EnergyConfig | None = None,
        charging_config: ChargingConfig | None = None,
    ) -> None:
        self.solver_config = solver_config or SolverConfig()
        self.energy_config = energy_config or EnergyConfig()
        self.charging_config = charging_config or ChargingConfig()
        self.solver_config.validate()
        self.energy_config.validate()
        self.charging_config.validate()

    @abc.abstractmethod
    def _solve(self, instance: Instance) -> tuple[list[list[int]], str, dict]:
        """Return ``(routes, status, meta)``; routes exclude depot sentinels."""

    def solve(self, instance: Instance) -> Solution:
        start = time.perf_counter()
        routes, status, meta = self._solve(instance)
        runtime = time.perf_counter() - start

        charge_plans = meta.pop("charge_plans", None)
        # Drop empty routes, but keep the charging plans aligned with what
        # survives.  Filtering the two lists independently silently shifts every
        # plan by one route, which shows up as a solver that "forgot" to charge.
        if charge_plans is None:
            routes = [list(r) for r in routes if r]
        else:
            paired = [
                (list(r), p)
                for r, p in zip(routes, list(charge_plans) + [{}] * len(routes))
                if r
            ]
            routes = [r for r, _ in paired]
            charge_plans = [p for _, p in paired]

        solution = Solution(
            instance_name=instance.name,
            solver=self.name,
            routes=routes,
            runtime_s=runtime,
            status=status,
            meta=meta,
        )
        solution.evaluate(
            instance,
            energy_config=self.energy_config,
            charging_config=self.charging_config,
            charge_plans=charge_plans,
            charge_policy=meta.get("charge_policy", "minimal"),
        )
        return solution


@contextmanager
def deadline(seconds: float):
    """Small helper giving heuristics a wall-clock budget."""
    end = time.perf_counter() + seconds
    yield lambda: time.perf_counter() >= end
