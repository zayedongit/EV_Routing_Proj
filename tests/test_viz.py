"""Figures are smoke-tested: they must build headless without raising."""

import matplotlib
import pandas as pd
import pytest

matplotlib.use("Agg")

from evrp.config import ChargingConfig, EnergyConfig
from evrp.feasibility import simulate_route
from evrp.solution import Solution
from evrp.viz import (
    plot_battery_sensitivity,
    plot_fleet_soc,
    plot_soc_profile,
    plot_solution,
    plot_solver_comparison,
)

FLAT = EnergyConfig(base_kwh_per_km=0.1, payload_kwh_per_km_per_kg=0.0)
LINEAR = ChargingConfig(curve="linear", fixed_time_min=0.0)


@pytest.fixture
def solved(tiny_with_station):
    station = tiny_with_station.station_indices[0]
    sol = Solution(instance_name="t", solver="manual", routes=[[1, 2], [station, 3]])
    sol.evaluate(tiny_with_station, FLAT, LINEAR, charge_policy="full")
    return tiny_with_station, sol


def test_route_map_builds(solved, tmp_path):
    inst, sol = solved
    fig = plot_solution(inst, sol)
    path = tmp_path / "routes.png"
    fig.savefig(path)
    assert path.stat().st_size > 0


def test_fleet_soc_builds(solved):
    inst, sol = solved
    assert plot_fleet_soc(inst, sol) is not None


def test_single_soc_profile_builds(tiny_with_station):
    sim = simulate_route(tiny_with_station, [1, 2, 3],
                         energy_config=FLAT, charging_config=LINEAR)
    assert plot_soc_profile(tiny_with_station, sim) is not None


def test_solver_comparison_builds():
    frame = pd.DataFrame(
        [
            {"instance": "C101", "solver": "ortools", "distance_km": 830.0},
            {"instance": "C101", "solver": "savings", "distance_km": 1010.0},
            {"instance": "R101", "solver": "ortools", "distance_km": 1650.0},
            {"instance": "R101", "solver": "savings", "distance_km": 1800.0},
        ]
    )
    assert plot_solver_comparison(frame) is not None


def test_battery_sensitivity_builds():
    frame = pd.DataFrame(
        [
            {"instance": "C101", "battery_kwh": b, "distance_km": 800 + b,
             "charging_stops": max(0, 40 - b), "feasible": True}
            for b in (14, 25, 40, 80)
        ]
    )
    assert plot_battery_sensitivity(frame) is not None


def test_empty_frames_are_rejected():
    with pytest.raises(ValueError):
        plot_solver_comparison(pd.DataFrame())
    with pytest.raises(ValueError):
        plot_battery_sensitivity(pd.DataFrame())
