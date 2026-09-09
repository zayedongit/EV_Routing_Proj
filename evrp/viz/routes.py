"""Route maps that show the things an EV plan is judged on.

Beyond "lines between dots", the map marks where each vehicle stopped to
charge and annotates every route with the state of charge it came home on,
which is the number that decides whether the plan is operable.
"""

from __future__ import annotations

import matplotlib

if matplotlib.get_backend().lower() not in ("agg", "module://matplotlib_inline.backend_inline"):
    matplotlib.use("Agg")

import matplotlib.pyplot as plt

from evrp.instance import Instance, NodeKind
from evrp.solution import Solution
from evrp.viz import theme


def plot_solution(
    instance: Instance,
    solution: Solution,
    title: str | None = None,
    annotate_soc: bool = True,
    figsize: tuple[float, float] = (11, 8),
    max_legend_entries: int = 12,
):
    """Draw depot, customers, charging stations and every route."""
    fig, ax = plt.subplots(figsize=figsize)

    customers = instance.customers
    ax.scatter(
        [c.x for c in customers], [c.y for c in customers],
        c=theme.CUSTOMER, s=42, alpha=0.85, zorder=3, label=f"Customers ({len(customers)})",
        edgecolors="none",
    )

    stations = instance.station_nodes
    if stations:
        ax.scatter(
            [s.x for s in stations], [s.y for s in stations],
            c=theme.STATION, s=170, marker="^", zorder=5,
            edgecolors="#0E1013", linewidth=1.4, label=f"Chargers ({len(stations)})",
        )

    depot = instance.depot
    ax.scatter(
        [depot.x], [depot.y], c=theme.DEPOT, s=260, marker="s", zorder=6,
        edgecolors="#0E1013", linewidth=1.8, label="Depot",
    )

    used = [(i, r) for i, r in enumerate(solution.routes) if r]
    for i, route in used:
        color = theme.route_color(i)
        xs = [depot.x] + [instance.nodes[n].x for n in route] + [depot.x]
        ys = [depot.y] + [instance.nodes[n].y for n in route] + [depot.y]
        label = None
        if i < max_legend_entries:
            label = f"EV {i + 1}"
            if annotate_soc and i < len(solution.simulations):
                sim = solution.simulations[i]
                if sim.stops:
                    label += f" ({sim.distance:.0f} km, {sim.stops[-1].soc_arrival:.1f} kWh left)"
        ax.plot(xs, ys, color=color, linewidth=2.0, alpha=0.9, zorder=4, label=label)

        charge_stops = [n for n in route if instance.nodes[n].kind is NodeKind.STATION]
        if charge_stops:
            ax.scatter(
                [instance.nodes[n].x for n in charge_stops],
                [instance.nodes[n].y for n in charge_stops],
                s=290, facecolors="none", edgecolors=color, linewidth=2.2, zorder=7,
            )

    if title is None:
        m = solution.metrics
        flag = "" if solution.feasible else "  [INFEASIBLE]"
        title = (
            f"{solution.solver} - {instance.name}: {m.total_distance:.1f} km, "
            f"{m.vehicles_used} EVs, {m.charging_stops} charging stops{flag}"
        )
    theme.style_axes(ax, title, "X (km)", "Y (km)")
    theme.style_legend(ax, loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=9)
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    return fig
