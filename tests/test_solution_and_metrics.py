import json

import pytest

from evrp.config import ChargingConfig, EnergyConfig
from evrp.solution import Solution, SolutionMetrics

FLAT = EnergyConfig(base_kwh_per_km=0.1, payload_kwh_per_km_per_kg=0.0)
LINEAR = ChargingConfig(curve="linear", fixed_time_min=0.0)


def test_evaluate_measures_everything_from_the_simulator(tiny):
    sol = Solution(instance_name="tiny", solver="manual", routes=[[1, 2], [3]])
    sol.evaluate(tiny, FLAT, LINEAR)
    assert sol.metrics.customers_served == 3
    assert sol.metrics.vehicles_used == 2
    assert sol.metrics.total_distance == pytest.approx(40.0 + 60.0)
    assert sol.feasible


def test_empty_solution_is_not_feasible(tiny):
    sol = Solution(instance_name="tiny", solver="none").evaluate(tiny, FLAT, LINEAR)
    assert not sol.feasible
    assert sol.unserved(tiny) == [1, 2, 3]


def test_partial_solution_is_reported_as_infeasible(tiny):
    """The failure mode of the original genetic algorithm: serving nobody and
    calling it a cost of zero.  Here that is an explicit infeasibility."""
    sol = Solution(instance_name="tiny", solver="lazy", routes=[[1]])
    sol.evaluate(tiny, FLAT, LINEAR)
    assert sol.metrics.total_distance == pytest.approx(20.0)
    assert not sol.feasible
    assert sol.unserved(tiny) == [2, 3]


def test_violations_are_surfaced(tiny):
    sol = Solution(instance_name="tiny", solver="bad", routes=[[1, 2, 3, 99]])
    sol.evaluate(tiny, FLAT, LINEAR)
    assert sol.metrics.n_violations > 0
    assert not sol.feasible


def test_energy_cost_uses_the_tariff(tiny_with_station):
    station = tiny_with_station.station_indices[0]
    sol = Solution(instance_name="t", solver="m", routes=[[1, station, 3]])
    sol.evaluate(tiny_with_station, FLAT,
                 ChargingConfig(curve="linear", fixed_time_min=0.0, energy_price=0.5),
                 charge_policy="full")
    assert sol.metrics.energy_charged_kwh > 0
    assert sol.metrics.energy_cost == pytest.approx(sol.metrics.energy_charged_kwh * 0.5)


def test_to_dict_is_json_serialisable(tiny):
    sol = Solution(instance_name="tiny", solver="m", routes=[[1, 2, 3]])
    sol.evaluate(tiny, FLAT, LINEAR)
    payload = json.dumps(sol.to_dict())
    assert "\"routes\"" in payload and "\"metrics\"" in payload


def test_to_json_writes_a_file(tiny, tmp_path):
    sol = Solution(instance_name="tiny", solver="m", routes=[[1, 2, 3]])
    sol.evaluate(tiny, FLAT, LINEAR)
    path = tmp_path / "nested" / "sol.json"
    sol.to_json(path)
    assert json.loads(path.read_text())["instance"] == "tiny"


def test_metrics_net_energy_cost():
    m = SolutionMetrics(energy_cost=10.0, v2g_revenue=4.0)
    assert m.net_energy_cost == pytest.approx(6.0)


def test_a_customer_served_by_two_routes_is_reported(tiny):
    """Each route is legal on its own; only the solution as a whole is wrong."""
    sol = Solution(instance_name="tiny", solver="double", routes=[[1, 2], [2, 3]])
    sol.evaluate(tiny, FLAT, LINEAR)
    assert sol.metrics.n_violations == 0          # no single route is broken
    assert sol.metrics.duplicate_customers == 1
    assert sol.metrics.customers_served == 3
    assert not sol.feasible
    assert "more than one route" in sol.summary()


def test_a_clean_solution_reports_no_duplicates(tiny):
    sol = Solution(instance_name="tiny", solver="m", routes=[[1, 2], [3]])
    sol.evaluate(tiny, FLAT, LINEAR)
    assert sol.metrics.duplicate_customers == 0
    assert sol.feasible
