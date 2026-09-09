"""Plotting helpers.  Matplotlib only, so they work headless and in Streamlit."""

from evrp.viz.routes import plot_solution
from evrp.viz.soc import plot_soc_profile, plot_fleet_soc
from evrp.viz.benchmarks import plot_solver_comparison, plot_battery_sensitivity

__all__ = [
    "plot_solution",
    "plot_soc_profile",
    "plot_fleet_soc",
    "plot_solver_comparison",
    "plot_battery_sensitivity",
]
