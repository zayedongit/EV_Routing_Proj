"""Shared fixtures.

The tiny instance is deliberately hand-computable: distances are Pythagorean
triples where possible, so assertions in the tests can quote exact numbers
instead of whatever the code happens to produce.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evrp.config import ChargingConfig, EnergyConfig, SolverConfig, VehicleSpec
from evrp.instance import ChargingStation, Instance, Node, NodeKind

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def vehicle() -> VehicleSpec:
    return VehicleSpec(
        payload_capacity=100.0,
        battery_kwh=10.0,
        reserve_soc=0.0,
        speed_km_per_min=1.0,
        onboard_charge_power_kw=100.0,
    )


@pytest.fixture
def energy_config() -> EnergyConfig:
    # 0.1 kWh/km flat: 10 kWh of pack == exactly 100 km of range.
    return EnergyConfig(base_kwh_per_km=0.1, payload_kwh_per_km_per_kg=0.0)


@pytest.fixture
def charging_config() -> ChargingConfig:
    return ChargingConfig(curve="linear", fixed_time_min=0.0)


@pytest.fixture
def tiny(vehicle) -> Instance:
    """Depot at the origin, three customers on a 30 km line, wide windows."""
    depot = Node(id=0, x=0, y=0, ready_time=0, due_time=1000, kind=NodeKind.DEPOT)
    customers = [
        Node(id=1, x=10, y=0, demand=10, ready_time=0, due_time=1000, service_time=5),
        Node(id=2, x=20, y=0, demand=10, ready_time=0, due_time=1000, service_time=5),
        Node(id=3, x=30, y=0, demand=10, ready_time=0, due_time=1000, service_time=5),
    ]
    return Instance.build("tiny", depot, customers, vehicle=vehicle, fleet_size=3)


@pytest.fixture
def tiny_with_station(vehicle) -> Instance:
    """Same line, plus a charger at the 25 km mark."""
    depot = Node(id=0, x=0, y=0, ready_time=0, due_time=1000, kind=NodeKind.DEPOT)
    customers = [
        Node(id=1, x=10, y=0, demand=10, ready_time=0, due_time=1000, service_time=5),
        Node(id=2, x=20, y=0, demand=10, ready_time=0, due_time=1000, service_time=5),
        Node(id=3, x=30, y=0, demand=10, ready_time=0, due_time=1000, service_time=5),
    ]
    stations = [ChargingStation(id=0, x=25, y=0, power_kw=100.0, due_time=1000)]
    return Instance.build("tiny-cs", depot, customers, stations, vehicle=vehicle, fleet_size=3)


@pytest.fixture
def solomon_path() -> Path:
    return DATA_DIR / "C101.csv"


@pytest.fixture
def fast_solver_config() -> SolverConfig:
    return SolverConfig(time_limit_s=3.0, seed=7, station_copies=1)
