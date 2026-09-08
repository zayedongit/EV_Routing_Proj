"""Interchangeable solvers behind one interface.

``registry`` maps a short name to a factory so the CLI and the benchmark
harness can select a solver by string without importing every backend.
"""

from __future__ import annotations

from typing import Callable

from evrp.solvers.base import Solver, SolverError

_REGISTRY: dict[str, Callable[..., Solver]] = {}


def register(name: str, factory: Callable[..., Solver]) -> None:
    _REGISTRY[name] = factory


def available() -> list[str]:
    return sorted(_REGISTRY)


def create(name: str, **kwargs) -> Solver:
    if name not in _REGISTRY:
        raise SolverError(f"unknown solver {name!r}; available: {available()}")
    return _REGISTRY[name](**kwargs)


def _bootstrap() -> None:
    from evrp.solvers.ortools_evrptw import ORToolsEVRPTWSolver
    from evrp.solvers.heuristic import InsertionLocalSearchSolver, SavingsSolver

    register("ortools", ORToolsEVRPTWSolver)
    register("insertion", lambda **kw: InsertionLocalSearchSolver(local_search=False, **kw))
    register("insertion-ls", InsertionLocalSearchSolver)
    register("savings", SavingsSolver)


_bootstrap()

__all__ = ["Solver", "SolverError", "available", "create", "register"]
