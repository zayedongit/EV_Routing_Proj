import pytest

from evrp.config import ChargingConfig, EnergyConfig, VehicleSpec
from evrp.instance import ChargingStation, Instance, Node, NodeKind
from evrp.solution import Solution
from evrp.v2g import apply_v2g, best_v2g_detour

FLAT = EnergyConfig(base_kwh_per_km=0.1, payload_kwh_per_km_per_kg=0.0)


def cfg(**kw):
    base = dict(curve="linear", fixed_time_min=0.0, energy_price=0.10,
                v2g_price=1.0, v2g_min_soc=0.1, distance_cost_per_km=0.05)
    base.update(kw)
    return ChargingConfig(**base)


@pytest.fixture
def grid_instance():
    """Roomy pack and a charger just off the route: V2G should pay."""
    v = VehicleSpec(payload_capacity=100, battery_kwh=50.0, reserve_soc=0.0,
                    onboard_charge_power_kw=100.0)
    depot = Node(id=0, x=0, y=0, due_time=100000, kind=NodeKind.DEPOT)
    customers = [Node(id=1, x=20, y=0, demand=1, due_time=100000, service_time=1)]
    stations = [ChargingStation(id=0, x=10, y=1, power_kw=100.0, due_time=100000)]
    return Instance.build("grid", depot, customers, stations, vehicle=v, fleet_size=1)


def test_no_stations_means_no_detour(tiny):
    decision = best_v2g_detour(tiny, [1, 2], FLAT, cfg())
    assert not decision.accepted and decision.station is None


def test_empty_route_is_handled(grid_instance):
    assert not best_v2g_detour(grid_instance, [], FLAT, cfg()).accepted


def test_profitable_detour_is_taken(grid_instance):
    decision = best_v2g_detour(grid_instance, [1], FLAT, cfg())
    assert decision.accepted
    assert decision.station == grid_instance.station_indices[0]
    assert decision.discharged_kwh > 0
    assert decision.net_gain > 0
    assert decision.route.count(decision.station) == 1


def test_expensive_kilometres_kill_the_detour(grid_instance):
    decision = best_v2g_detour(grid_instance, [1], FLAT, cfg(distance_cost_per_km=1e6))
    assert not decision.accepted


def test_worthless_energy_kills_the_detour(grid_instance):
    decision = best_v2g_detour(grid_instance, [1], FLAT, cfg(v2g_price=0.0))
    assert not decision.accepted


def test_apply_v2g_keeps_every_customer(grid_instance):
    base = Solution(instance_name="grid", solver="manual", routes=[[1]])
    base.evaluate(grid_instance, FLAT, cfg())
    out, report = apply_v2g(grid_instance, base, FLAT, cfg())
    assert out.metrics.customers_served == base.metrics.customers_served
    assert out.feasible
    assert report.total_discharged_kwh > 0
    assert report.net_gain > 0


def test_report_serialises_to_plain_numbers(grid_instance):
    base = Solution(instance_name="grid", solver="manual", routes=[[1]])
    base.evaluate(grid_instance, FLAT, cfg())
    _, report = apply_v2g(grid_instance, base, FLAT, cfg())
    payload = report.to_dict()
    assert all(isinstance(v, (int, float)) for v in payload.values())


def test_v2g_never_loses_feasibility(grid_instance):
    base = Solution(instance_name="grid", solver="manual", routes=[[1]])
    base.evaluate(grid_instance, FLAT, cfg())
    assert base.feasible
    out, _ = apply_v2g(grid_instance, base, FLAT, cfg())
    assert out.feasible
