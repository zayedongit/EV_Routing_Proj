"""Problem instances: nodes, charging stations and the matrices derived from them.

An :class:`Instance` is immutable once built.  Distance and travel-time
matrices are computed once with NumPy (O(n^2) vectorised) rather than in the
Python double loop the original code used, because every solver and every
feasibility check reads them many thousands of times.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from evrp.config import Scenario, VehicleSpec


class NodeKind(str, Enum):
    DEPOT = "depot"
    CUSTOMER = "customer"
    STATION = "station"


class InstanceError(ValueError):
    """Raised when instance data is missing, malformed or self-contradictory."""


@dataclass(frozen=True)
class Node:
    """A location the fleet may visit."""

    id: int
    x: float
    y: float
    demand: float = 0.0
    ready_time: float = 0.0
    due_time: float = 0.0
    service_time: float = 0.0
    kind: NodeKind = NodeKind.CUSTOMER

    def validate(self) -> None:
        if self.ready_time > self.due_time:
            raise InstanceError(
                f"node {self.id}: ready_time {self.ready_time} > due_time {self.due_time}"
            )
        if self.service_time < 0:
            raise InstanceError(f"node {self.id}: negative service_time")
        if self.demand < 0:
            raise InstanceError(f"node {self.id}: negative demand")


@dataclass(frozen=True)
class ChargingStation:
    """A roadside charger, optionally able to absorb energy back (V2G)."""

    id: int
    x: float
    y: float
    power_kw: float = 50.0
    ready_time: float = 0.0
    due_time: float = 1e9
    v2g_capable: bool = True
    peak_start: float | None = None   # minutes; V2G tariff window
    peak_end: float | None = None

    def is_peak(self, t: float) -> bool:
        if self.peak_start is None or self.peak_end is None:
            return True
        return self.peak_start <= t <= self.peak_end

    def as_node(self, node_id: int) -> Node:
        return Node(
            id=node_id,
            x=self.x,
            y=self.y,
            demand=0.0,
            ready_time=self.ready_time,
            due_time=self.due_time,
            service_time=0.0,
            kind=NodeKind.STATION,
        )


def _euclidean_matrix(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    dx = xs[:, None] - xs[None, :]
    dy = ys[:, None] - ys[None, :]
    return np.sqrt(dx * dx + dy * dy)


def _manhattan_matrix(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    return np.abs(xs[:, None] - xs[None, :]) + np.abs(ys[:, None] - ys[None, :])


def _haversine_matrix(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Great-circle distance in km for coordinates given as (lat, lon) degrees."""
    r = 6371.0088
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)
    dlat = lat_r[:, None] - lat_r[None, :]
    dlon = lon_r[:, None] - lon_r[None, :]
    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat_r)[:, None] * np.cos(lat_r)[None, :] * np.sin(dlon / 2.0) ** 2
    )
    return 2.0 * r * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


METRICS = {
    "euclidean": _euclidean_matrix,
    "manhattan": _manhattan_matrix,
    "haversine": _haversine_matrix,
}


