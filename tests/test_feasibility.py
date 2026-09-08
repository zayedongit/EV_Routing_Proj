import pytest

from evrp.config import ChargingConfig, EnergyConfig, VehicleSpec
from evrp.feasibility import ViolationKind, route_is_feasible, simulate_route
from evrp.instance import ChargingStation, Instance, Node, NodeKind


def sim(inst, route, **kw):
    kw.setdefault("energy_config", EnergyConfig(base_kwh_per_km=0.1,
                                                payload_kwh_per_km_per_kg=0.0))
    kw.setdefault("charging_config", ChargingConfig(curve="linear", fixed_time_min=0.0))
    return simulate_route(inst, route, **kw)


def test_empty_route_is_trivially_feasible(tiny):
    result = sim(tiny, [])
    assert result.feasible and result.distance == 0.0


def test_depot_sentinels_are_optional(tiny):
    assert sim(tiny, [1, 2]).distance == pytest.approx(sim(tiny, [0, 1, 2, 0]).distance)


def test_distance_and_time_are_the_hand_computed_values(tiny):
    result = sim(tiny, [1, 2, 3])
    assert result.distance == pytest.approx(60.0)     # 0->10->20->30->0
    assert result.drive_time == pytest.approx(60.0)   # speed is 1 km/min
    assert result.service_time == pytest.approx(15.0)
    assert result.end_time == pytest.approx(75.0)


def test_state_of_charge_decreases_by_the_energy_model(tiny):
    result = sim(tiny, [1, 2, 3])
    # 10 kWh pack, 0.1 kWh/km, 60 km round trip -> 6 kWh used.
    assert result.energy_consumed == pytest.approx(6.0)
    assert result.stops[-1].soc_arrival == pytest.approx(4.0)


def test_payload_lowers_as_deliveries_are_made(tiny):
    result = sim(tiny, [1, 2, 3])
    payloads = [s.payload_on_arrival for s in result.stops]
    assert payloads[:3] == [30.0, 20.0, 10.0]


def test_load_dependent_consumption_costs_more_energy(tiny):
    flat = sim(tiny, [1, 2, 3])
    loaded = simulate_route(
        tiny, [1, 2, 3],
        energy_config=EnergyConfig(base_kwh_per_km=0.1, payload_kwh_per_km_per_kg=0.001),
        charging_config=ChargingConfig(curve="linear", fixed_time_min=0.0),
    )
    assert loaded.energy_consumed > flat.energy_consumed


def test_capacity_violation_is_reported_with_its_magnitude(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=1000, kind=NodeKind.DEPOT)
    customers = [Node(id=i, x=10 * i, y=0, demand=60, due_time=1000) for i in (1, 2)]
    inst = Instance.build("cap", depot, customers, vehicle=vehicle, fleet_size=1)
    result = sim(inst, [1, 2])
    kinds = [v.kind for v in result.violations]
    assert ViolationKind.CAPACITY in kinds
    assert result.violations_of(ViolationKind.CAPACITY)[0].magnitude == pytest.approx(20.0)


def test_late_arrival_is_a_time_window_violation(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=1000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=100, y=0, demand=1, ready_time=0, due_time=10)]
    inst = Instance.build("tw", depot, customers, vehicle=vehicle, fleet_size=1)
    result = sim(inst, [1])
    v = result.violations_of(ViolationKind.TIME_WINDOW)
    assert v and v[0].magnitude == pytest.approx(90.0)


def test_early_arrival_waits_rather_than_failing(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=1000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=10, y=0, demand=1, ready_time=100, due_time=200)]
    inst = Instance.build("wait", depot, customers, vehicle=vehicle, fleet_size=1)
    result = sim(inst, [1])
    assert result.feasible
    assert result.wait_time == pytest.approx(90.0)
    assert result.stops[0].service_start == pytest.approx(100.0)


def test_running_out_of_charge_is_a_battery_violation(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=200, y=0, demand=1, due_time=100000)]
    inst = Instance.build("flat", depot, customers, vehicle=vehicle, fleet_size=1)
    result = sim(inst, [1])
    assert result.violations_of(ViolationKind.BATTERY)
    assert not result.feasible


