"""Distance helpers.

Historical note: this module used to export a function called
``haversine_distance`` that computed a plain Euclidean distance on the
Solomon x/y grid.  The name was wrong, not the behaviour -- benchmark
coordinates are planar, so Euclidean is the right metric there, and the
published Solomon results depend on it.

Rather than silently keep a misnamed function, the two metrics are now
separate: :func:`euclidean_distance` is what planar instances use, and
:func:`haversine_distance` really is the great-circle distance, for the day
this runs on real latitude/longitude data.  ``planar_distance`` is kept as an
alias for callers that used the old name for its old behaviour.

For bulk work prefer :mod:`evrp.instance`, which builds the whole matrix in
one vectorised NumPy pass instead of calling a Python function n^2 times.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def euclidean_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Straight-line distance between two points on a plane."""
    return math.hypot(x2 - x1, y2 - y1)


def manhattan_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Grid distance: a better proxy than Euclidean for dense street networks."""
    return abs(x2 - x1) + abs(y2 - y1)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two lat/lon points."""
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = lat2_r - lat1_r
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, max(0.0, a))))


#: Backwards-compatible alias for the planar metric the project actually uses.
planar_distance = euclidean_distance