@dataclass(frozen=True)
class Instance:
    """A complete routing problem.

    Node indexing is fixed and relied on everywhere else:

    ``0``                                depot
    ``1 .. n_customers``                 customers
    ``n_customers+1 .. n_customers+m``   charging stations

    ``routes`` produced by any solver are sequences of these indices.
    """

    name: str
    nodes: tuple[Node, ...]
    stations: tuple[ChargingStation, ...]
    vehicle: VehicleSpec
    fleet_size: int
    metric: str = "euclidean"
    distance: np.ndarray = field(default=None, repr=False, compare=False)  # type: ignore[assignment]
    travel_time: np.ndarray = field(default=None, repr=False, compare=False)  # type: ignore[assignment]

    # -- construction -----------------------------------------------------
    @classmethod
    def build(
        cls,
        name: str,
        depot: Node,
        customers: Sequence[Node],
        stations: Sequence[ChargingStation] = (),
        vehicle: VehicleSpec | None = None,
        fleet_size: int = 25,
        metric: str = "euclidean",
    ) -> "Instance":
        if metric not in METRICS:
            raise InstanceError(f"unknown metric {metric!r}; expected one of {sorted(METRICS)}")
        if fleet_size <= 0:
            raise InstanceError("fleet_size must be > 0")
        vehicle = vehicle or VehicleSpec()
        vehicle.validate()

        depot = Node(**{**depot.__dict__, "kind": NodeKind.DEPOT, "id": 0, "demand": 0.0})
        nodes: list[Node] = [depot]
        for i, c in enumerate(customers, start=1):
            nodes.append(Node(**{**c.__dict__, "id": i, "kind": NodeKind.CUSTOMER}))
        offset = len(nodes)
        for j, s in enumerate(stations):
            nodes.append(s.as_node(offset + j))

        for n in nodes:
            n.validate()

        xs = np.array([n.x for n in nodes], dtype=float)
        ys = np.array([n.y for n in nodes], dtype=float)
        dist = METRICS[metric](xs, ys)
        np.fill_diagonal(dist, 0.0)
        tt = dist / vehicle.speed_km_per_min

        inst = cls(
            name=name,
            nodes=tuple(nodes),
            stations=tuple(stations),
            vehicle=vehicle,
            fleet_size=fleet_size,
            metric=metric,
            distance=dist,
            travel_time=tt,
        )
        inst.validate()
        return inst

    # -- views ------------------------------------------------------------
    @property
    def depot(self) -> Node:
        return self.nodes[0]

    @property
    def customers(self) -> tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.kind is NodeKind.CUSTOMER)

    @property
    def station_nodes(self) -> tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.kind is NodeKind.STATION)

    @property
    def n_customers(self) -> int:
        return sum(1 for n in self.nodes if n.kind is NodeKind.CUSTOMER)

    @property
    def n_nodes(self) -> int:
        return len(self.nodes)

    @property
    def customer_indices(self) -> tuple[int, ...]:
        return tuple(range(1, self.n_customers + 1))

    @property
    def station_indices(self) -> tuple[int, ...]:
        return tuple(range(self.n_customers + 1, self.n_nodes))

    @property
    def total_demand(self) -> float:
        return float(sum(n.demand for n in self.customers))

    @property
    def horizon(self) -> float:
        return float(self.depot.due_time)

    def station_for_node(self, node_index: int) -> ChargingStation:
        if node_index not in self.station_indices:
            raise InstanceError(f"node {node_index} is not a charging station")
        return self.stations[node_index - self.n_customers - 1]

    def is_station(self, node_index: int) -> bool:
        return self.nodes[node_index].kind is NodeKind.STATION

    def with_stations(self, stations: Sequence[ChargingStation]) -> "Instance":
        """Rebuild the instance with a different charging network."""
        return Instance.build(
            name=self.name,
            depot=self.depot,
            customers=self.customers,
            stations=stations,
            vehicle=self.vehicle,
            fleet_size=self.fleet_size,
            metric=self.metric,
        )

    def with_vehicle(self, vehicle: VehicleSpec, fleet_size: int | None = None) -> "Instance":
        return Instance.build(
            name=self.name,
            depot=self.depot,
            customers=self.customers,
            stations=self.stations,
            vehicle=vehicle,
            fleet_size=self.fleet_size if fleet_size is None else fleet_size,
            metric=self.metric,
        )

    # -- validation -------------------------------------------------------
    def validate(self) -> None:
        if self.n_customers == 0:
            raise InstanceError("instance has no customers")
        if self.distance.shape != (self.n_nodes, self.n_nodes):
            raise InstanceError("distance matrix shape does not match node count")
        if not np.allclose(self.distance, self.distance.T, atol=1e-9):
            raise InstanceError("distance matrix is not symmetric")
        if float(np.min(self.distance)) < 0:
            raise InstanceError("distance matrix contains negative entries")

    def reachable_charge_points(self, max_range_km: float) -> set[int]:
        """Charge points (depot + stations) reachable from the depot by hopping.

        Classic E-VRP preprocessing: with a finite range, the charging network
        induces a graph on the charge points, and anything outside the depot's
        connected component can never be used.
        """
        points = [0, *self.station_indices]
        seen = {0}
        frontier = [0]
        while frontier:
            cur = frontier.pop()
            for p in points:
                if p not in seen and self.distance[cur][p] <= max_range_km + 1e-9:
                    seen.add(p)
                    frontier.append(p)
        return seen

    def unreachable_customers(self, max_range_km: float) -> list[int]:
        """Customers no vehicle can serve and still get to a charge point.

        A customer is serviceable only if some reachable charge point can get
        the vehicle to it and some charge point can be reached afterwards,
        within one pack's worth of range.
        """
        reachable = self.reachable_charge_points(max_range_km)
        points = [0, *self.station_indices]
        out = []
        for c in self.customer_indices:
            ok = any(
                self.distance[p][c] + self.distance[c][q] <= max_range_km + 1e-9
                for p in reachable
                for q in points
            )
            if not ok:
                out.append(c)
        return out

    def diagnostics(self, energy_config=None) -> list[str]:
        """Non-fatal warnings about the instance / fleet combination.

        These are the checks that explain *why* a solver returns "no solution",
        which is otherwise the least actionable error message in routing.
        Passing an :class:`~evrp.config.EnergyConfig` adds the range checks.
        """
        issues: list[str] = []
        cap = self.vehicle.payload_capacity
        if cap * self.fleet_size < self.total_demand:
            issues.append(
                f"fleet capacity {cap * self.fleet_size:.0f} < total demand "
                f"{self.total_demand:.0f}: at least "
                f"{math.ceil(self.total_demand / cap)} vehicles are required"
            )
        oversized = [c.id for c in self.customers if c.demand > cap]
        if oversized:
            issues.append(
                f"{len(oversized)} customer(s) demand more than one vehicle can carry: {oversized[:5]}"
            )
        for c in self.customers:
            travel = self.travel_time[0][c.id]
            if c.due_time < travel:
                issues.append(
                    f"customer {c.id} is unreachable: earliest arrival {travel:.1f} "
                    f"> due time {c.due_time:.1f}"
                )
            back = c.due_time + c.service_time + self.travel_time[c.id][0]
            if back > self.horizon + 1e-6:
                issues.append(
                    f"customer {c.id} cannot be served and returned before the depot "
                    f"closes ({back:.1f} > {self.horizon:.1f})"
                )

        if energy_config is not None:
            from evrp.energy import EnergyModel

            model = EnergyModel(energy_config, self.vehicle)
            # Conservative: assume the pack is worked at full payload.
            max_range = model.range_km(self.vehicle.battery_kwh, cap)
            stranded = self.unreachable_customers(max_range)
            if stranded:
                issues.append(
                    f"{len(stranded)} customer(s) are out of range of the charging "
                    f"network at {max_range:.0f} km per charge: {stranded[:5]}"
                )
            isolated = set(self.station_indices) - self.reachable_charge_points(max_range)
            if isolated:
                issues.append(
                    f"{len(isolated)} charging station(s) cannot be reached from the "
                    f"depot within {max_range:.0f} km: {sorted(isolated)[:5]}"
                )
        return issues