def test_reserve_is_enforced_not_just_empty():
    v = VehicleSpec(payload_capacity=100, battery_kwh=10.0, reserve_soc=0.5)
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=30, y=0, demand=1, due_time=100000)]
    inst = Instance.build("reserve", depot, customers, vehicle=v, fleet_size=1)
    # 60 km costs 6 kWh; the pack has 10 kWh but may only use 5.
    assert not sim(inst, [1]).feasible


def test_returning_after_the_depot_closes_is_a_duration_violation(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=50, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=40, y=0, demand=1, due_time=1000)]
    inst = Instance.build("late", depot, customers, vehicle=vehicle, fleet_size=1)
    assert sim(inst, [1]).violations_of(ViolationKind.DURATION)


def test_shift_limit_is_enforced():
    v = VehicleSpec(payload_capacity=100, battery_kwh=100.0, max_route_duration=30.0)
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=40, y=0, demand=1, due_time=100000)]
    inst = Instance.build("shift", depot, customers, vehicle=v, fleet_size=1)
    assert sim(inst, [1]).violations_of(ViolationKind.DURATION)


def test_out_of_range_node_is_caught_early(tiny):
    result = sim(tiny, [99])
    assert result.violations_of(ViolationKind.BAD_NODE)


# -- charging behaviour ----------------------------------------------------

def test_charging_at_a_station_rescues_an_infeasible_route(vehicle):
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=90, y=0, demand=1, due_time=100000)]
    stations = [ChargingStation(id=0, x=50, y=0, power_kw=100.0, due_time=100000)]
    inst = Instance.build("cs", depot, customers, stations, vehicle=vehicle, fleet_size=1)
    station = inst.station_indices[0]
    assert not sim(inst, [1]).feasible                       # 180 km on a 100 km pack
    assert sim(inst, [station, 1, station]).feasible         # charge out and back


def test_minimal_policy_charges_less_than_full(tiny_with_station):
    minimal = sim(tiny_with_station, [1, 4, 3], charge_policy="minimal")
    full = sim(tiny_with_station, [1, 4, 3], charge_policy="full")
    assert minimal.energy_charged <= full.energy_charged
    assert minimal.charge_time <= full.charge_time


def test_none_policy_passes_through_without_charging(tiny_with_station):
    result = sim(tiny_with_station, [1, 4, 3], charge_policy="none")
    assert result.energy_charged == 0.0


def test_explicit_plan_is_obeyed(tiny_with_station):
    result = sim(tiny_with_station, [1, 4, 3], charge_policy="explicit",
                 charge_plan={1: 2.5})
    assert result.energy_charged == pytest.approx(2.5)


def test_charging_never_exceeds_the_pack(tiny_with_station):
    result = sim(tiny_with_station, [1, 4, 3], charge_policy="explicit",
                 charge_plan={1: 999.0})
    assert result.stops[1].soc_departure <= tiny_with_station.vehicle.battery_kwh + 1e-9


def test_charging_costs_time(tiny_with_station):
    without = sim(tiny_with_station, [1, 4, 3], charge_policy="none")
    with_charge = sim(tiny_with_station, [1, 4, 3], charge_policy="full")
    assert with_charge.end_time > without.end_time
    assert with_charge.charge_time > 0


def test_soc_profile_records_the_charging_jump(tiny_with_station):
    result = sim(tiny_with_station, [1, 4, 3], charge_policy="full")
    profile = result.soc_profile()
    xs = [p[0] for p in profile]
    assert len(set(xs)) < len(xs)  # a vertical segment at the charger


def test_invalid_policy_is_rejected(tiny):
    with pytest.raises(ValueError):
        simulate_route(tiny, [1], charge_policy="wishful")


def test_route_is_feasible_helper(tiny):
    assert route_is_feasible(
        tiny, [1, 2],
        energy_config=EnergyConfig(base_kwh_per_km=0.1, payload_kwh_per_km_per_kg=0.0),
    )
