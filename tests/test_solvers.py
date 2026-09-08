"""Solver behaviour, checked against the independent simulator.

Every assertion about "the solver found a good route" also asserts that the
route survives :mod:`evrp.feasibility`.  A solver that games its own objective
-- the failure mode the previous genetic-algorithm implementation had, where
serving nobody scored a perfect zero -- fails these tests.
"""

from __future__ import annotations

import pytest

from evrp.config import ChargingConfig, EnergyConfig, SolverConfig, VehicleSpec
from evrp.instance import ChargingStation, Instance, Node, NodeKind
from evrp.solvers import available, create
from evrp.solvers.base import SolverError
from evrp.solvers.heuristic import repair_with_charging, _RouteEvaluator

ALL_SOLVERS = ["ortools", "savings", "insertion", "insertion-ls"]
FLAT = EnergyConfig(base_kwh_per_km=0.1, payload_kwh_per_km_per_kg=0.0)
LINEAR = ChargingConfig(curve="linear", fixed_time_min=0.0)


def make(name, time_limit=3.0, **kw):
    kw.setdefault("station_copies", 1)
    return create(
        name,
        solver_config=SolverConfig(time_limit_s=time_limit, seed=7, **kw),
        energy_config=FLAT,
        charging_config=LINEAR,
    )


def test_registry_lists_every_solver():
    assert set(ALL_SOLVERS) <= set(available())


def test_unknown_solver_is_rejected():
    with pytest.raises(SolverError):
        create("teleporter")


@pytest.mark.parametrize("name", ALL_SOLVERS)
def test_solver_serves_every_customer_feasibly(name, tiny):
    solution = make(name).solve(tiny)
    assert solution.metrics.customers_served == 3
    assert solution.feasible, [str(v) for v in solution.violations]
    assert solution.unserved(tiny) == []


@pytest.mark.parametrize("name", ALL_SOLVERS)
def test_solution_metrics_match_a_fresh_simulation(name, tiny):
    from evrp.feasibility import simulate_route

    solution = make(name).solve(tiny)
    recomputed = sum(
        simulate_route(tiny, r, energy_config=FLAT, charging_config=LINEAR).distance
        for r in solution.routes
    )
    assert recomputed == pytest.approx(solution.metrics.total_distance)


@pytest.mark.parametrize("name", ALL_SOLVERS)
def test_no_route_visits_a_customer_twice(name, tiny):
    solution = make(name).solve(tiny)
    visited = [n for r in solution.routes for n in r if not tiny.is_station(n)]
    assert len(visited) == len(set(visited))


def test_solver_uses_a_charger_when_the_pack_is_too_small(vehicle):
    """The point of the whole exercise: a route that only exists via a charger."""
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=90, y=0, demand=1, due_time=100000)]
    stations = [ChargingStation(id=0, x=50, y=0, power_kw=200.0, due_time=100000)]
    inst = Instance.build("needs-charge", depot, customers, stations,
                          vehicle=vehicle, fleet_size=1)
    solution = make("ortools", time_limit=5.0, station_copies=3).solve(inst)
    assert solution.feasible
    assert solution.metrics.charging_stops >= 1
    assert solution.metrics.customers_served == 1


def test_time_windows_force_more_vehicles(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=1000, kind=NodeKind.DEPOT)
    far_apart = [
        Node(id=1, x=10, y=0, demand=1, ready_time=0, due_time=15, service_time=1),
        Node(id=2, x=-10, y=0, demand=1, ready_time=0, due_time=15, service_time=1),
    ]
    inst = Instance.build("tw", depot, far_apart, vehicle=vehicle, fleet_size=2)
    solution = make("ortools").solve(inst)
    assert solution.feasible
    assert solution.metrics.vehicles_used == 2