# -- Solomon parsing ------------------------------------------------------

_COLUMN_ALIASES = {
    "cust no.": "id", "custno": "id", "cust_no": "id", "customer": "id",
    "id": "id", "customerid": "id", "customer_id": "id", "cust no": "id",
    "xcoord.": "x", "xcoord": "x", "x": "x", "x_coord": "x", "x_coordinate": "x",
    "ycoord.": "y", "ycoord": "y", "y": "y", "y_coord": "y", "y_coordinate": "y",
    "demand": "demand",
    "ready time": "ready_time", "readytime": "ready_time", "ready_time": "ready_time",
    "due date": "due_time", "duedate": "due_time", "due time": "due_time",
    "duetime": "due_time", "due_time": "due_time", "due_date": "due_time",
    "service time": "service_time", "servicetime": "service_time",
    "service_time": "service_time",
}

REQUIRED_COLUMNS = ("id", "x", "y", "demand", "ready_time", "due_time", "service_time")


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map the many spellings of Solomon column headers onto canonical names."""
    renamed = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in _COLUMN_ALIASES:
            renamed[col] = _COLUMN_ALIASES[key]
    out = df.rename(columns=renamed)
    missing = [c for c in REQUIRED_COLUMNS if c not in out.columns]
    if missing:
        raise InstanceError(
            f"missing required column(s) {missing}; got {list(df.columns)}"
        )
    return out[list(REQUIRED_COLUMNS)]


def read_solomon_frame(source) -> pd.DataFrame:
    """Read a Solomon CSV (path or file-like) into a canonical DataFrame."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"instance file not found: {path}")
        df = pd.read_csv(path)
    else:
        df = pd.read_csv(source)
    if df.empty:
        raise InstanceError("instance file contains no rows")
    df = normalise_columns(df)
    for col in REQUIRED_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if df.isna().any().any():
        bad = df[df.isna().any(axis=1)]
        raise InstanceError(
            f"instance file has {len(bad)} row(s) with non-numeric or missing values "
            f"(first offending row index {bad.index[0]})"
        )
    return df


