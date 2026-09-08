"""Battery, consumption and charging-curve models.

Two things make an EV routing problem different from a classic VRP:

1. **Consumption depends on what you are carrying.**  Modelled as a linear
   function of payload, which keeps it embeddable in an OR-Tools dimension
   and in a linear program.
2. **Recharging is not instantaneous and not linear.**  A real pack charges at
   full power up to roughly 80 % state of charge and then tapers.  Treating
   charging as linear underestimates the time cost of "just top it up at the
   end", which is exactly the decision the router has to get right.
"""

from __future__ import annotations

from dataclasses import dataclass

from evrp.config import ChargingConfig, EnergyConfig, VehicleSpec


@dataclass(frozen=True)
class EnergyModel:
    """Load-dependent linear consumption."""

    config: EnergyConfig
    vehicle: VehicleSpec

    def rate_kwh_per_km(self, payload_kg: float = 0.0) -> float:
        if payload_kg < 0:
            raise ValueError("payload_kg must be >= 0")
        c = self.config
        return (c.base_kwh_per_km + c.payload_kwh_per_km_per_kg * payload_kg) * c.regen_efficiency

    def consumption(self, distance_km: float, payload_kg: float = 0.0) -> float:
        """Energy in kWh needed to drive ``distance_km`` carrying ``payload_kg``."""
        if distance_km < 0:
            raise ValueError("distance_km must be >= 0")
        return self.rate_kwh_per_km(payload_kg) * distance_km

    def range_km(self, soc_kwh: float, payload_kg: float = 0.0) -> float:
        """How far the vehicle can still drive on ``soc_kwh`` before hitting reserve."""
        usable = max(0.0, soc_kwh - self.vehicle.min_soc_kwh)
        return usable / self.rate_kwh_per_km(payload_kg)

    @property
    def full_range_km(self) -> float:
        """Range from a full pack, empty vehicle -- the optimistic upper bound."""
        return self.range_km(self.vehicle.battery_kwh, 0.0)


class ChargingCurve:
    """Maps energy transferred to time spent plugged in.

    ``linear``  constant power ``P``:  t(e) = e / P.

    ``piecewise``  concave two-segment approximation of CC-CV charging.  Below
    ``cc_end_soc`` the pack accepts the full power of the slower of (station,
    on-board charger); above it, the effective power drops to
    ``taper_power_fraction * P``.  The resulting time function is convex and
    piecewise linear in the energy delivered, which is what lets the schedule
    LP represent it exactly with two segment variables.
    """

    def __init__(
        self,
        station_power_kw: float,
        vehicle: VehicleSpec,
        config: ChargingConfig,
    ) -> None:
        if station_power_kw <= 0:
            raise ValueError("station_power_kw must be > 0")
        self.config = config
        self.vehicle = vehicle
        self.power_kw = min(station_power_kw, vehicle.onboard_charge_power_kw)
        self.battery_kwh = vehicle.battery_kwh
        self.knee_kwh = (
            vehicle.battery_kwh * config.cc_end_soc
            if config.curve == "piecewise"
            else vehicle.battery_kwh
        )
        self.taper_power_kw = (
            self.power_kw * config.taper_power_fraction
            if config.curve == "piecewise"
            else self.power_kw
        )

    # -- forward: energy -> time -----------------------------------------
    def time_for(self, soc_from_kwh: float, soc_to_kwh: float) -> float:
        """Minutes needed to raise the pack from ``soc_from`` to ``soc_to``."""
        if soc_to_kwh < soc_from_kwh - 1e-9:
            raise ValueError("soc_to_kwh must be >= soc_from_kwh")
        if soc_to_kwh > self.battery_kwh + 1e-6:
            raise ValueError("soc_to_kwh exceeds battery capacity")
        lo = max(0.0, soc_from_kwh)
        hi = min(self.battery_kwh, soc_to_kwh)
        if hi <= lo:
            return 0.0

        fast = max(0.0, min(hi, self.knee_kwh) - lo)
        slow = max(0.0, hi - max(lo, self.knee_kwh))
        minutes = 60.0 * (fast / self.power_kw + slow / self.taper_power_kw)
        return minutes + self.config.fixed_time_min

    # -- inverse: time -> energy -----------------------------------------
    def energy_after(self, soc_kwh: float, minutes: float) -> float:
        """State of charge reached after plugging in for ``minutes``."""
        if minutes <= self.config.fixed_time_min:
            return min(soc_kwh, self.battery_kwh)
        budget = minutes - self.config.fixed_time_min
        soc = min(max(soc_kwh, 0.0), self.battery_kwh)

        fast_capacity = max(0.0, self.knee_kwh - soc)
        fast_time = 60.0 * fast_capacity / self.power_kw
        if budget <= fast_time:
            return soc + budget * self.power_kw / 60.0
        soc += fast_capacity
        budget -= fast_time
        return min(self.battery_kwh, soc + budget * self.taper_power_kw / 60.0)

    def marginal_power_kw(self, soc_kwh: float) -> float:
        """Instantaneous accepted power at a given state of charge."""
        return self.power_kw if soc_kwh < self.knee_kwh else self.taper_power_kw

    def segments(self, soc_from_kwh: float) -> list[tuple[float, float]]:
        """``[(energy_capacity_kwh, power_kw), ...]`` of the remaining segments.

        Used by the schedule LP, which needs the piecewise curve as a set of
        linear pieces rather than as a callable.
        """
        soc = min(max(soc_from_kwh, 0.0), self.battery_kwh)
        out: list[tuple[float, float]] = []
        fast = max(0.0, self.knee_kwh - soc)
        if fast > 0:
            out.append((fast, self.power_kw))
        slow = max(0.0, self.battery_kwh - max(soc, self.knee_kwh))
        if slow > 0:
            out.append((slow, self.taper_power_kw))
        return out
