"""Parameter objects for the EV routing model.

Everything that a run depends on lives in one of these dataclasses so that a
scenario can be serialised to JSON, committed next to its results and replayed
later.  Units are stated explicitly on every field because mixing kWh with Wh
or km with "coordinate units" is the most common source of silent modelling
bugs in this problem class.

Unit convention used throughout the package
-------------------------------------------
distance   km          (Solomon coordinate units are read as km)
time       minutes     (Solomon time units are read as minutes)
speed      km/min      (Solomon convention is 1.0 km/min == 60 km/h, which is
                        what makes ``travel_time == distance`` hold)
energy     kWh
power      kW
mass       kg
money      currency units (interpreted as $ in reports)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping


class ConfigError(ValueError):
    """Raised when a configuration object is internally inconsistent."""


#: Search strategies accepted by :class:`SolverConfig`.  Kept here (rather than
#: imported from OR-Tools) so that configuration can be validated without
#: pulling in the solver backend.
FIRST_SOLUTION_NAMES = frozenset(
    {
        "PATH_CHEAPEST_ARC",
        "PARALLEL_CHEAPEST_INSERTION",
        "SAVINGS",
        "CHRISTOFIDES",
        "AUTOMATIC",
    }
)

METAHEURISTIC_NAMES = frozenset(
    {
        "GUIDED_LOCAL_SEARCH",
        "SIMULATED_ANNEALING",
        "TABU_SEARCH",
        "GREEDY_DESCENT",
        "AUTOMATIC",
    }
)


@dataclass(frozen=True)
class VehicleSpec:
    """Physical description of one electric delivery vehicle.

    ``battery_kwh`` is the *usable* pack energy.  ``reserve_soc`` is the
    fraction of the pack that routing is not allowed to consume; real fleets
    keep a buffer because arriving at 0 kWh is a breakdown, not a solution.
    """

    payload_capacity: float = 200.0        # kg (Solomon "capacity" units)
    battery_kwh: float = 40.0              # usable kWh
    reserve_soc: float = 0.10              # fraction of battery kept in hand
    speed_km_per_min: float = 1.0          # 1.0 == Solomon convention (60 km/h)
    onboard_charge_power_kw: float = 50.0  # DC charge limit of the vehicle
    max_route_duration: float | None = None  # minutes; None -> depot horizon

    @property
    def min_soc_kwh(self) -> float:
        return self.battery_kwh * self.reserve_soc

    @property
    def usable_kwh(self) -> float:
        """Energy available for driving between two full charges."""
        return self.battery_kwh - self.min_soc_kwh

    def validate(self) -> None:
        if self.payload_capacity <= 0:
            raise ConfigError("payload_capacity must be > 0")
        if self.battery_kwh <= 0:
            raise ConfigError("battery_kwh must be > 0")
        if not 0.0 <= self.reserve_soc < 1.0:
            raise ConfigError("reserve_soc must be in [0, 1)")
        if self.speed_km_per_min <= 0:
            raise ConfigError("speed_km_per_min must be > 0")
        if self.onboard_charge_power_kw <= 0:
            raise ConfigError("onboard_charge_power_kw must be > 0")
        if self.max_route_duration is not None and self.max_route_duration <= 0:
            raise ConfigError("max_route_duration must be > 0 when set")


@dataclass(frozen=True)
class EnergyConfig:
    """Load-dependent linear consumption model.

    ``E(d, m) = (base + slope * m) * d``  with *m* the payload still on board.

    A linear dependence on carried mass is the standard first-order model for
    road vehicles: rolling resistance and the inertial component of the drive
    cycle both scale with mass.  Keeping it linear is what allows the same
    model to be embedded in the OR-Tools dimension and in the schedule LP.
    """

    base_kwh_per_km: float = 0.22
    # A 1000 kg payload adds 0.08 kWh/km, about 36 % on top of the empty rate.
    # That is the right order for a light commercial vehicle; an earlier value
    # of 0.00025 more than doubled consumption at full load, which made the
    # worst-case bound used by the CP model far too pessimistic to route with.
    payload_kwh_per_km_per_kg: float = 0.00008
    regen_efficiency: float = 1.0  # multiplier applied to consumption (<1 = regen credit)

    def validate(self) -> None:
        if self.base_kwh_per_km <= 0:
            raise ConfigError("base_kwh_per_km must be > 0")
        if self.payload_kwh_per_km_per_kg < 0:
            raise ConfigError("payload_kwh_per_km_per_kg must be >= 0")
        if not 0 < self.regen_efficiency <= 1.5:
            raise ConfigError("regen_efficiency must be in (0, 1.5]")


@dataclass(frozen=True)
class ChargingConfig:
    """Charging-station behaviour and tariffs.

    ``curve`` selects the charging model:

    ``"linear"``    constant power; charge time = energy / power.
    ``"piecewise"`` three-segment concave approximation of a CC-CV curve, i.e.
                    full power up to ``cc_end_soc`` then tapering.  This is the
                    standard piecewise-linear approximation used in the
                    E-VRPTW-with-partial-recharge literature.
    """

    curve: str = "piecewise"
    cc_end_soc: float = 0.80          # end of the constant-current phase
    taper_power_fraction: float = 0.45  # average power in the taper, as a fraction
    fixed_time_min: float = 2.0       # plug-in / handshake overhead per stop
    energy_price: float = 0.18        # $/kWh paid when charging
    v2g_price: float = 0.55           # $/kWh earned when discharging to grid
    v2g_enabled: bool = False
    v2g_min_soc: float = 0.35         # never discharge below this fraction
    distance_cost_per_km: float = 0.25  # marginal $/km, used to price V2G detours

    def validate(self) -> None:
        if self.curve not in ("linear", "piecewise"):
            raise ConfigError("curve must be 'linear' or 'piecewise'")
        if not 0 < self.cc_end_soc <= 1.0:
            raise ConfigError("cc_end_soc must be in (0, 1]")
        if not 0 < self.taper_power_fraction <= 1.0:
            raise ConfigError("taper_power_fraction must be in (0, 1]")
        if self.fixed_time_min < 0:
            raise ConfigError("fixed_time_min must be >= 0")
        if self.energy_price < 0 or self.v2g_price < 0:
            raise ConfigError("prices must be >= 0")
        if not 0 <= self.v2g_min_soc <= 1:
            raise ConfigError("v2g_min_soc must be in [0, 1]")
        if self.distance_cost_per_km < 0:
            raise ConfigError("distance_cost_per_km must be >= 0")


@dataclass(frozen=True)
class SolverConfig:
    """Search-effort knobs shared by every solver."""

    time_limit_s: float = 30.0
    seed: int = 42
    first_solution: str = "PATH_CHEAPEST_ARC"
    metaheuristic: str = "GUIDED_LOCAL_SEARCH"
    station_copies: int = 2      # replicas per charging station in the MIP-style model
    model_charge_power_mode: str = "conservative"  # "conservative" | "nominal"
    model_consumption_mode: str = "worst"  # "worst" | "average" | "empty"
    charge_stop_minutes: float = 30.0  # length of one charging session
    vehicle_fixed_cost: float = 0.0  # cost charged for using a vehicle at all
    log_search: bool = False

    def validate(self) -> None:
        if self.time_limit_s <= 0:
            raise ConfigError("time_limit_s must be > 0")
        if self.station_copies < 0:
            raise ConfigError("station_copies must be >= 0")
        if self.vehicle_fixed_cost < 0:
            raise ConfigError("vehicle_fixed_cost must be >= 0")
        if self.model_charge_power_mode not in ("conservative", "nominal"):
            raise ConfigError(
                "model_charge_power_mode must be 'conservative' or 'nominal'"
            )
        if self.model_consumption_mode not in ("worst", "average", "empty"):
            raise ConfigError(
                "model_consumption_mode must be 'worst', 'average' or 'empty'"
            )
        if self.charge_stop_minutes <= 0:
            raise ConfigError("charge_stop_minutes must be > 0")
        if self.first_solution not in FIRST_SOLUTION_NAMES:
            raise ConfigError(
                f"first_solution must be one of {sorted(FIRST_SOLUTION_NAMES)}"
            )
        if self.metaheuristic not in METAHEURISTIC_NAMES:
            raise ConfigError(
                f"metaheuristic must be one of {sorted(METAHEURISTIC_NAMES)}"
            )


@dataclass(frozen=True)
class Scenario:
    """A fully specified, reproducible experiment."""

    name: str = "default"
    instance_file: str = "data/C101.csv"
    fleet_size: int = 25
    n_stations: int = 6
    station_strategy: str = "kmeans"
    station_power_kw: float = 50.0
    # Optional time-of-use window, in minutes from the start of the day, during
    # which a charger will buy energy back.  Left unset, stations accept V2G at
    # any time; set, it becomes a hard constraint in the schedule MILP and is
    # re-checked by the route simulator.
    peak_start_min: float | None = None
    peak_end_min: float | None = None
    vehicle: VehicleSpec = field(default_factory=VehicleSpec)
    energy: EnergyConfig = field(default_factory=EnergyConfig)
    charging: ChargingConfig = field(default_factory=ChargingConfig)
    solver: SolverConfig = field(default_factory=SolverConfig)

    def validate(self) -> None:
        if not self.name:
            raise ConfigError("scenario name must be non-empty")
        if self.fleet_size <= 0:
            raise ConfigError("fleet_size must be > 0")
        if self.n_stations < 0:
            raise ConfigError("n_stations must be >= 0")
        if self.station_power_kw <= 0:
            raise ConfigError("station_power_kw must be > 0")
        if self.station_strategy not in ("kmeans", "grid", "random", "none"):
            raise ConfigError(
                "station_strategy must be one of kmeans|grid|random|none"
            )
        if (self.peak_start_min is None) != (self.peak_end_min is None):
            raise ConfigError(
                "peak_start_min and peak_end_min must be set together"
            )
        if (
            self.peak_start_min is not None
            and self.peak_end_min is not None
            and self.peak_start_min >= self.peak_end_min
        ):
            raise ConfigError("peak_start_min must be < peak_end_min")
        self.vehicle.validate()
        self.energy.validate()
        self.charging.validate()
        self.solver.validate()

    # -- serialisation ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Scenario":
        raw = dict(raw)
        nested = {
            "vehicle": VehicleSpec,
            "energy": EnergyConfig,
            "charging": ChargingConfig,
            "solver": SolverConfig,
        }
        kwargs: dict[str, Any] = {}
        for key, klass in nested.items():
            kwargs[key] = klass(**raw.pop(key)) if key in raw else klass()
        unknown = set(raw) - {f for f in cls.__dataclass_fields__}
        if unknown:
            raise ConfigError(f"unknown scenario keys: {sorted(unknown)}")
        scenario = cls(**raw, **kwargs)
        scenario.validate()
        return scenario

    @classmethod
    def from_json(cls, path: str | Path) -> "Scenario":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"scenario file not found: {p}")
        return cls.from_dict(json.loads(p.read_text()))

    def with_overrides(self, **kwargs: Any) -> "Scenario":
        """Return a copy with top-level fields replaced (keeps immutability)."""
        return replace(self, **kwargs)
