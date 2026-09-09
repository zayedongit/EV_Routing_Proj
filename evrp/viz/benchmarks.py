"""Charts for the benchmark tables."""

from __future__ import annotations

import matplotlib

if matplotlib.get_backend().lower() not in ("agg", "module://matplotlib_inline.backend_inline"):
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from evrp.viz import theme


def plot_solver_comparison(frame: pd.DataFrame, figsize: tuple[float, float] = (11, 5)):
    """Grouped bars: route distance per instance, one group per solver."""
    if frame.empty:
        raise ValueError("no benchmark rows to plot")
    pivot = frame.pivot_table(
        index="instance", columns="solver", values="distance_km", aggfunc="min"
    )
    fig, ax = plt.subplots(figsize=figsize)
    n = len(pivot.columns)
    width = 0.8 / max(n, 1)
    x = np.arange(len(pivot.index))
    for i, solver in enumerate(pivot.columns):
        ax.bar(
            x + i * width - 0.4 + width / 2,
            pivot[solver].values,
            width=width,
            label=solver,
            color=theme.route_color(i),
        )
    ax.set_xticks(x)
    ax.set_xticklabels(pivot.index, rotation=0)
    theme.style_axes(ax, "Total route distance by solver", "Instance", "Distance (km)")
    theme.style_legend(ax, fontsize=9)
    fig.tight_layout()
    return fig


def plot_battery_sensitivity(frame: pd.DataFrame, figsize: tuple[float, float] = (11, 4.5)):
    """Distance and charging stops as the usable pack shrinks.

    This is the plot that shows the EV part of the problem doing something:
    below a certain range the router has to start buying energy mid-route, and
    the distance curve bends.
    """
    if frame.empty:
        raise ValueError("no benchmark rows to plot")
    fig, axes = plt.subplots(1, 2, figsize=figsize)
    grouped = frame.groupby(["instance", "battery_kwh"], as_index=False).agg(
        distance_km=("distance_km", "min"),
        charging_stops=("charging_stops", "mean"),
        feasible=("feasible", "max"),
    )
    for i, (instance, sub) in enumerate(grouped.groupby("instance")):
        sub = sub.sort_values("battery_kwh")
        color = theme.route_color(i)
        axes[0].plot(sub["battery_kwh"], sub["distance_km"], "o-", color=color, label=instance)
        axes[1].plot(sub["battery_kwh"], sub["charging_stops"], "o-", color=color, label=instance)

    theme.style_axes(axes[0], "Route distance vs usable battery", "Battery (kWh)", "Distance (km)")
    theme.style_axes(axes[1], "Charging stops vs usable battery", "Battery (kWh)", "Charging stops")
    theme.style_legend(axes[0], fontsize=9)
    fig.tight_layout()
    return fig
