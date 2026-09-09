"""The CLI is the reproducibility surface, so its contract is tested."""

import json

import pytest

from evrp.cli import build_parser, main


def test_parser_requires_a_subcommand():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_env_command_prints_json(capsys):
    assert main(["env"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "ortools" in payload


def test_validate_passes_on_a_workable_configuration(capsys):
    code = main(["validate", "--instance", "data/C101.csv", "--battery", "40"])
    assert code == 0
    assert "no blocking issues" in capsys.readouterr().out


def test_validate_flags_an_impossible_battery(capsys):
    code = main(["validate", "--instance", "data/C101.csv", "--battery", "6"])
    assert code == 1
    assert "out of range" in capsys.readouterr().out


def test_validate_reports_a_missing_file(capsys):
    assert main(["validate", "--instance", "data/nope.csv"]) == 2
    assert "invalid instance" in capsys.readouterr().err


def test_solve_writes_a_solution_and_a_scenario(tmp_path, capsys):
    code = main([
        "solve", "--instance", "data/C101.csv", "--solver", "savings",
        "--battery", "60", "--stations", "3", "--time-limit", "3",
        "--out", str(tmp_path), "--no-plots",
    ])
    assert code == 0
    solution = json.loads((tmp_path / "C101-savings.json").read_text())
    scenario = json.loads((tmp_path / "C101-savings-scenario.json").read_text())
    assert solution["metrics"]["customers_total"] == 100
    assert scenario["vehicle"]["battery_kwh"] == 60.0
    assert "savings on C101" in capsys.readouterr().out


@pytest.mark.slow
def test_compare_writes_a_benchmark_table(tmp_path):
    code = main([
        "compare", "--instances", "C101", "--solvers", "savings", "insertion",
        "--time-limit", "3", "--battery", "60", "--stations", "3",
        "--out", str(tmp_path), "--no-plots",
    ])
    assert code == 0
    assert (tmp_path / "benchmark.csv").exists()
    assert (tmp_path / "environment.json").exists()


def test_solve_accepts_a_scenario_file(tmp_path, capsys):
    """Scenario files are the reproducibility contract, so they must run."""
    from evrp.config import Scenario, SolverConfig, VehicleSpec

    scenario = Scenario(
        name="from-file",
        instance_file="data/C101.csv",
        fleet_size=25,
        n_stations=3,
        vehicle=VehicleSpec(payload_capacity=200, battery_kwh=60.0),
        solver=SolverConfig(time_limit_s=3.0, seed=5, station_copies=1),
    )
    path = tmp_path / "scenario.json"
    scenario.to_json(path)

    code = main([
        "solve", "--solver", "savings", "--scenario", str(path),
        "--out", str(tmp_path), "--no-plots",
    ])
    assert code == 0
    assert "Loaded scenario from-file" in capsys.readouterr().out
    assert (tmp_path / "C101-savings.json").exists()


@pytest.mark.slow
def test_bounds_experiment_records_the_safety_trade_off(tmp_path):
    """The conservative bound must never produce a rejected plan."""
    import pandas as pd

    code = main([
        "bounds", "--instances", "C101", "--modes", "worst",
        "--battery", "25", "--stations", "6", "--station-copies", "2",
        "--time-limit", "5", "--out", str(tmp_path),
    ])
    assert code == 0
    frame = pd.read_csv(tmp_path / "consumption_bounds.csv")
    worst = frame[frame["consumption_bound"] == "worst"].iloc[0]
    assert worst["violations"] == 0
