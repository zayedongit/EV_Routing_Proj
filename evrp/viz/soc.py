"""State-of-charge profiles.

A route map cannot show whether a plan was comfortable or one traffic light
away from a tow truck.  The SoC trace can: it plots the pack level against
distance travelled, with the reserve floor drawn in and charging events shown
as the vertical jumps they are.
"""

from __future__ import annotations

import matplotlib

if matplotlib.get_backend().lower() not in ("agg", "module://matplotlib_inline.backend_inline"):
    matplotlib.use("Agg")

import matplotlib.pyplot as plt

from evrp.feasibility import RouteSimulation
from evrp.instance import Instance, NodeKind
from evrp.solution import Solution
from evrp.viz import theme


def _draw_profile(ax, instance: Instance, sim: RouteSimulation, color: str, label: str):
    pts = sim.soc_profile()
    if not pts:
        return
    xs = [0.0] + [p[0] for p in pts]
    ys = [instance.vehicle.battery_kwh] + [p[1] for p in pts]
    ax.plot(xs, ys, color=color, linewidth=1.9, label=label, zorder=4)
    charge_x = [
        x for (x, _), stop in zip(pts, sim.stops)
        if stop.kind is NodeKind.STATION and stop.charged_kwh > 1e-6
    ]
    if charge_x:
        ax.scatter(
            charge_x,
            [instance.vehicle.battery_kwh * 0.02] * len(charge_x),
            marker="^", s=90, color=theme.STATION, zorder=6,
        )


def plot_soc_profile(
    instance: Instance,
    sim: RouteSimulation,
    title: str = "State of charge along the route",
    figsize: tuple[float, float] = (10, 4.5),
):
    """SoC trace of a single route."""
    fig, ax = plt.subplots(figsize=figsize)
    _draw_profile(ax, instance, sim, theme.CUSTOMER, "State of charge")

    battery = instance.vehicle.battery_kwh
    reserve = instance.vehicle.min_soc_kwh
    ax.axhline(battery, color=theme.MUTED, linestyle=":", linewidth=1.0)
    ax.axhspan(0, reserve, color=theme.DANGER, alpha=0.16, zorder=1)
    ax.axhline(reserve, color=theme.DANGER, linestyle="--", linewidth=1.2,
               label=f"Reserve ({reserve:.1f} kWh)")
    ax.set_ylim(0, battery * 1.08)

    theme.style_axes(ax, title, "Distance travelled (km)", "Pack energy (kWh)")
    theme.style_legend(ax, loc="lower left", fontsize=9)
    fig.tight_layout()
    return fig


def plot_fleet_soc(
    instance: Instance,
    solution: Solution,
    max_routes: int = 12,
    figsize: tuple[float, float] = (10, 5),
):
    """Overlay the SoC traces of a whole solution."""
    fig, ax = plt.subplots(figsize=figsize)
    for i, sim in enumerate(solution.simulations[:max_routes]):
        _draw_profile(ax, instance, sim, theme.route_color(i), f"EV {i + 1}")

    battery = instance.vehicle.battery_kwh
    reserve = instance.vehicle.min_soc_kwh
    ax.axhspan(0, reserve, color=theme.DANGER, alpha=0.16, zorder=1)
    ax.axhline(reserve, color=theme.DANGER, linestyle="--", linewidth=1.2,
               label=f"Reserve ({reserve:.1f} kWh)")
    ax.set_ylim(0, battery * 1.08)
    theme.style_axes(
        ax,
        f"Fleet state of charge - {solution.solver} on {instance.name}",
        "Distance travelled (km)",
        "Pack energy (kWh)",
    )
    theme.style_legend(ax, loc="upper right", fontsize=8, ncol=2)
    fig.tight_layout()
    return fig
