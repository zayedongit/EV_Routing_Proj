"""Legacy task 1: VRP with time windows, solved with OR-Tools.

Kept for continuity with the original project (``main.py`` and the notebooks
still call it), but with the correctness bugs fixed.  New work should use
:mod:`evrp.solvers.ortools_evrptw`, which additionally models the battery,
charging stations and charging time.

What was wrong before, and why it mattered
------------------------------------------
* **Vehicle capacity was hard-coded to 100.**  Solomon C1/R1/RC1 instances
  prescribe 200 (C2 700, R2/RC2 1000).  C101 has a total demand of 1810, so
  ten 100-unit vehicles could never serve it and the solver returned
  "No solution found!" for a reason that had nothing to do with routing.
* **Travel time was computed as ``distance / 50 * 60``.**  The Solomon
  convention is that travel time *equals* Euclidean distance; scaling it by
  1.2 makes every time window 20 % tighter than the benchmark defines and
  makes the results incomparable with published ones.
* **Distances were truncated with ``int()``.**  Losing up to 1 km per arc is a
  systematic bias of several percent on a 100-customer instance.  Costs are
  now scaled to centi-kilometres before rounding.
* **Failure raised a bare ``Exception``** with no diagnosis.  It now raises a
  typed error that reports which constraint makes the instance impossible.
"""

from __future__ import annotations

import math
from typing import Dict, List

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from models.ev import Customer, Depot, ElectricVehicle
from utils.distance import euclidean_distance

DIST_SCALE = 100  # cost unit: centi-kilometres


class NoSolutionError(RuntimeError):
    """Raised when no feasible routing exists for the given fleet."""


