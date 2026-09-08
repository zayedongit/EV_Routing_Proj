"""E-VRPTW as a constraint-programming routing model (OR-Tools).

Modelling the battery
---------------------
The interesting part of an electric VRP is that the battery is a resource that
can be *replenished mid-route*, which classic VRP dimensions cannot express:
an OR-Tools dimension only ever accumulates, ``cumul(j) = cumul(i) +
transit(i,j) + slack(i)``, and slack is non-negative.

The trick used here is to track **remaining state of charge** rather than
energy consumed:

* ``transit(i, j) = -energy(i, j)``  -- driving is a negative transit,
* ``slack(i)``                       -- energy pushed into the pack at ``i``,
* ``cumul`` bounded to ``[reserve, battery]``.

Slack is forced to zero everywhere except at charging nodes, so the only place
the pack can gain energy is at a charger, and the amount charged becomes a
decision variable of the search rather than a fixed policy.

Charging stations may be visited more than once by different vehicles, so each
station is replicated ``station_copies`` times as an *optional* node (a
disjunction with zero penalty), the standard reformulation for
E-VRPTW with recharging.

Charging **time** is modelled as a **fixed-length charging session**.  Every
station visit costs ``charge_stop_minutes`` of dwell time -- an ordinary term
in the time transit callback, so it is enforced like any other travel time --
and the energy one visit may add is capped at what the charger is guaranteed
to deliver in that window at its slowest (taper) rate.  Charging more means
stopping again, and paying for another session.

That structure replaces the obvious-looking alternative, a constraint tying
the time dimension's slack variable to the energy dimension's slack variable.
That constraint did not hold in the solutions this OR-Tools build returned:
the independent simulator flagged routes where several kWh appeared in zero
minutes, and it reproduced on a four-node instance where the link bound at the
last charging stop of a route but not at earlier ones.  A per-visit transit
needs no cross-dimension reasoning and cannot be quietly dropped.

Relaxation safety
-----------------
The CP model must never call a route feasible that the exact simulator in
:mod:`evrp.feasibility` rejects.  Two approximations are therefore taken in
the conservative direction:

* consumption uses a payload-independent **upper bound** (the rate at full
  payload) while the simulator uses the true, lighter, load-dependent rate;
* charging power uses the **taper** power of the CC-CV curve, an upper bound
  on the time needed for any amount of energy.

``SolverConfig`` exposes ``model_charge_power_mode`` so the cost of that
conservatism can be measured rather than assumed -- see ``docs/`` and the
benchmark harness.
"""

from __future__ import annotations

import math
from typing import Any

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from evrp.config import ChargingConfig, EnergyConfig, SolverConfig
from evrp.energy import ChargingCurve, EnergyModel
from evrp.instance import Instance, NodeKind
from evrp.solvers.base import Solver, SolverError

DIST_SCALE = 100      # centi-km, keeps arc costs from being truncated to int
TIME_SCALE = 10       # deci-minutes
ENERGY_SCALE = 1000   # Wh

FIRST_SOLUTION_STRATEGIES = {
    "PATH_CHEAPEST_ARC": routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC,
    "PARALLEL_CHEAPEST_INSERTION":
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION,
    "SAVINGS": routing_enums_pb2.FirstSolutionStrategy.SAVINGS,
    "CHRISTOFIDES": routing_enums_pb2.FirstSolutionStrategy.CHRISTOFIDES,
    "AUTOMATIC": routing_enums_pb2.FirstSolutionStrategy.AUTOMATIC,
}

METAHEURISTICS = {
    "GUIDED_LOCAL_SEARCH": routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH,
    "SIMULATED_ANNEALING": routing_enums_pb2.LocalSearchMetaheuristic.SIMULATED_ANNEALING,
    "TABU_SEARCH": routing_enums_pb2.LocalSearchMetaheuristic.TABU_SEARCH,
    "GREEDY_DESCENT": routing_enums_pb2.LocalSearchMetaheuristic.GREEDY_DESCENT,
    "AUTOMATIC": routing_enums_pb2.LocalSearchMetaheuristic.AUTOMATIC,
}


