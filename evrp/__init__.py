"""EV routing optimisation: energy-aware vehicle routing with time windows.

The package is organised in layers:

``evrp.config``       parameter objects (vehicle, energy, solver, scenario)
``evrp.instance``     problem instances (depot, customers, charging stations, matrices)
``evrp.energy``       battery / consumption / charging-curve models
``evrp.feasibility``  an independent route simulator used as ground truth
``evrp.solvers``      interchangeable solvers behind one interface
``evrp.benchmark``    reproducible experiment harness
"""

from evrp.config import (
    ChargingConfig,
    EnergyConfig,
    Scenario,
    SolverConfig,
    VehicleSpec,
)
from evrp.instance import ChargingStation, Instance, Node, NodeKind
from evrp.feasibility import RouteSimulation, Violation, simulate_route
from evrp.solution import Solution

__all__ = [
    "ChargingConfig",
    "ChargingStation",
    "EnergyConfig",
    "Instance",
    "Node",
    "NodeKind",
    "RouteSimulation",
    "Scenario",
    "Solution",
    "SolverConfig",
    "VehicleSpec",
    "Violation",
    "simulate_route",
]

__version__ = "0.2.0"