def test_capacity_forces_more_vehicles():
    v = VehicleSpec(payload_capacity=10.0, battery_kwh=100.0, reserve_soc=0.0)
    depot = Node(id=0, x=0, y=0, due_time=10000, kind=NodeKind.DEPOT)
    customers = [Node(id=i, x=5 * i, y=0, demand=8, due_time=10000) for i in (1, 2, 3)]
    inst = Instance.build("cap", depot, customers, vehicle=v, fleet_size=3)
    solution = make("ortools").solve(inst)
    assert solution.feasible
    assert solution.metrics.vehicles_used == 3


def test_dropping_is_reported_rather_than_hidden(vehicle):
    """An unreachable customer produces an explicit drop, not a silent success."""
    depot = Node(id=0, x=0, y=0, due_time=1000, kind=NodeKind.DEPOT)
    customers = [
        Node(id=1, x=10, y=0, demand=1, due_time=1000),
        Node(id=2, x=400, y=0, demand=1, due_time=5),  # cannot be reached in time
    ]
    inst = Instance.build("drop", depot, customers, vehicle=vehicle, fleet_size=2)
    solution = make("ortools").solve(inst)
    assert 2 in solution.unserved(inst)
    assert not solution.feasible


def test_charging_repair_inserts_a_station(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=90, y=0, demand=1, due_time=100000)]
    stations = [ChargingStation(id=0, x=50, y=0, power_kw=200.0, due_time=100000)]
    inst = Instance.build("repair", depot, customers, stations, vehicle=vehicle, fleet_size=1)
    ev = _RouteEvaluator(inst, FLAT, LINEAR)
    repaired = repair_with_charging(ev, [1])
    assert repaired is not None
    assert any(inst.is_station(n) for n in repaired)
    assert ev.feasible(repaired)


def test_charging_repair_gives_up_when_no_station_helps(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=900, y=0, demand=1, due_time=100000)]
    stations = [ChargingStation(id=0, x=5, y=0, power_kw=200.0, due_time=100000)]
    inst = Instance.build("hopeless", depot, customers, stations, vehicle=vehicle, fleet_size=1)
    ev = _RouteEvaluator(inst, FLAT, LINEAR)
    assert repair_with_charging(ev, [1]) is None


def test_local_search_does_not_worsen_the_construction(tiny):
    plain = make("insertion").solve(tiny)
    improved = make("insertion-ls").solve(tiny)
    assert improved.metrics.total_distance <= plain.metrics.total_distance + 1e-6
    assert improved.feasible


def test_ortools_is_deterministic_for_a_fixed_seed(tiny):
    a = make("ortools", time_limit=2.0).solve(tiny)
    b = make("ortools", time_limit=2.0).solve(tiny)
    assert a.routes == b.routes


def test_vehicle_fixed_cost_reduces_the_fleet(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=10000, kind=NodeKind.DEPOT)
    customers = [Node(id=i, x=3 * i, y=0, demand=1, due_time=10000) for i in (1, 2, 3, 4)]
    inst = Instance.build("fleet", depot, customers, vehicle=vehicle, fleet_size=4)
    free = make("ortools").solve(inst)
    charged = make("ortools", vehicle_fixed_cost=500.0).solve(inst)
    assert charged.metrics.vehicles_used <= free.metrics.vehicles_used
    assert charged.feasible


@pytest.mark.slow
def test_ortools_matches_the_published_c101_optimum():
    """C101's published optimum is 828.94 km with 10 vehicles.

    Reproducing it end to end is the strongest available check that the
    distance, capacity and time-window parts of the model are set up
    correctly -- including the Solomon convention that travel time equals
    Euclidean distance, which the original code got wrong by dividing by a
    50 km/h speed.
    """
    from evrp.config import Scenario
    from evrp.instance import instance_from_scenario

    scenario = Scenario(
        name="c101-optimum",
        instance_file="data/C101.csv",
        fleet_size=25,
        n_stations=6,
        vehicle=VehicleSpec(payload_capacity=200, battery_kwh=40.0),
        solver=SolverConfig(time_limit_s=25.0, seed=42, station_copies=2),
    )
    instance = instance_from_scenario(scenario)
    solver = create(
        "ortools",
        solver_config=scenario.solver,
        energy_config=scenario.energy,
        charging_config=scenario.charging,
    )
    solution = solver.solve(instance)
    assert solution.feasible
    assert solution.metrics.customers_served == 100
    assert solution.metrics.vehicles_used == 10
    assert solution.metrics.total_distance == pytest.approx(828.94, abs=1.0)


