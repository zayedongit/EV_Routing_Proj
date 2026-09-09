import json

import pytest

from evrp.config import (
    ChargingConfig,
    ConfigError,
    EnergyConfig,
    Scenario,
    SolverConfig,
    VehicleSpec,
)


def test_vehicle_reserve_maths():
    v = VehicleSpec(battery_kwh=50.0, reserve_soc=0.2)
    assert v.min_soc_kwh == pytest.approx(10.0)
    assert v.usable_kwh == pytest.approx(40.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"payload_capacity": 0},
        {"battery_kwh": -1},
        {"reserve_soc": 1.0},
        {"speed_km_per_min": 0},
        {"onboard_charge_power_kw": 0},
        {"max_route_duration": 0},
    ],
)
def test_vehicle_rejects_nonsense(kwargs):
    with pytest.raises(ConfigError):
        VehicleSpec(**kwargs).validate()


@pytest.mark.parametrize(
    "kwargs",
    [{"base_kwh_per_km": 0}, {"payload_kwh_per_km_per_kg": -1}, {"regen_efficiency": 0}],
)
def test_energy_config_rejects_nonsense(kwargs):
    with pytest.raises(ConfigError):
        EnergyConfig(**kwargs).validate()


@pytest.mark.parametrize(
    "kwargs",
    [{"curve": "quadratic"}, {"cc_end_soc": 0}, {"energy_price": -1}, {"v2g_min_soc": 2}],
)
def test_charging_config_rejects_nonsense(kwargs):
    with pytest.raises(ConfigError):
        ChargingConfig(**kwargs).validate()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"time_limit_s": 0},
        {"station_copies": -1},
        {"first_solution": "MAGIC"},
        {"metaheuristic": "MAGIC"},
        {"model_charge_power_mode": "optimistic"},
    ],
)
def test_solver_config_rejects_nonsense(kwargs):
    with pytest.raises(ConfigError):
        SolverConfig(**kwargs).validate()


def test_scenario_round_trips_through_json(tmp_path):
    scenario = Scenario(
        name="rt",
        fleet_size=7,
        vehicle=VehicleSpec(battery_kwh=33.0),
        solver=SolverConfig(time_limit_s=1.5, seed=11),
    )
    path = tmp_path / "s.json"
    scenario.to_json(path)
    assert Scenario.from_json(path) == scenario
    assert json.loads(path.read_text())["vehicle"]["battery_kwh"] == 33.0


def test_scenario_rejects_unknown_keys():
    with pytest.raises(ConfigError):
        Scenario.from_dict({"name": "x", "nonsense": 1})


def test_scenario_with_overrides_is_a_copy():
    a = Scenario(name="a")
    b = a.with_overrides(fleet_size=99)
    assert a.fleet_size != 99 and b.fleet_size == 99


def test_peak_window_bounds_must_be_consistent():
    with pytest.raises(ConfigError):
        Scenario(peak_start_min=100.0).validate()          # end missing
    with pytest.raises(ConfigError):
        Scenario(peak_end_min=100.0).validate()            # start missing
    with pytest.raises(ConfigError):
        Scenario(peak_start_min=200.0, peak_end_min=100.0).validate()
    Scenario(peak_start_min=100.0, peak_end_min=200.0).validate()


def test_peak_window_survives_a_json_round_trip(tmp_path):
    scenario = Scenario(name="peak", peak_start_min=600.0, peak_end_min=900.0)
    path = tmp_path / "s.json"
    scenario.to_json(path)
    assert Scenario.from_json(path) == scenario
