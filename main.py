"""End-to-end demo: solve, verify, plot and report.

Running ``python main.py`` reproduces the original two tasks -- plain VRP with
time windows, and VRP with grid discharge -- and adds the parts the original
could not do: an energy-feasible route with charging stops, an independent
feasibility check on every result, and a state-of-charge trace.

    python main.py                       # default demo on C101
    python main.py --instance data/R101.csv --battery 25
    python main.py --legacy              # also run the original two solvers

For anything beyond the demo use the CLI, which has the benchmark, sensitivity
and V2G experiments:

    python -m evrp.cli --help
"""

from __future__ import annotations

import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from evrp.config import Scenario, SolverConfig, VehicleSpec
from evrp.energy import EnergyModel
from evrp.instance import instance_from_scenario
from evrp.solvers import create
from evrp.solvers.base import SolverError
from evrp.v2g import apply_v2g
from evrp.viz import plot_fleet_soc, plot_solution

OUTPUT_DIR = "outputs"


def _save(fig, path: str) -> None:
    fig.savefig(path, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  saved {path}")


def run_modern(args) -> int:
    scenario = Scenario(
        name="demo",
        instance_file=args.instance,
        fleet_size=args.fleet,
        n_stations=args.stations,
        vehicle=VehicleSpec(payload_capacity=args.capacity, battery_kwh=args.battery),
        solver=SolverConfig(time_limit_s=args.time_limit, seed=args.seed),
    )
    instance = instance_from_scenario(scenario)
    model = EnergyModel(scenario.energy, scenario.vehicle)

    print(f"Instance {instance.name}: {instance.n_customers} customers, "
          f"{len(instance.stations)} chargers, demand {instance.total_demand:g}")
    print(f"Vehicle: {scenario.vehicle.battery_kwh:g} kWh usable pack, "
          f"{model.full_range_km:.0f} km of range empty, "
          f"{model.range_km(scenario.vehicle.battery_kwh, scenario.vehicle.payload_capacity):.0f} km loaded")
    for issue in instance.diagnostics(scenario.energy):
        print(f"  warning: {issue}", file=sys.stderr)

    print("\nSolving (energy-aware VRPTW with charging stations)...")
    results = {}
    for name in ("ortools", "insertion-ls", "savings"):
        try:
            solution = create(
                name,
                solver_config=scenario.solver,
                energy_config=scenario.energy,
                charging_config=scenario.charging,
            ).solve(instance)
        except SolverError as exc:
            print(f"  {name}: {exc}")
            continue
        results[name] = solution
        print(f"  {solution.summary()}")

    if not results:
        print("No solver produced a solution.", file=sys.stderr)
        return 2

    best = min(
        (s for s in results.values() if s.feasible),
        key=lambda s: s.metrics.total_distance,
        default=None,
    )
    if best is None:
        best = min(results.values(), key=lambda s: s.metrics.total_distance)
        print("\nNo fully feasible solution; plotting the closest one.")
    else:
        print(f"\nBest verified plan: {best.solver} at {best.metrics.total_distance:.2f} km")

    _save(plot_solution(instance, best), os.path.join(OUTPUT_DIR, "routes.png"))
    _save(plot_fleet_soc(instance, best), os.path.join(OUTPUT_DIR, "soc_profile.png"))

    print("\nGrid discharge (V2G): pricing detours against the energy they sell...")
    with_v2g, report = apply_v2g(instance, best, scenario.energy, scenario.charging)
    payload = report.to_dict()
    print(f"  routes taking a V2G stop : {payload['routes_with_v2g']}")
    print(f"  extra distance           : {payload['extra_km']:.2f} km")
    print(f"  energy sold              : {payload['discharged_kwh']:.1f} kWh")
    print(f"  net gain                 : {payload['net_gain']:.2f}")
    if payload["routes_with_v2g"]:
        _save(plot_solution(instance, with_v2g), os.path.join(OUTPUT_DIR, "routes_v2g.png"))

    best.to_json(os.path.join(OUTPUT_DIR, "solution.json"))
    scenario.to_json(os.path.join(OUTPUT_DIR, "scenario.json"))
    print(f"  saved {os.path.join(OUTPUT_DIR, 'solution.json')}")
    return 0 if best.feasible else 1


def run_legacy(args) -> None:
    """The original task 1 and task 2 solvers, kept working for comparison."""
    from models.ev import GridStation
    from parsers.solomon_parser import parse_solomon_dataset
    from solver.task1_vrp_solver import NoSolutionError, VRPSolver
    from solver.task2_vrp_discharge_solver import Customer as LegacyCustomer
    from solver.task2_vrp_discharge_solver import VRPDischargeSolver, Vehicle
    from visualization.map_plotter import plot_routes

    print("\n" + "=" * 62)
    print("Legacy solvers (original project code, bugs fixed)")
    print("=" * 62)

    depot, customers = parse_solomon_dataset(args.instance)

    print("\nTask 1 - VRP with time windows (OR-Tools):")
    try:
        routes = VRPSolver(
            depot, customers, args.fleet,
            vehicle_capacity=args.capacity, time_limit_s=args.time_limit,
        ).solve()
        total = sum(r["distance"] for r in routes)
        served = sum(r["customers_served"] for r in routes)
        print(f"  {total:.2f} km, {len(routes)} vehicles, {served}/{len(customers)} customers")
        _save(
            plot_routes(depot, customers, [], routes, "Task 1: VRP with time windows"),
            os.path.join(OUTPUT_DIR, "basic_vrp_routes.png"),
        )
    except NoSolutionError as exc:
        print(f"  no solution: {exc}")

    print("\nTask 2 - VRP with grid discharge (genetic algorithm):")
    legacy_customers = [
        LegacyCustomer(i, c.x, c.y, c.demand, c.ready_time, c.due_date, c.service_time)
        for i, c in enumerate(customers, start=1)
    ]
    legacy_depot = LegacyCustomer(
        0, depot.x, depot.y, 0, depot.ready_time, depot.due_date, 0
    )
    vehicles = [Vehicle(int(args.capacity), args.battery, 0.2) for _ in range(args.fleet)]
    solution = VRPDischargeSolver(
        legacy_customers, legacy_depot, vehicles,
        enable_discharge=True, max_iterations=args.ga_iterations,
    ).solve()
    print(f"  {solution['total_distance']:.2f} km, {solution['vehicles_used']} vehicles, "
          f"{solution['customers_served']}/{len(customers)} customers, "
          f"success={solution['success']}")
    grid_stations = [GridStation(id=1, x=40, y=50), GridStation(id=2, x=60, y=60)]
    _save(
        plot_routes(depot, customers, grid_stations, solution["routes"],
                    "Task 2: VRP with grid discharge"),
        os.path.join(OUTPUT_DIR, "discharge_vrp_routes.png"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--instance", default="data/C101.csv")
    parser.add_argument("--fleet", type=int, default=25)
    parser.add_argument("--capacity", type=float, default=200.0)
    parser.add_argument("--battery", type=float, default=40.0, help="usable pack in kWh")
    parser.add_argument("--stations", type=int, default=6)
    parser.add_argument("--time-limit", type=float, default=20.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--legacy", action="store_true",
                        help="also run the original task 1 / task 2 solvers")
    parser.add_argument("--ga-iterations", type=int, default=300,
                        help="iteration budget for the legacy genetic algorithm")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    code = run_modern(args)
    if args.legacy:
        run_legacy(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
