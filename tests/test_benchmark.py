import pandas as pd
import pytest

from evrp.benchmark import (
    environment_info,
    gap_table,
    make_scenarios,
    run_benchmark,
    solomon_capacity,
    summarise,
    to_markdown,
)
from evrp.config import Scenario, SolverConfig, VehicleSpec


@pytest.mark.parametrize(
    "name,expected",
    [("C101", 200), ("C201", 700), ("R101", 200), ("R201", 1000),
     ("RC101", 200), ("RC202", 1000), ("r102", 200)],
)
def test_solomon_capacities(name, expected):
    assert solomon_capacity(name) == expected


def test_unknown_family_is_an_error():
    with pytest.raises(KeyError):
        solomon_capacity("X999")


def test_make_scenarios_uses_the_family_capacity():
    scenarios = make_scenarios(["C101", "R201"], time_limit_s=1.0)
    assert scenarios[0].vehicle.payload_capacity == 200
    assert scenarios[1].vehicle.payload_capacity == 1000
    for s in scenarios:
        s.validate()


def test_environment_info_records_what_matters():
    info = environment_info()
    assert {"python", "platform", "ortools", "timestamp_utc"} <= set(info)


def test_run_benchmark_produces_one_row_per_pair(tmp_path):
    scenario = Scenario(
        name="tiny-bench",
        instance_file="data/C101.csv",
        fleet_size=25,
        n_stations=3,
        vehicle=VehicleSpec(payload_capacity=200, battery_kwh=60.0),
        solver=SolverConfig(time_limit_s=2.0, seed=1, station_copies=1),
    )
    result = run_benchmark([scenario], solvers=["savings", "insertion"], verbose=False)
    assert len(result.rows) == 2
    frame = result.to_frame()
    assert set(frame["solver"]) == {"savings", "insertion"}
    assert (frame["customers_total"] == 100).all()

    paths = result.save(tmp_path)
    assert paths["csv"].exists() and paths["markdown"].exists()
    assert pd.read_csv(paths["csv"]).shape[0] == 2


def test_unknown_solver_is_rejected():
    with pytest.raises(ValueError):
        run_benchmark(make_scenarios(["C101"], time_limit_s=1.0), solvers=["magic"])


def test_summarise_reports_feasibility_rate():
    frame = pd.DataFrame(
        [
            {"solver": "a", "instance": "i1", "feasible": True, "distance_km": 10.0,
             "vehicles": 2, "runtime_s": 1.0, "charging_stops": 0},
            {"solver": "a", "instance": "i2", "feasible": False, "distance_km": 20.0,
             "vehicles": 3, "runtime_s": 2.0, "charging_stops": 1},
        ]
    )
    out = summarise(frame)
    assert out.loc[0, "runs"] == 2
    assert out.loc[0, "feasible_rate"] == pytest.approx(0.5)


def test_gap_table_only_compares_feasible_rows():
    frame = pd.DataFrame(
        [
            {"instance": "i1", "solver": "ortools", "distance_km": 100.0,
             "feasible": True, "runtime_s": 1.0},
            {"instance": "i1", "solver": "savings", "distance_km": 120.0,
             "feasible": True, "runtime_s": 0.1},
            {"instance": "i1", "solver": "broken", "distance_km": 5.0,
             "feasible": False, "runtime_s": 0.1},
        ]
    )
    gaps = gap_table(frame)
    assert set(gaps["solver"]) == {"ortools", "savings"}
    row = gaps[gaps["solver"] == "savings"].iloc[0]
    assert row["gap_pct"] == pytest.approx(20.0)


def test_markdown_renders_a_table():
    frame = pd.DataFrame([{"a": 1, "b": 2.5}])
    text = to_markdown(frame)
    assert text.startswith("| a | b |")
    assert "2.50" in text


def test_markdown_handles_no_rows():
    assert "no results" in to_markdown(pd.DataFrame())
