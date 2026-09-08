import pytest

from evrp.config import ChargingConfig, EnergyConfig, VehicleSpec
from evrp.energy import ChargingCurve, EnergyModel


def test_consumption_is_linear_in_distance(energy_config, vehicle):
    m = EnergyModel(energy_config, vehicle)
    assert m.consumption(10.0) == pytest.approx(1.0)
    assert m.consumption(20.0) == pytest.approx(2.0)


def test_payload_raises_consumption():
    cfg = EnergyConfig(base_kwh_per_km=0.2, payload_kwh_per_km_per_kg=0.001)
    m = EnergyModel(cfg, VehicleSpec())
    assert m.rate_kwh_per_km(0) == pytest.approx(0.2)
    assert m.rate_kwh_per_km(100) == pytest.approx(0.3)
    assert m.consumption(10, 100) > m.consumption(10, 0)


def test_range_accounts_for_the_reserve():
    v = VehicleSpec(battery_kwh=50.0, reserve_soc=0.2)
    m = EnergyModel(EnergyConfig(base_kwh_per_km=0.2, payload_kwh_per_km_per_kg=0.0), v)
    assert m.full_range_km == pytest.approx(200.0)  # 40 usable kWh / 0.2
    assert m.range_km(25.0) == pytest.approx(75.0)  # only 15 kWh above reserve
    assert m.range_km(5.0) == 0.0                   # already below reserve


def test_negative_inputs_are_rejected(energy_config, vehicle):
    m = EnergyModel(energy_config, vehicle)
    with pytest.raises(ValueError):
        m.consumption(-1.0)
    with pytest.raises(ValueError):
        m.rate_kwh_per_km(-5.0)


def test_linear_curve_is_energy_over_power():
    v = VehicleSpec(battery_kwh=60.0, onboard_charge_power_kw=1000.0)
    curve = ChargingCurve(60.0, v, ChargingConfig(curve="linear", fixed_time_min=0.0))
    assert curve.time_for(0.0, 60.0) == pytest.approx(60.0)  # 60 kWh at 60 kW = 1 h
    assert curve.time_for(30.0, 60.0) == pytest.approx(30.0)


def test_onboard_charger_caps_station_power():
    v = VehicleSpec(battery_kwh=60.0, onboard_charge_power_kw=11.0)
    curve = ChargingCurve(150.0, v, ChargingConfig(curve="linear", fixed_time_min=0.0))
    assert curve.power_kw == 11.0


def test_piecewise_curve_tapers_after_the_knee():
    v = VehicleSpec(battery_kwh=100.0, onboard_charge_power_kw=1000.0)
    cfg = ChargingConfig(curve="piecewise", cc_end_soc=0.8,
                         taper_power_fraction=0.5, fixed_time_min=0.0)
    curve = ChargingCurve(100.0, v, cfg)
    first_80 = curve.time_for(0.0, 80.0)
    last_20 = curve.time_for(80.0, 100.0)
    assert first_80 == pytest.approx(48.0)   # 80 kWh at 100 kW
    assert last_20 == pytest.approx(24.0)    # 20 kWh at 50 kW
    # The last fifth of the pack costs half as long as the first four fifths:
    # this is exactly the effect a linear charging model misses.
    assert last_20 / 20.0 > first_80 / 80.0


def test_fixed_plug_in_overhead_is_added_once():
    v = VehicleSpec(battery_kwh=60.0, onboard_charge_power_kw=1000.0)
    curve = ChargingCurve(60.0, v, ChargingConfig(curve="linear", fixed_time_min=3.0))
    assert curve.time_for(0.0, 60.0) == pytest.approx(63.0)


def test_energy_after_inverts_time_for():
    v = VehicleSpec(battery_kwh=80.0, onboard_charge_power_kw=1000.0)
    curve = ChargingCurve(50.0, v, ChargingConfig(curve="piecewise", fixed_time_min=1.5))
    for start, target in ((0.0, 30.0), (10.0, 70.0), (55.0, 80.0)):
        minutes = curve.time_for(start, target)
        assert curve.energy_after(start, minutes) == pytest.approx(target, abs=1e-6)


def test_energy_after_never_exceeds_the_pack():
    v = VehicleSpec(battery_kwh=40.0, onboard_charge_power_kw=1000.0)
    curve = ChargingCurve(150.0, v, ChargingConfig())
    assert curve.energy_after(10.0, 10_000.0) == pytest.approx(40.0)


def test_curve_rejects_impossible_requests():
    v = VehicleSpec(battery_kwh=40.0)
    curve = ChargingCurve(50.0, v, ChargingConfig())
    with pytest.raises(ValueError):
        curve.time_for(20.0, 10.0)
    with pytest.raises(ValueError):
        curve.time_for(0.0, 100.0)
    with pytest.raises(ValueError):
        ChargingCurve(0.0, v, ChargingConfig())


def test_segments_describe_the_remaining_curve():
    v = VehicleSpec(battery_kwh=100.0, onboard_charge_power_kw=1000.0)
    curve = ChargingCurve(100.0, v, ChargingConfig(curve="piecewise", cc_end_soc=0.8,
                                                   taper_power_fraction=0.5))
    segments = curve.segments(0.0)
    assert segments == [(80.0, 100.0), (20.0, 50.0)]
    assert curve.segments(90.0) == [(10.0, 50.0)]
