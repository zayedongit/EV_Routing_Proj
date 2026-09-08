import pytest

from evrp.config import ChargingConfig, EnergyConfig, VehicleSpec
from evrp.instance import ChargingStation, Instance, Node, NodeKind
from evrp.schedule import optimise_schedule

FLAT = EnergyConfig(base_kwh_per_km=0.1, payload_kwh_per_km_per_kg=0.0)
LINEAR = ChargingConfig(curve="linear", fixed_time_min=0.0, energy_price=0.20,
                        v2g_price=0.60, v2g_min_soc=0.0)


@pytest.fixture
def corridor():
    """Depot, a charger at 50 km, a customer at 90 km. 100 km of range."""
    v = VehicleSpec(payload_capacity=100, battery_kwh=10.0, reserve_soc=0.0,
                    onboard_charge_power_kw=100.0)
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=90, y=0, demand=1, due_time=100000, service_time=0)]
    stations = [ChargingStation(id=0, x=50, y=0, power_kw=100.0, due_time=100000)]
    return Instance.build("corridor", depot, customers, stations, vehicle=v, fleet_size=1)


def test_empty_route_is_trivial(corridor):
    result = optimise_schedule(corridor, [], FLAT, LINEAR)
    assert result.feasible and result.total_charged == 0.0


def test_schedule_finds_the_minimum_energy_purchase(corridor):
    station = corridor.station_indices[0]
    result = optimise_schedule(corridor, [station, 1, station], FLAT, LINEAR)
    assert result.feasible and result.status == "optimal"
    # 180 km costs 18 kWh; the pack starts with 10, so exactly 8 must be bought.
    assert result.total_charged == pytest.approx(8.0, abs=1e-6)
    assert result.energy_cost == pytest.approx(8.0 * 0.20, abs=1e-6)


def test_schedule_reports_infeasible_sequences(corridor):
    # No charging stop: 180 km on a 100 km pack cannot be scheduled at all.
    assert not optimise_schedule(corridor, [1], FLAT, LINEAR).feasible


def test_schedule_respects_time_windows():
    v = VehicleSpec(payload_capacity=100, battery_kwh=100.0, reserve_soc=0.0)
    depot = Node(id=0, x=0, y=0, due_time=1000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=10, y=0, demand=1, ready_time=0, due_time=5)]
    inst = Instance.build("tw", depot, customers, vehicle=v, fleet_size=1)
    assert not optimise_schedule(inst, [1], FLAT, LINEAR).feasible


def test_schedule_waits_for_a_late_window():
    v = VehicleSpec(payload_capacity=100, battery_kwh=100.0, reserve_soc=0.0)
    depot = Node(id=0, x=0, y=0, due_time=1000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=10, y=0, demand=1, ready_time=200, due_time=300)]
    inst = Instance.build("wait", depot, customers, vehicle=v, fleet_size=1)
    result = optimise_schedule(inst, [1], FLAT, LINEAR)
    assert result.feasible
    assert result.service_start[1] >= 200.0


def test_v2g_sells_surplus_energy(corridor):
    station = corridor.station_indices[0]
    off = optimise_schedule(corridor, [station, 1, station], FLAT, LINEAR)
    on = optimise_schedule(
        corridor, [station, 1, station],
        FLAT, ChargingConfig(**{**LINEAR.__dict__, "v2g_enabled": True}),
    )
    assert on.feasible
    assert on.net_revenue >= off.net_revenue - 1e-6


def test_v2g_never_makes_a_feasible_route_infeasible(corridor):
    """Enabling an option must only add choices, never remove them."""
    station = corridor.station_indices[0]
    route = [station, 1, station]
    assert optimise_schedule(corridor, route, FLAT, LINEAR).feasible
    v2g = ChargingConfig(**{**LINEAR.__dict__, "v2g_enabled": True, "v2g_min_soc": 0.9})
    assert optimise_schedule(corridor, route, FLAT, v2g).feasible


def test_v2g_floor_caps_what_can_be_sold():
    v = VehicleSpec(payload_capacity=100, battery_kwh=20.0, reserve_soc=0.0,
                    onboard_charge_power_kw=100.0)
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=10, y=0, demand=1, due_time=100000)]
    stations = [ChargingStation(id=0, x=5, y=0, power_kw=100.0, due_time=100000)]
    inst = Instance.build("v2g", depot, customers, stations, vehicle=v, fleet_size=1)
    station = inst.station_indices[0]

    generous = ChargingConfig(**{**LINEAR.__dict__, "v2g_enabled": True, "v2g_min_soc": 0.1})
    strict = ChargingConfig(**{**LINEAR.__dict__, "v2g_enabled": True, "v2g_min_soc": 0.9})
    a = optimise_schedule(inst, [station, 1], FLAT, generous)
    b = optimise_schedule(inst, [station, 1], FLAT, strict)
    assert a.feasible and b.feasible
    assert a.total_discharged >= b.total_discharged


def test_a_stop_cannot_both_buy_and_sell():
    """Round-tripping energy at one plug would be free money; the model forbids it."""
    v = VehicleSpec(payload_capacity=100, battery_kwh=20.0, reserve_soc=0.0,
                    onboard_charge_power_kw=100.0)
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=10, y=0, demand=1, due_time=100000)]
    stations = [ChargingStation(id=0, x=5, y=0, power_kw=100.0, due_time=100000)]
    inst = Instance.build("arb", depot, customers, stations, vehicle=v, fleet_size=1)
    station = inst.station_indices[0]
    cfg = ChargingConfig(**{**LINEAR.__dict__, "v2g_enabled": True,
                            "energy_price": 0.10, "v2g_price": 5.0, "v2g_min_soc": 0.0})
    result = optimise_schedule(inst, [station, 1], FLAT, cfg)
    assert result.feasible
    for pos in result.charge_kwh:
        assert result.discharge_kwh.get(pos, 0.0) == pytest.approx(0.0)


def test_charging_consumes_time(corridor):
    station = corridor.station_indices[0]
    result = optimise_schedule(corridor, [station, 1, station], FLAT, LINEAR)
    # 8 kWh at 100 kW is 4.8 minutes on top of 180 minutes of driving.
    assert result.finish_time > 180.0
    assert result.finish_time == pytest.approx(184.8, abs=0.5)