def _prune_idle_charging_stops(
    instance: Instance, route: list[int], plan: dict[int, float]
) -> tuple[list[int], dict[int, float]]:
    """Drop station visits where nothing was charged.

    Station replicas are free to enter (zero-penalty disjunctions), so the
    search sometimes parks an unused one on a route.  Removing it can only
    shorten the route -- the triangle inequality holds for every metric here --
    and never changes the energy trajectory, because no energy was added.
    """
    kept: list[int] = []
    new_plan: dict[int, float] = {}
    for pos, node in enumerate(route):
        if instance.is_station(node) and plan.get(pos, 0.0) <= 1e-9:
            continue
        if instance.is_station(node):
            new_plan[len(kept)] = plan[pos]
        kept.append(node)
    return kept, new_plan


class ORToolsEVRPTWSolver(Solver):
    """Energy-aware VRPTW solved with the OR-Tools routing library."""

    name = "ortools"

    def __init__(
        self,
        solver_config: SolverConfig | None = None,
        energy_config: EnergyConfig | None = None,
        charging_config: ChargingConfig | None = None,
        allow_dropping_customers: bool = True,
        drop_penalty: float = 1e6,
        enforce_energy: bool = True,
        span_cost_coefficient: int = 0,
        strategy_portfolio: bool = True,
    ) -> None:
        super().__init__(solver_config, energy_config, charging_config)
        self.strategy_portfolio = strategy_portfolio
        self.allow_dropping_customers = allow_dropping_customers
        self.drop_penalty = drop_penalty
        self.enforce_energy = enforce_energy
        self.span_cost_coefficient = span_cost_coefficient
        self.last_model: dict[str, Any] | None = None

    # -- model construction ----------------------------------------------
    def _model_nodes(self, instance: Instance) -> list[int]:
        """Model node -> instance node.  Stations appear ``station_copies`` times."""
        nodes = list(range(instance.n_customers + 1))
        copies = self.solver_config.station_copies
        if self.enforce_energy and copies > 0:
            for s in instance.station_indices:
                nodes.extend([s] * copies)
        return nodes

    def _charge_quantum_kwh(self, instance: Instance, node: int) -> float:
        """Energy one charging session is guaranteed to deliver.

        Priced at the charger's slowest rate, so the real CC-CV curve -- which
        is at least this fast everywhere -- always finishes inside the session
        and the simulator can never find the stop running over.
        """
        power_kw = self._charge_power_kw(instance, node)
        session = max(
            0.0,
            self.solver_config.charge_stop_minutes - self.charging_config.fixed_time_min,
        )
        return power_kw * session / 60.0

    def _charge_power_kw(self, instance: Instance, node: int) -> float:
        station = instance.station_for_node(node)
        curve = ChargingCurve(station.power_kw, instance.vehicle, self.charging_config)
        mode = getattr(self.solver_config, "model_charge_power_mode", "conservative")
        if mode == "nominal":
            return curve.power_kw
        return curve.taper_power_kw

    def _solve(self, instance: Instance) -> tuple[list[list[int]], str, dict[str, Any]]:
        """Run the CP model, falling back to other construction heuristics.

        The first-solution strategy matters more here than in a plain VRP.
        ``PATH_CHEAPEST_ARC`` builds routes greedily arc by arc and, on an
        energy-tight instance, happily drives to the far customer before
        discovering it cannot get home -- there is no charging station left to
        insert, so the customer is dropped and local search never recovers.
        Insertion-based construction places the station first.  Rather than
        pick one strategy and hope, the solver runs a small portfolio and keeps
        the best verified result; the reported runtime covers every attempt.
        """
        attempts = [self.solver_config.first_solution]
        if self.strategy_portfolio:
            for extra in ("PARALLEL_CHEAPEST_INSERTION", "SAVINGS"):
                if extra not in attempts:
                    attempts.append(extra)

        best: tuple[list[list[int]], str, dict[str, Any]] | None = None
        best_key: tuple[int, float] | None = None
        errors: list[str] = []
        for strategy in attempts:
            try:
                routes, status, meta = self._solve_once(instance, strategy)
            except SolverError as exc:
                errors.append(f"{strategy}: {exc}")
                continue
            served = len({n for r in routes for n in r if not instance.is_station(n)})
            distance = sum(
                float(instance.distance[a][b])
                for r in routes
                for a, b in zip([0, *r], [*r, 0])
            )
            key = (-served, distance)
            if best_key is None or key < best_key:
                best_key, best = key, (routes, status, meta)
                meta["first_solution"] = strategy
            if served == instance.n_customers:
                break

        if best is None:
            raise SolverError(
                "OR-Tools found no solution with any first-solution strategy. "
                + " | ".join(errors)
                + f" Instance diagnostics: {instance.diagnostics()[:3]}"
            )
        best[2]["strategies_tried"] = attempts[: attempts.index(best[2]["first_solution"]) + 1]
        return best

    def _solve_once(
        self, instance: Instance, first_solution: str
    ) -> tuple[list[list[int]], str, dict[str, Any]]:
        cfg = self.solver_config
        vehicle = instance.vehicle
        model_nodes = self._model_nodes(instance)
        n_model = len(model_nodes)
        n_vehicles = instance.fleet_size

        energy_model = EnergyModel(self.energy_config, vehicle)
        # The CP model cannot know the payload on an arc, so consumption has to
        # be payload-independent.  "worst" (the rate at full payload) is the
        # only choice that guarantees a model-feasible route also passes the
        # exact simulator; the looser modes trade that guarantee for shorter
        # routes and are there to be measured, not assumed.
        payload_for_rate = {
            "worst": vehicle.payload_capacity,
            "average": vehicle.payload_capacity / 2.0,
            "empty": 0.0,
        }[cfg.model_consumption_mode]
        worst_rate = energy_model.rate_kwh_per_km(payload_for_rate)

        manager = pywrapcp.RoutingIndexManager(n_model, n_vehicles, 0)
        routing = pywrapcp.RoutingModel(manager)

        dist = instance.distance
        tt = instance.travel_time

        def to_node(index: int) -> int:
            return model_nodes[manager.IndexToNode(index)]

        # -- arc cost: distance ------------------------------------------
        def distance_cb(i: int, j: int) -> int:
            return int(round(dist[to_node(i)][to_node(j)] * DIST_SCALE))

        distance_idx = routing.RegisterTransitCallback(distance_cb)
        routing.SetArcCostEvaluatorOfAllVehicles(distance_idx)
        if cfg.vehicle_fixed_cost:
            routing.SetFixedCostOfAllVehicles(int(round(cfg.vehicle_fixed_cost * DIST_SCALE)))

        routing.AddDimension(
            distance_idx, 0, int(1e9), True, "Distance"
        )
        if self.span_cost_coefficient:
            routing.GetDimensionOrDie("Distance").SetGlobalSpanCostCoefficient(
                self.span_cost_coefficient
            )

        # -- capacity ------------------------------------------------------
        def demand_cb(i: int) -> int:
            return int(round(instance.nodes[to_node(i)].demand))

        demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
        routing.AddDimensionWithVehicleCapacity(
            demand_idx,
            0,
            [int(round(vehicle.payload_capacity))] * n_vehicles,
            True,
            "Capacity",
        )

        # -- time (travel + service + waiting + one charging session) --------
        session_minutes = max(
            self.charging_config.fixed_time_min, cfg.charge_stop_minutes
        )

        def time_cb(i: int, j: int) -> int:
            frm = to_node(i)
            node = instance.nodes[frm]
            service = node.service_time
            if node.kind is NodeKind.STATION:
                service = session_minutes
            return int(round((tt[frm][to_node(j)] + service) * TIME_SCALE))

        time_idx = routing.RegisterTransitCallback(time_cb)
        horizon = int(round(instance.horizon * TIME_SCALE))
        routing.AddDimension(time_idx, horizon, horizon, False, "Time")
        time_dim = routing.GetDimensionOrDie("Time")

        for model_node in range(1, n_model):
            node = instance.nodes[model_nodes[model_node]]
            index = manager.NodeToIndex(model_node)
            if index < 0:
                continue
            time_dim.CumulVar(index).SetRange(
                int(round(node.ready_time * TIME_SCALE)),
                int(round(min(node.due_time, instance.horizon) * TIME_SCALE)),
            )
        for v in range(n_vehicles):
            time_dim.CumulVar(routing.Start(v)).SetRange(
                int(round(instance.depot.ready_time * TIME_SCALE)), horizon
            )
            time_dim.CumulVar(routing.End(v)).SetRange(0, horizon)
            routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.Start(v)))
            routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.End(v)))

        # -- state of charge ------------------------------------------------
        station_model_nodes: list[int] = []
        if self.enforce_energy:
            battery_wh = int(round(vehicle.battery_kwh * ENERGY_SCALE))
            reserve_wh = int(round(vehicle.min_soc_kwh * ENERGY_SCALE))

            def soc_cb(i: int, j: int) -> int:
                d = dist[to_node(i)][to_node(j)]
                return -int(math.ceil(worst_rate * d * ENERGY_SCALE))

            soc_idx = routing.RegisterTransitCallback(soc_cb)
            # With no chargers in the model nothing can add energy, so the
            # dimension needs no slack at all -- and telling the solver that
            # tightens propagation considerably.
            has_chargers = bool(instance.station_indices) and cfg.station_copies > 0
            soc_slack = battery_wh if has_chargers else 0
            routing.AddDimension(soc_idx, soc_slack, battery_wh, False, "Energy")
            soc_dim = routing.GetDimensionOrDie("Energy")

            for model_node in range(n_model):
                index = manager.NodeToIndex(model_node)
                if index < 0:
                    continue
                soc_dim.CumulVar(index).SetRange(reserve_wh, battery_wh)
                inst_node = model_nodes[model_node]
                if model_node != 0 and instance.is_station(inst_node):
                    station_model_nodes.append(model_node)
                    # One session delivers at most this much energy; the dwell
                    # time it costs is already priced into the time transit.
                    quantum_wh = min(
                        battery_wh,
                        int(self._charge_quantum_kwh(instance, inst_node) * ENERGY_SCALE),
                    )
                    soc_dim.SlackVar(index).SetRange(0, max(0, quantum_wh))
                    # Without this the pack can be "overfilled": the dimension
                    # only bounds the cumul *at* nodes, so a model that charges
                    # slack S at a node holding C is free to have C + S exceed
                    # the battery as long as the next arc burns the excess off.
                    # The bound has to be on the state at departure.
                    routing.solver().Add(
                        soc_dim.CumulVar(index) + soc_dim.SlackVar(index) <= battery_wh
                    )
                else:
                    soc_dim.SlackVar(index).SetValue(0)

            for v in range(n_vehicles):
                start = routing.Start(v)
                soc_dim.CumulVar(start).SetValue(battery_wh)
                soc_dim.SlackVar(start).SetValue(0)
                soc_dim.CumulVar(routing.End(v)).SetRange(reserve_wh, battery_wh)

        # -- optional nodes ---------------------------------------------------
        for model_node in station_model_nodes:
            index = manager.NodeToIndex(model_node)
            if index >= 0:
                routing.AddDisjunction([index], 0)
        if self.allow_dropping_customers:
            penalty = int(round(self.drop_penalty * DIST_SCALE))
            for model_node in range(1, instance.n_customers + 1):
                index = manager.NodeToIndex(model_node)
                if index >= 0:
                    routing.AddDisjunction([index], penalty)

        # -- search ------------------------------------------------------------
        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = FIRST_SOLUTION_STRATEGIES.get(
            first_solution, FIRST_SOLUTION_STRATEGIES["PATH_CHEAPEST_ARC"]
        )
        params.local_search_metaheuristic = METAHEURISTICS.get(
            cfg.metaheuristic, METAHEURISTICS["GUIDED_LOCAL_SEARCH"]
        )
        params.time_limit.FromMilliseconds(int(cfg.time_limit_s * 1000))
        params.log_search = bool(cfg.log_search)

        solution = routing.SolveWithParameters(params)
        status = {
            0: "not_solved", 1: "success", 2: "fail", 3: "fail_timeout", 4: "invalid",
        }.get(routing.status(), str(routing.status()))

        if solution is None:
            raise SolverError(
                "OR-Tools found no solution "
                f"(status={status}). Instance diagnostics: {instance.diagnostics()[:3]}"
            )

        # Kept for debugging and for tests that need to inspect the CP model
        # itself rather than only the routes it produced.
        self.last_model = {
            "manager": manager,
            "routing": routing,
            "solution": solution,
            "model_nodes": model_nodes,
        }
        routes, charge_plans = self._extract(
            instance, manager, routing, solution, model_nodes
        )
        meta = {
            "status": status,
            "objective": solution.ObjectiveValue() / DIST_SCALE,
            "model_nodes": n_model,
            "station_copies": cfg.station_copies,
            "charge_plans": charge_plans,
            "charge_policy": "explicit",
            "dropped_customers": self._dropped(
                instance, manager, routing, solution, model_nodes
            ),
        }
        return routes, status, meta

    # -- extraction --------------------------------------------------------
    def _extract(self, instance, manager, routing, solution, model_nodes):
        """Read routes and the charged energy back out of the CP solution.

        The recharge at a station is the dimension's slack, but slack variables
        are not part of the returned assignment -- reading ``SlackVar`` gives a
        meaningless zero.  The reliable way to recover it is the cumul
        difference across the arc minus the arc's own transit, which is exactly
        the definition of the slack:

            slack(i) = cumul(next) - cumul(i) - transit(i, next)
        """
        soc_dim = routing.GetDimensionOrDie("Energy") if self.enforce_energy else None
        routes: list[list[int]] = []
        plans: list[dict[int, float]] = []

        for v in range(instance.fleet_size):
            index = routing.Start(v)
            route: list[int] = []
            plan: dict[int, float] = {}
            while not routing.IsEnd(index):
                node = model_nodes[manager.IndexToNode(index)]
                nxt = solution.Value(routing.NextVar(index))
                if node != 0:
                    if soc_dim is not None and instance.is_station(node):
                        transit = soc_dim.GetTransitValue(index, nxt, v)
                        charged = (
                            solution.Value(soc_dim.CumulVar(nxt))
                            - solution.Value(soc_dim.CumulVar(index))
                            - transit
                        )
                        plan[len(route)] = max(0.0, charged / ENERGY_SCALE)
                    route.append(node)
                index = nxt
            if route:
                route, plan = _prune_idle_charging_stops(instance, route, plan)
                if route:  # pruning can empty a route made only of idle stops
                    routes.append(route)
                    plans.append(plan)
        return routes, plans

    def _dropped(self, instance, manager, routing, solution, model_nodes) -> list[int]:
        dropped = []
        for model_node in range(1, instance.n_customers + 1):
            index = manager.NodeToIndex(model_node)
            if index >= 0 and solution.Value(routing.NextVar(index)) == index:
                dropped.append(model_nodes[model_node])
        return dropped