def _corridor_instance(battery=10.0, station_power=20.0, horizon=100000):
    """One customer far enough away that a charging stop is mandatory."""
    v = VehicleSpec(payload_capacity=100.0, battery_kwh=battery, reserve_soc=0.0,
                    speed_km_per_min=1.0, onboard_charge_power_kw=station_power)
    depot = Node(id=0, x=0, y=0, due_time=horizon, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=90, y=0, demand=1, due_time=horizon)]
    stations = [ChargingStation(id=0, x=50, y=0, power_kw=station_power, due_time=horizon)]
    return Instance.build("corridor", depot, customers, stations, vehicle=v, fleet_size=1)


def test_charging_time_is_actually_charged_for():
    """Regression: the energy/time link had a 3600x unit error.

    With it, recharging was free in wall-clock terms and the CP model happily
    dumped 28 kWh into a pack in under four minutes, which the simulator then
    rejected as a pile of late deliveries.  The check here is that the schedule
    the model returns leaves room for the recharge it prescribes.
    """
    instance = _corridor_instance(battery=10.0, station_power=20.0)
    solution = make("ortools", time_limit=6.0, station_copies=3).solve(instance)
    assert solution.feasible, [str(v) for v in solution.violations]
    sim = solution.simulations[0]
    assert sim.charge_time > 0
    # 8 kWh has to be bought; at a 20 kW charger tapering to 9 kW that cannot
    # possibly take less than 8/20*60 = 24 minutes.
    assert sim.energy_charged >= 7.9
    assert sim.charge_time >= 24.0


def test_charging_stop_pushes_the_route_past_a_tight_horizon():
    """If the depot closes before the recharge can finish, there is no plan."""
    # 180 km of driving is 180 minutes; 8 kWh at 20 kW adds at least 24 more.
    instance = _corridor_instance(battery=10.0, station_power=20.0, horizon=195)
    solution = make("ortools", time_limit=6.0, station_copies=3).solve(instance)
    assert not solution.feasible
    assert solution.metrics.customers_served == 0


@pytest.mark.parametrize("mode", ["worst", "average", "empty"])
def test_consumption_bound_modes_all_run(mode):
    instance = _corridor_instance(battery=12.0, station_power=50.0)
    solution = make("ortools", time_limit=5.0, station_copies=3,
                    model_consumption_mode=mode).solve(instance)
    assert solution.metrics.customers_served == 1


def test_worst_case_consumption_bound_is_verification_safe(solomon_path):
    """The default bound must never produce a route the simulator rejects."""
    from evrp.config import Scenario
    from evrp.instance import instance_from_scenario

    scenario = Scenario(
        name="safe",
        instance_file=str(solomon_path),
        fleet_size=25,
        n_stations=6,
        vehicle=VehicleSpec(payload_capacity=200, battery_kwh=22.0),
        solver=SolverConfig(time_limit_s=10.0, seed=3, station_copies=2),
    )
    instance = instance_from_scenario(scenario)
    solution = create(
        "ortools",
        solver_config=scenario.solver,
        energy_config=scenario.energy,
        charging_config=scenario.charging,
    ).solve(instance)
    # Customers may be dropped when the bound is too tight, but nothing that is
    # served may violate a constraint.
    assert solution.metrics.n_violations == 0, [str(v) for v in solution.violations]