class VRPSolver:
    """VRP with time windows.

    Args:
        depot: the depot.
        customers: customers to serve.
        vehicle_count: fleet size.
        vehicle_capacity: payload per vehicle.  Defaults to 200, the Solomon
            value for the C1/R1/RC1 families.
        speed: distance units per time unit.  Defaults to 1.0, the Solomon
            convention under which travel time equals distance.
        time_limit_s: search budget.
        max_route_distance: per-vehicle distance cap.
    """

    def __init__(
        self,
        depot: Depot,
        customers: List[Customer],
        vehicle_count: int,
        vehicle_capacity: float = 200.0,
        speed: float = 1.0,
        time_limit_s: float = 30.0,
        max_route_distance: float = 10_000.0,
        span_cost_coefficient: int = 0,
    ) -> None:
        if vehicle_count <= 0:
            raise ValueError("vehicle_count must be > 0")
        if vehicle_capacity <= 0:
            raise ValueError("vehicle_capacity must be > 0")
        if speed <= 0:
            raise ValueError("speed must be > 0")
        self.depot = depot
        self.customers = customers
        self.vehicle_count = vehicle_count
        self.vehicle_capacity = vehicle_capacity
        self.speed = speed
        self.time_limit_s = time_limit_s
        self.max_route_distance = max_route_distance
        self.span_cost_coefficient = span_cost_coefficient
        self.vehicles = [ElectricVehicle(f"EV{i + 1}") for i in range(vehicle_count)]

    # -- data -------------------------------------------------------------
    def create_data_model(self) -> Dict:
        data: Dict = {}
        data["distance_matrix"] = self._create_distance_matrix()
        data["demands"] = [0.0] + [c.demand for c in self.customers]
        data["time_windows"] = [
            (int(self.depot.ready_time), int(self.depot.due_date))
        ] + [(int(c.ready_time), int(c.due_date)) for c in self.customers]
        data["service_times"] = [0] + [int(c.service_time) for c in self.customers]
        data["num_vehicles"] = self.vehicle_count
        data["depot"] = 0
        return data

    def _create_distance_matrix(self) -> List[List[float]]:
        locations = [self.depot] + list(self.customers)
        return [
            [euclidean_distance(a.x, a.y, b.x, b.y) for b in locations]
            for a in locations
        ]

    def diagnose(self, data: Dict) -> List[str]:
        """Reasons the instance may be unsolvable, in plain language."""
        issues: List[str] = []
        total_demand = sum(data["demands"])
        fleet_capacity = self.vehicle_capacity * self.vehicle_count
        if total_demand > fleet_capacity:
            issues.append(
                f"total demand {total_demand:g} exceeds fleet capacity "
                f"{fleet_capacity:g}; at least "
                f"{math.ceil(total_demand / self.vehicle_capacity)} vehicles are needed"
            )
        for c in self.customers:
            if c.demand > self.vehicle_capacity:
                issues.append(
                    f"customer {c.id} demands {c.demand:g}, more than one vehicle carries"
                )
            travel = euclidean_distance(self.depot.x, self.depot.y, c.x, c.y) / self.speed
            if travel > c.due_time if hasattr(c, "due_time") else travel > c.due_date:
                issues.append(
                    f"customer {c.id} cannot be reached before its window closes"
                )
        return issues

    # -- solve ------------------------------------------------------------
    def solve(self) -> List[Dict]:
        data = self.create_data_model()
        matrix = data["distance_matrix"]

        manager = pywrapcp.RoutingIndexManager(
            len(matrix), data["num_vehicles"], data["depot"]
        )
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(from_index, to_index):
            i = manager.IndexToNode(from_index)
            j = manager.IndexToNode(to_index)
            return int(round(matrix[i][j] * DIST_SCALE))

        transit_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_index)

        routing.AddDimension(
            transit_index,
            0,
            int(self.max_route_distance * DIST_SCALE),
            True,
            "Distance",
        )
        if self.span_cost_coefficient:
            routing.GetDimensionOrDie("Distance").SetGlobalSpanCostCoefficient(
                self.span_cost_coefficient
            )

        def demand_callback(from_index):
            return int(round(data["demands"][manager.IndexToNode(from_index)]))

        demand_index = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_index,
            0,
            [int(round(self.vehicle_capacity))] * data["num_vehicles"],
            True,
            "Capacity",
        )

        horizon = int(self.depot.due_date)

        def time_callback(from_index, to_index):
            i = manager.IndexToNode(from_index)
            j = manager.IndexToNode(to_index)
            travel = matrix[i][j] / self.speed
            service = data["service_times"][i] if i != data["depot"] else 0
            return int(round(travel + service))

        time_index = routing.RegisterTransitCallback(time_callback)
        routing.AddDimension(time_index, horizon, horizon, False, "Time")
        time_dimension = routing.GetDimensionOrDie("Time")

        for node, (ready, due) in enumerate(data["time_windows"]):
            if node == data["depot"]:
                continue
            index = manager.NodeToIndex(node)
            time_dimension.CumulVar(index).SetRange(ready, min(due, horizon))

        for vehicle_id in range(data["num_vehicles"]):
            start = routing.Start(vehicle_id)
            time_dimension.CumulVar(start).SetRange(int(self.depot.ready_time), horizon)
            routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(start))
            routing.AddVariableMinimizedByFinalizer(
                time_dimension.CumulVar(routing.End(vehicle_id))
            )

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_parameters.time_limit.FromMilliseconds(int(self.time_limit_s * 1000))

        solution = routing.SolveWithParameters(search_parameters)
        if solution is None:
            issues = self.diagnose(data)
            detail = "; ".join(issues) if issues else "no obvious cause found"
            raise NoSolutionError(f"no feasible routing for this fleet ({detail})")
        return self._get_routes(data, manager, routing, solution)

    def _get_routes(self, data, manager, routing, solution) -> List[Dict]:
        routes: List[Dict] = []
        matrix = data["distance_matrix"]
        for vehicle_id in range(data["num_vehicles"]):
            index = routing.Start(vehicle_id)
            nodes: List[int] = []
            distance = 0.0
            load = 0.0
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                nodes.append(node)
                load += data["demands"][node]
                nxt = solution.Value(routing.NextVar(index))
                distance += matrix[node][manager.IndexToNode(nxt)]
                index = nxt
            if len(nodes) > 1:
                routes.append(
                    {
                        "vehicle_id": vehicle_id,
                        "route": nodes,
                        "distance": distance,
                        "load": load,
                        "customers_served": len(nodes) - 1,
                    }
                )
        return routes
