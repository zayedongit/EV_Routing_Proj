"""Charging-network generation.

The Solomon benchmark instances contain no charging infrastructure, so an
E-VRPTW study has to place it.  Placement is a modelling decision that changes
results, so it is explicit, seeded and reproducible rather than hard-coded.

Strategies
----------
``kmeans``  Lloyd's algorithm on the customer coordinates with k-means++ seeding.
            Stations end up where demand is, which is where a fleet operator
            would put them.
``grid``    Stations on a regular lattice clipped to the customer bounding box:
            a deterministic, geometry-only baseline.
``random``  Uniform samples in the bounding box; only useful as a control.
"""

from __future__ import annotations

import numpy as np

from evrp.instance import ChargingStation, Instance, InstanceError


def _kmeans(points: np.ndarray, k: int, seed: int, iters: int = 100) -> np.ndarray:
    """Lloyd's algorithm with k-means++ initialisation (no sklearn dependency)."""
    rng = np.random.default_rng(seed)
    n = len(points)
    k = min(k, n)

    centres = np.empty((k, points.shape[1]))
    centres[0] = points[rng.integers(n)]
    closest = np.sum((points - centres[0]) ** 2, axis=1)
    for i in range(1, k):
        total = closest.sum()
        probs = closest / total if total > 0 else np.full(n, 1.0 / n)
        centres[i] = points[rng.choice(n, p=probs)]
        closest = np.minimum(closest, np.sum((points - centres[i]) ** 2, axis=1))

    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        d = np.sum((points[:, None, :] - centres[None, :, :]) ** 2, axis=2)
        new_labels = np.argmin(d, axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for j in range(k):
            members = points[labels == j]
            if len(members):
                centres[j] = members.mean(axis=0)
    return centres


def generate_stations(
    instance: Instance,
    n_stations: int,
    strategy: str = "kmeans",
    power_kw: float = 50.0,
    seed: int = 42,
    peak_window: tuple[float, float] | None = None,
    v2g_capable: bool = True,
) -> tuple[ChargingStation, ...]:
    """Place ``n_stations`` chargers over the customer geography.

    A charger is always co-located with the depot (index 0 of the returned
    tuple) because depots of electric fleets are charged overnight and during
    the day; without it, instances with tight batteries become trivially
    infeasible for reasons that have nothing to do with routing.
    """
    if n_stations < 0:
        raise InstanceError("n_stations must be >= 0")
    if n_stations == 0:
        return ()
    if power_kw <= 0:
        raise InstanceError("power_kw must be > 0")

    customers = instance.customers
    pts = np.array([[c.x, c.y] for c in customers], dtype=float)
    depot = instance.depot
    horizon = instance.horizon

    coords: list[tuple[float, float]] = [(depot.x, depot.y)]
    remaining = n_stations - 1

    if remaining > 0:
        if strategy == "kmeans":
            centres = _kmeans(pts, remaining, seed)
            coords.extend((float(cx), float(cy)) for cx, cy in centres)
        elif strategy == "grid":
            side = int(np.ceil(np.sqrt(remaining)))
            xs = np.linspace(pts[:, 0].min(), pts[:, 0].max(), side + 2)[1:-1]
            ys = np.linspace(pts[:, 1].min(), pts[:, 1].max(), side + 2)[1:-1]
            lattice = [(float(x), float(y)) for y in ys for x in xs]
            coords.extend(lattice[:remaining])
        elif strategy == "random":
            rng = np.random.default_rng(seed)
            for _ in range(remaining):
                coords.append(
                    (
                        float(rng.uniform(pts[:, 0].min(), pts[:, 0].max())),
                        float(rng.uniform(pts[:, 1].min(), pts[:, 1].max())),
                    )
                )
        else:
            raise InstanceError(f"unknown station strategy {strategy!r}")

    peak_start, peak_end = peak_window if peak_window else (None, None)
    return tuple(
        ChargingStation(
            id=i,
            x=round(x, 4),
            y=round(y, 4),
            power_kw=power_kw,
            ready_time=depot.ready_time,
            due_time=horizon,
            v2g_capable=v2g_capable,
            peak_start=peak_start,
            peak_end=peak_end,
        )
        for i, (x, y) in enumerate(coords)
    )
