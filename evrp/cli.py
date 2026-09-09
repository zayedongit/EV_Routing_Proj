"""Command-line entry point.

    python -m evrp.cli solve       --instance data/C101.csv
    python -m evrp.cli compare     --instances C101 R101 RC101
    python -m evrp.cli benchmark   --out results/
    python -m evrp.cli sensitivity --instances C101 R101
    python -m evrp.cli v2g         --instance data/R201.csv
    python -m evrp.cli validate    --instance data/C101.csv

Every subcommand takes ``--seed`` and ``--time-limit`` and writes the scenario
it actually ran next to its output, so a result can be reproduced later.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from evrp.benchmark import (
    DEFAULT_INSTANCES,
    build_row,
    environment_info,
    gap_table,
    make_scenarios,
    run_benchmark,
    solomon_capacity,
    summarise,
    to_markdown,
)
from evrp.config import ChargingConfig, EnergyConfig, Scenario, SolverConfig, VehicleSpec
from evrp.instance import InstanceError, instance_from_scenario
from evrp.solvers import available, create
from evrp.solvers.base import SolverError

DEFAULT_BATTERIES = (80.0, 40.0, 25.0, 18.0, 14.0)


# -- helpers --------------------------------------------------------------

def _scenario_from_args(args, name: str) -> Scenario:
    path = Path(args.instance)
    capacity = args.capacity
    if capacity is None:
        try:
            capacity = solomon_capacity(path.stem)
        except KeyError:
            capacity = 200
    return Scenario(
        name=name,
        instance_file=str(path),
        fleet_size=args.fleet,
        n_stations=args.stations,
        station_strategy=args.station_strategy,
        station_power_kw=args.station_power,
        peak_start_min=args.peak_window[0] if args.peak_window else None,
        peak_end_min=args.peak_window[1] if args.peak_window else None,
        vehicle=VehicleSpec(
            payload_capacity=capacity,
            battery_kwh=args.battery,
            reserve_soc=args.reserve,
        ),
        energy=EnergyConfig(),
        charging=ChargingConfig(v2g_enabled=getattr(args, "v2g", False)),
        solver=SolverConfig(
            time_limit_s=args.time_limit,
            seed=args.seed,
            station_copies=args.station_copies,
        ),
    )


def _save_figure(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140, facecolor=fig.get_facecolor())
    print(f"  wrote {path}")


# -- subcommands ----------------------------------------------------------

def cmd_solve(args) -> int:
    if args.scenario:
        scenario = Scenario.from_json(args.scenario)
        print(f"Loaded scenario {scenario.name} from {args.scenario}")
    else:
        scenario = _scenario_from_args(args, f"solve-{Path(args.instance).stem}")
    instance = instance_from_scenario(scenario)
    for note in instance.diagnostics(scenario.energy):
        print(f"  warning: {note}", file=sys.stderr)

    solver = create(
        args.solver,
        solver_config=scenario.solver,
        energy_config=scenario.energy,
        charging_config=scenario.charging,
    )
    try:
        solution = solver.solve(instance)
    except SolverError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(solution.summary())
    m = solution.metrics
    print(f"  energy used     : {m.energy_consumed_kwh:.1f} kWh")
    print(f"  energy charged  : {m.energy_charged_kwh:.1f} kWh "
          f"({m.total_charge_time:.0f} min plugged in)")
    print(f"  lowest pack SoC : {m.min_soc_kwh:.2f} kWh "
          f"(reserve {instance.vehicle.min_soc_kwh:.2f} kWh)")
    for v in solution.violations[:10]:
        print(f"  violation: {v}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    solution.to_json(out / f"{instance.name}-{args.solver}.json")
    scenario.to_json(out / f"{instance.name}-{args.solver}-scenario.json")
    if not args.no_plots:
        from evrp.viz import plot_fleet_soc, plot_solution

        _save_figure(plot_solution(instance, solution), out / f"{instance.name}-{args.solver}-routes.png")
        _save_figure(plot_fleet_soc(instance, solution), out / f"{instance.name}-{args.solver}-soc.png")
    print(f"  wrote {out / f'{instance.name}-{args.solver}.json'}")
    return 0 if solution.feasible else 1


def cmd_compare(args) -> int:
    scenarios = make_scenarios(
        args.instances,
        data_dir=args.data_dir,
        battery_kwh=args.battery,
        n_stations=args.stations,
        fleet_size=args.fleet,
        time_limit_s=args.time_limit,
        seed=args.seed,
        name_prefix="compare",
        station_copies=args.station_copies,
        station_strategy=args.station_strategy,
        station_power_kw=args.station_power,
        reserve_soc=args.reserve,
    )
    result = run_benchmark(scenarios, solvers=args.solvers, data_dir=args.data_dir)
    frame = result.to_frame()
    cols = ["instance", "solver", "distance_km", "vehicles", "charging_stops",
            "customers_served", "feasible", "runtime_s"]
    print()
    print(to_markdown(frame[cols]))
    print(to_markdown(summarise(frame)))

    out = Path(args.out)
    paths = result.save(out)
    gaps = gap_table(frame, reference_solver=args.reference)
    if not gaps.empty:
        gaps.to_csv(out / "gaps.csv", index=False)
        print(to_markdown(gaps))
    if not args.no_plots:
        from evrp.viz import plot_solver_comparison

        _save_figure(plot_solver_comparison(frame), out / "solver_comparison.png")
    print(f"  wrote {paths['csv']}")
    return 0


def cmd_benchmark(args) -> int:
    return cmd_compare(args)


def cmd_sensitivity(args) -> int:
    """Sweep usable battery capacity and watch the routing decisions change."""
    rows = []
    for battery in args.batteries:
        scenarios = make_scenarios(
            args.instances,
            data_dir=args.data_dir,
            battery_kwh=battery,
            n_stations=args.stations,
            fleet_size=args.fleet,
            time_limit_s=args.time_limit,
            seed=args.seed,
            name_prefix=f"battery{battery:g}",
            station_copies=args.station_copies,
            station_strategy=args.station_strategy,
            station_power_kw=args.station_power,
            reserve_soc=args.reserve,
        )
        print(f"battery = {battery:g} kWh")
        result = run_benchmark(scenarios, solvers=args.solvers, data_dir=args.data_dir)
        rows.extend(result.rows)

    frame = pd.DataFrame([r.to_dict() for r in rows])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out / "sensitivity.csv", index=False)
    cols = ["instance", "battery_kwh", "solver", "distance_km", "vehicles",
            "charging_stops", "charge_time_min", "customers_served", "feasible"]
    (out / "sensitivity.md").write_text(to_markdown(frame[cols]))
    print()
    print(to_markdown(frame[cols]))
    if not args.no_plots:
        from evrp.viz import plot_battery_sensitivity

        _save_figure(plot_battery_sensitivity(frame), out / "battery_sensitivity.png")
    print(f"  wrote {out / 'sensitivity.csv'}")
    return 0


def cmd_bounds(args) -> int:
    """Measure what the CP model's conservative energy bound actually costs.

    The model cannot know the payload on an arc, so it uses one payload-
    independent consumption rate.  ``worst`` (full payload) is the only setting
    that guarantees a model-feasible route also passes the exact simulator;
    ``average`` and ``empty`` produce shorter routes but may produce plans the
    simulator rejects.  This prints how often that actually happens.
    """
    from evrp.config import SolverConfig

    rows = []
    for mode in args.modes:
        print(f"consumption bound = {mode}")
        for inst in args.instances:
            capacity = solomon_capacity(inst)
            scenario = Scenario(
                name=f"bound-{mode}-{inst}",
                instance_file=str(Path(args.data_dir) / f"{inst}.csv"),
                fleet_size=args.fleet,
                n_stations=args.stations,
                vehicle=VehicleSpec(
                    payload_capacity=capacity, battery_kwh=args.battery
                ),
                solver=SolverConfig(
                    time_limit_s=args.time_limit,
                    seed=args.seed,
                    station_copies=args.station_copies,
                    model_consumption_mode=mode,
                ),
            )
            instance = instance_from_scenario(scenario)
            solver = create(
                "ortools",
                solver_config=scenario.solver,
                energy_config=scenario.energy,
                charging_config=scenario.charging,
            )
            try:
                solution = solver.solve(instance)
            except SolverError as exc:
                print(f"  {inst}: {exc}")
                continue
            print(f"  {solution.summary()}")
            row = build_row(scenario, instance, solution).to_dict()
            row["consumption_bound"] = mode
            rows.append(row)

    frame = pd.DataFrame(rows)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out / "consumption_bounds.csv", index=False)
    cols = ["instance", "consumption_bound", "distance_km", "vehicles",
            "charging_stops", "customers_served", "violations", "feasible"]
    (out / "consumption_bounds.md").write_text(to_markdown(frame[cols]))
    print()
    print(to_markdown(frame[cols]))
    print(f"  wrote {out / 'consumption_bounds.csv'}")
    return 0


def cmd_v2g(args) -> int:
    from evrp.v2g import apply_v2g

    scenario = _scenario_from_args(args, f"v2g-{Path(args.instance).stem}")
    instance = instance_from_scenario(scenario)
    solver = create(
        args.solver,
        solver_config=scenario.solver,
        energy_config=scenario.energy,
        charging_config=scenario.charging,
    )
    base = solver.solve(instance)
    print("baseline:", base.summary())

    with_v2g, report = apply_v2g(instance, base, scenario.energy, scenario.charging)
    print("with V2G:", with_v2g.summary())
    print(json.dumps(report.to_dict(), indent=2))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{instance.name}-v2g.json").write_text(
        json.dumps(
            {
                "scenario": scenario.to_dict(),
                "baseline": base.to_dict(),
                "with_v2g": with_v2g.to_dict(),
                "report": report.to_dict(),
            },
            indent=2,
            default=str,
        )
        + "\n"
    )
    if not args.no_plots:
        from evrp.viz import plot_solution

        _save_figure(plot_solution(instance, with_v2g), out / f"{instance.name}-v2g-routes.png")
    print(f"  wrote {out / f'{instance.name}-v2g.json'}")
    return 0


def cmd_validate(args) -> int:
    """Load an instance and report everything that would make it unsolvable."""
    scenario = _scenario_from_args(args, f"validate-{Path(args.instance).stem}")
    try:
        instance = instance_from_scenario(scenario)
    except (InstanceError, FileNotFoundError) as exc:
        print(f"invalid instance: {exc}", file=sys.stderr)
        return 2

    from evrp.energy import EnergyModel

    model = EnergyModel(scenario.energy, scenario.vehicle)
    print(f"{instance.name}: {instance.n_customers} customers, "
          f"{len(instance.stations)} chargers, horizon {instance.horizon:g} min")
    print(f"  total demand      : {instance.total_demand:g} "
          f"(fleet can carry {instance.fleet_size * scenario.vehicle.payload_capacity:g})")
    print(f"  usable pack       : {scenario.vehicle.usable_kwh:.1f} kWh "
          f"-> {model.full_range_km:.0f} km empty, "
          f"{model.range_km(scenario.vehicle.battery_kwh, scenario.vehicle.payload_capacity):.0f} km loaded")
    furthest = max(instance.customer_indices, key=lambda c: instance.distance[0][c])
    print(f"  furthest customer : {instance.distance[0][furthest]:.1f} km "
          f"(round trip {2 * instance.distance[0][furthest]:.1f} km)")

    issues = instance.diagnostics(scenario.energy)
    if not issues:
        print("  no blocking issues found")
        return 0
    print(f"  {len(issues)} issue(s):")
    for issue in issues[: args.max_issues]:
        print(f"    - {issue}")
    if len(issues) > args.max_issues:
        print(f"    ... and {len(issues) - args.max_issues} more")
    return 1


def cmd_env(args) -> int:
    print(json.dumps(environment_info(), indent=2))
    return 0


# -- argument parsing ------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evrp",
        description="Energy-aware vehicle routing with time windows and charging stops.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p, with_instance: bool = True):
        if with_instance:
            p.add_argument("--instance", default="data/C101.csv", help="Solomon CSV file")
        p.add_argument("--fleet", type=int, default=25, help="number of vehicles available")
        p.add_argument("--capacity", type=float, default=None,
                       help="payload capacity; ignored by compare/sensitivity/bounds, "
                            "which always use the Solomon value for the family")
        p.add_argument("--battery", type=float, default=40.0, help="usable pack size in kWh")
        p.add_argument("--reserve", type=float, default=0.10, help="fraction of pack held back")
        p.add_argument("--stations", type=int, default=6, help="number of charging stations")
        p.add_argument("--station-power", type=float, default=50.0, help="charger power in kW")
        p.add_argument("--station-strategy", default="kmeans",
                       choices=["kmeans", "grid", "random", "none"])
        p.add_argument("--peak-window", nargs=2, type=float, default=None,
                       metavar=("START", "END"),
                       help="minutes from day start during which chargers buy "
                            "energy back; unset means any time")
        p.add_argument("--station-copies", type=int, default=2,
                       help="visits allowed per station in the CP model")
        p.add_argument("--time-limit", type=float, default=30.0, help="solver budget in seconds")
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--out", default="results", help="output directory")
        p.add_argument("--no-plots", action="store_true", help="skip figure generation")

    p_solve = sub.add_parser("solve", help="solve one instance with one solver")
    add_common(p_solve)
    p_solve.add_argument("--solver", default="ortools", choices=available())
    p_solve.add_argument("--scenario", default=None,
                         help="JSON scenario file; overrides the flags above")
    p_solve.set_defaults(func=cmd_solve)

    for name, help_text in (("compare", "compare solvers over several instances"),
                            ("benchmark", "alias of compare")):
        p = sub.add_parser(name, help=help_text)
        add_common(p, with_instance=False)
        p.add_argument("--instances", nargs="+", default=list(DEFAULT_INSTANCES))
        p.add_argument("--solvers", nargs="+", default=["ortools", "savings", "insertion", "insertion-ls"])
        p.add_argument("--reference", default="ortools", help="solver used as the gap baseline")
        p.add_argument("--data-dir", default="data")
        p.set_defaults(func=cmd_compare if name == "compare" else cmd_benchmark)

    p_sens = sub.add_parser("sensitivity", help="sweep battery capacity")
    add_common(p_sens, with_instance=False)
    p_sens.add_argument("--instances", nargs="+", default=["C101", "R101"])
    p_sens.add_argument("--solvers", nargs="+", default=["ortools"])
    p_sens.add_argument("--batteries", nargs="+", type=float, default=list(DEFAULT_BATTERIES))
    p_sens.add_argument("--data-dir", default="data")
    p_sens.set_defaults(func=cmd_sensitivity)

    p_v2g = sub.add_parser("v2g", help="price vehicle-to-grid detours on a solved plan")
    add_common(p_v2g)
    p_v2g.add_argument("--solver", default="insertion-ls", choices=available())
    p_v2g.set_defaults(func=cmd_v2g, v2g=True)

    p_bounds = sub.add_parser(
        "bounds", help="measure the cost of the model's conservative energy bound"
    )
    add_common(p_bounds, with_instance=False)
    p_bounds.add_argument("--instances", nargs="+", default=["C101", "C201", "R201"])
    p_bounds.add_argument("--modes", nargs="+", default=["worst", "average", "empty"],
                          choices=["worst", "average", "empty"])
    p_bounds.add_argument("--data-dir", default="data")
    p_bounds.set_defaults(func=cmd_bounds)

    p_val = sub.add_parser("validate", help="check an instance before solving it")
    add_common(p_val)
    p_val.add_argument("--max-issues", type=int, default=15)
    p_val.set_defaults(func=cmd_validate)

    p_env = sub.add_parser("env", help="print the environment used for benchmarks")
    p_env.set_defaults(func=cmd_env)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