def load_solomon(
    source,
    name: str | None = None,
    vehicle: VehicleSpec | None = None,
    fleet_size: int = 25,
    stations: Sequence[ChargingStation] = (),
    metric: str = "euclidean",
    depot_row: int = 0,
) -> Instance:
    """Load a Solomon-format instance.

    The first data row is the depot (this is the Solomon convention and matches
    the CSVs shipped in ``data/``, whose customer numbering starts at 1 for the
    depot).  Customers are renumbered 1..n so that node index == customer index.
    """
    df = read_solomon_frame(source)
    if len(df) < 2:
        raise InstanceError("instance needs a depot row plus at least one customer")

    depot_raw = df.iloc[depot_row]
    depot = Node(
        id=0,
        x=float(depot_raw["x"]),
        y=float(depot_raw["y"]),
        demand=0.0,
        ready_time=float(depot_raw["ready_time"]),
        due_time=float(depot_raw["due_time"]),
        service_time=float(depot_raw["service_time"]),
        kind=NodeKind.DEPOT,
    )
    customers = [
        Node(
            id=i,
            x=float(r["x"]),
            y=float(r["y"]),
            demand=float(r["demand"]),
            ready_time=float(r["ready_time"]),
            due_time=float(r["due_time"]),
            service_time=float(r["service_time"]),
            kind=NodeKind.CUSTOMER,
        )
        for i, (_, r) in enumerate(df.drop(df.index[depot_row]).iterrows(), start=1)
    ]

    if name is None:
        name = Path(source).stem if isinstance(source, (str, Path)) else "instance"

    return Instance.build(
        name=name,
        depot=depot,
        customers=customers,
        stations=stations,
        vehicle=vehicle,
        fleet_size=fleet_size,
        metric=metric,
    )


def instance_from_scenario(scenario: Scenario, source: str | None = None) -> Instance:
    """Build the full instance (customers + generated charging network) for a scenario."""
    from evrp.stations import generate_stations  # local import: avoids a cycle

    scenario.validate()
    base = load_solomon(
        source or scenario.instance_file,
        vehicle=scenario.vehicle,
        fleet_size=scenario.fleet_size,
    )
    if scenario.n_stations == 0 or scenario.station_strategy == "none":
        return base
    peak_window = (
        (scenario.peak_start_min, scenario.peak_end_min)
        if scenario.peak_start_min is not None and scenario.peak_end_min is not None
        else None
    )
    stations = generate_stations(
        base,
        n_stations=scenario.n_stations,
        strategy=scenario.station_strategy,
        power_kw=scenario.station_power_kw,
        seed=scenario.solver.seed,
        peak_window=peak_window,
    )
    return base.with_stations(stations)
