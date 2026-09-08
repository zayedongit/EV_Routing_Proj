"""Legacy route plot, kept for ``main.py``, the Streamlit dashboard and any
existing notebooks.  New code should prefer :func:`evrp.viz.plot_solution`,
which also marks charging stops and annotates remaining state of charge.

Two robustness fixes over the original:

* route dictionaries are accepted with or without a ``customers_served`` key,
  so both solvers' output shapes work;
* node indices outside the customer list (a charging station, say) are skipped
  instead of raising ``IndexError`` in the middle of a plot.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

import matplotlib

if matplotlib.get_backend().lower() not in ("agg", "module://matplotlib_inline.backend_inline"):
    matplotlib.use("Agg")

import matplotlib.pyplot as plt

PALETTE = [
    "#4C9AFF", "#3ED598", "#FFB020", "#B57BFF", "#FF6B9D",
    "#5AD1E6", "#FF8F5A", "#9BE564", "#F26D6D", "#7FA0FF",
]


def _node_xy(depot, customers: Sequence, node: int):
    """Coordinates for a route node, or ``None`` if it is not a known stop."""
    if node == 0:
        return depot.x, depot.y
    index = node - 1
    if 0 <= index < len(customers):
        return customers[index].x, customers[index].y
    return None


def plot_routes(
    depot,
    customers: Sequence,
    grid_stations: Sequence,
    routes: List[Dict[str, Any]],
    title: str = "EV Routing Solution",
):
    """Plot vehicle routes over the customer geography."""
    fig, ax = plt.subplots(figsize=(12, 8.5))
    fig.patch.set_facecolor("#14161A")
    ax.set_facecolor("#1C1F24")

    ax.scatter(
        [c.x for c in customers], [c.y for c in customers],
        c="#4C9AFF", s=46, label=f"Customers ({len(customers)})", zorder=4, alpha=0.9,
    )
    if grid_stations:
        ax.scatter(
            [g.x for g in grid_stations], [g.y for g in grid_stations],
            c="#3ED598", s=180, marker="^", zorder=5,
            edgecolors="#0E1013", linewidth=1.4, label="Grid stations",
        )
    ax.scatter(
        [depot.x], [depot.y], c="#FF6B5A", s=250, marker="s", zorder=6,
        edgecolors="#0E1013", linewidth=1.8, label="Depot",
    )

    drawn = 0
    for i, info in enumerate(routes or []):
        nodes = info.get("route", [])
        served = info.get("customers_served")
        if served is not None and served <= 0:
            continue
        points = [(depot.x, depot.y)]
        for node in nodes:
            xy = _node_xy(depot, customers, node)
            if xy is not None:
                points.append(xy)
        points.append((depot.x, depot.y))
        if len(points) <= 2:
            continue
        colour = PALETTE[i % len(PALETTE)]
        ax.plot(
            [p[0] for p in points], [p[1] for p in points],
            color=colour, linewidth=2.2, alpha=0.9, zorder=3,
            label=f"EV {i + 1}" if drawn < 10 else None,
        )
        drawn += 1

    ax.set_xlabel("X coordinate", fontsize=11, color="#9AA4B2")
    ax.set_ylabel("Y coordinate", fontsize=11, color="#9AA4B2")
    ax.set_title(title, fontsize=15, fontweight="bold", color="#F2F4F7")
    legend = ax.legend(frameon=True, facecolor="#1C1F24", edgecolor="#2E333A", fontsize=9)
    for text in legend.get_texts():
        text.set_color("#F2F4F7")
    ax.tick_params(colors="#9AA4B2")
    ax.grid(color="#2E333A", linestyle="--", linewidth=0.6)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_edgecolor("#2E333A")
    fig.tight_layout()
    return fig
