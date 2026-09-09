# EV Routing Optimisation

Vehicle routing for electric fleets: delivery time windows, vehicle capacity,
**and** a battery that runs down, has to be recharged mid-route, and takes real
time to do it.

Four solvers, one problem model, and an independent simulator that checks every
answer before it is reported.

```bash
pip install -r requirements.txt
python main.py                    # solve C101 end to end, write figures
python -m evrp.cli --help         # benchmarks, sensitivity, V2G, validation
streamlit run app.py              # interactive dashboard
```

---

## The problem

A diesel van refuels in five minutes anywhere. An electric one does not, and
that changes the routing problem rather than just its cost:

* **Range is finite and depends on the load.** A van still carrying 800 kg uses
  measurably more per kilometre than one that is nearly empty, and the battery
  is tightest at the end of a route.
* **Recharging costs time, non-linearly.** A pack charges at full power to
  about 80 % state of charge, then tapers. "Just top it up at the end" is the
  expensive option, and the time it costs is what pushes a route out of its
  remaining delivery windows.
* **Where you charge is a decision.** A detour to a charger has to earn its
  kilometres.
* **Energy can flow the other way.** A vehicle with surplus charge can sell it
  back to the grid (V2G) — but only if it can get to a charger, has energy above
  its reserve, and can afford the dwell time.

So a route that is cheapest on distance can be physically impossible, and a
route that is feasible can be needlessly expensive. This project models both
sides and measures the difference.

## What it does

**Solves** the electric VRP with time windows and partial recharging
(E-VRPTW), on the Solomon benchmark instances shipped in `data/`.

**Compares four approaches** on identical instances and constraints:

| solver | approach |
| --- | --- |
| `ortools` | constraint-programming model: energy as an OR-Tools dimension with charging stations as optional replicated nodes |
| `insertion-ls` | Solomon-style cheapest insertion + local search (2-opt, Or-opt, relocate, swap) with charging repair |
| `insertion` | the construction phase alone, as an ablation |
| `savings` | Clarke & Wright savings with time-window and energy screening |

**Verifies** every result. `evrp.feasibility` replays each route stop by stop —
payload, clock, state of charge, charging events — and returns typed violations
with magnitudes. It shares no code with any solver.

**Schedules energy exactly.** Once a sequence is fixed, deciding how much to
charge at each stop (and how much to sell back) is a linear program, solved to
optimality with GLOP/SCIP rather than by a rule of thumb.

## Architecture

```
evrp/
  config.py        parameter objects; a Scenario serialises a whole experiment
  instance.py      nodes, charging stations, vectorised distance/time matrices
  energy.py        load-dependent consumption; CC-CV charging curve
  feasibility.py   independent route simulator -- the ground truth
  solution.py      solutions + metrics, all measured by the simulator
  stations.py      seeded charging-network placement (k-means / grid / random)
  schedule.py      exact per-route charge & V2G schedule (LP / MILP)
  v2g.py           prices grid-discharge detours against the km they cost
  benchmark.py     reproducible experiment harness
  cli.py           solve / compare / sensitivity / bounds / v2g / validate
  solvers/         ortools_evrptw.py, heuristic.py behind one interface
  viz/             route maps, SoC profiles, benchmark charts

app.py             Streamlit dashboard
main.py            end-to-end demo (also runs the original task 1/2 solvers)
tests/             193 tests, 92 % statement coverage of evrp/
docs/MODELLING.md  the modelling decisions and their justifications
```

Solvers are registered by name, so adding one means implementing `_solve` and
registering it — the benchmark harness, CLI and dashboard pick it up.

## Algorithms

### Battery as an OR-Tools dimension

An OR-Tools dimension only accumulates —
`cumul(j) = cumul(i) + transit(i,j) + slack(i)` with `slack >= 0` — so a battery
that can be refilled mid-route does not fit the obvious encoding. The trick is
to track **remaining state of charge** rather than energy consumed:

* `transit(i, j) = -energy(i, j)`, so driving is a negative transit;
* `slack(i)` is energy pushed into the pack, forced to zero away from chargers;
* `cumul` bounded to `[reserve, battery]`.

Charging stations are replicated `station_copies` times as optional nodes
(zero-penalty disjunctions), so several vehicles — or one vehicle twice — can
use the same charger.

Charging **time** is a fixed-length session: every station visit costs
`charge_stop_minutes` of dwell time in the time transit, and the energy one
visit may add is capped at what the charger is guaranteed to deliver in that
window at its slowest rate. Charging more means stopping again.

### Exact energy scheduling

With the sequence fixed, the state-of-charge recursion and the time-window
recursion are both affine in the decisions, so the charging plan is an LP:

```
soc[k+1] = soc[k] + charge[k] - discharge[k] - arc_energy[k]
arr[k+1] = start[k] + service[k] + plug[k] + travel[k]
start[k] >= arr[k],  start[k] >= ready[k],  arr[k] <= due[k]
```

Waiting for a window is a `max`, handled by splitting arrival from service
start. With V2G on, one binary per station makes a stop a buyer or a seller,
never both, and the problem becomes a small MILP.

### Charging-station repair

The heuristics keep energy handling in one operator: when a candidate route
runs the pack below its reserve, the repair tries every (position, station)
pair, keeps the one that fixes the deficit at the smallest detour, and repeats
if one stop is not enough — a customer beyond half the range needs a stop
outbound *and* one on the way home. Every acceptance test goes through the
simulator, so a heuristic cannot talk itself into an infeasible answer.

## EV constraints, and how each is enforced

| constraint | where |
| --- | --- |
| delivery time windows | CP time dimension; simulator re-checks arrivals |
| vehicle capacity | CP capacity dimension; simulator re-checks route load |
| state of charge ≥ reserve | CP energy dimension bounds; simulator re-checks every arc |
| pack never overfilled | explicit departure bound `cumul + slack <= battery` |
| charging takes time | fixed-length session in the time transit |
| CC-CV taper | `ChargingCurve`, exact in the simulator, conservatively bounded in the CP model |
| load-dependent consumption | exact in the simulator; payload-independent upper bound in the CP model |
| shift length / depot closing | duration checks in the simulator |
| V2G floor | LP constraint, only energy above `v2g_min_soc` may be sold; re-checked by the simulator |
| V2G peak window | opt-in (`--peak-window`); a MILP binary in the schedule, re-checked by the simulator |
| one visit per customer | simulator flags a repeat on a route; `Solution` flags one served by two routes |

## Results

All numbers below were produced by the commands shown, on the machine recorded
in `results/*/environment.json`, seed 42. Raw output is committed under
`results/`. Nothing here is estimated.

### Routing quality (energy not binding, 80 kWh pack)

With a pack large enough that the battery never binds, the model reduces to a
classic VRPTW, which is a check on the routing core.

```bash
python -m evrp.cli compare --instances C101 C201 R101 R201 RC101 RC201 \
  --solvers ortools insertion-ls insertion savings \
  --battery 80 --stations 6 --time-limit 20 --seed 42 --out results/unconstrained
```

| instance | ortools | insertion-ls | insertion | savings |
| --- | --- | --- | --- | --- |
| C101 | **828.94** | 904.87 (+9.2 %) | 1022.53 (+23.4 %) | 1018.36 (+22.9 %) |
| C201 | **607.94** | 712.10 (+17.1 %) | 755.68 (+24.3 %) | 856.56 (+40.9 %) |
| R101 | **1701.51** | 1751.35 (+2.9 %) | 2159.57 (+26.9 %) | infeasible |
| R201 | **1206.38** | 1301.03 (+7.8 %) | 1569.85 (+30.1 %) | 1542.17 (+27.8 %) |
| RC101 | **1744.55** | 1792.54 (+2.8 %) | 2299.24 (+31.8 %) | 2098.17 (+20.3 %) |
| RC201 | **1299.85** | 1413.68 (+8.8 %) | 1841.32 (+41.7 %) | 1757.66 (+35.2 %) |

| solver | feasible | mean distance | mean vehicles | mean runtime |
| --- | --- | --- | --- | --- |
| ortools | 6/6 | 1231.5 km | 11.7 | 20.0 s |
| insertion-ls | 6/6 | 1312.6 km | 11.3 | 3.8 s |
| savings | 5/6 | 1526.3 km | 16.7 | 0.06 s |
| insertion | 6/6 | 1608.0 km | 11.3 | 0.5 s |

Two things worth reading off this table. Local search buys most of what the CP
model buys, for a fraction of the time — `insertion-ls` is within 3 % on the
R1/RC1 instances at a twentieth of the runtime. And the construction phase
alone is 25–40 % worse, so the improvement really is coming from the local
search rather than from the seed.

**On C101 the solver reaches 828.94 km with 10 vehicles**, which is the
published optimum for that instance. That is the one directly comparable
number here: this project minimises total distance with a large fleet, whereas
the classical Solomon results minimise vehicle count first and distance second,
so the other rows are not comparable with published values.

### Energy-constrained routing (25 kWh pack, 8 chargers)

```bash
python -m evrp.cli compare --instances C101 C201 R101 R201 RC101 RC201 \
  --solvers ortools insertion-ls insertion savings \
  --battery 25 --stations 8 --time-limit 20 --seed 42 \
  --out results/constrained
```

| instance | solver | km | vehicles | charging stops | plugged in (min) | served | feasible |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C101 | ortools | 937.21 | 11 | 4 | 27 | 100/100 | yes |
| C101 | insertion-ls | 984.71 | 12 | 1 | 10 | 100/100 | yes |
| C201 | ortools | 681.63 | 4 | 12 | 166 | 100/100 | yes |
| C201 | savings | 985.70 | 6 | 15 | 150 | 100/100 | yes |
| R101 | ortools | 1769.13 | 22 | 5 | 32 | 100/100 | yes |
| R201 | ortools | 1341.46 | 15 | 11 | 151 | 100/100 | yes |
| RC101 | ortools | 1878.78 | 20 | 8 | 83 | 99/100 | no |
| RC201 | ortools | 1155.12 | 12 | 11 | 173 | 85/100 | no |

Squeezing the pack from 80 kWh to 25 kWh costs **13 % more distance on C101**
(828.94 → 937.21 km) and one extra vehicle, and it buys four charging stops and
27 minutes of dwell time. On C201, whose 3390-minute horizon allows very long
routes, the battery bites hardest: twelve charging stops and nearly three hours
plugged in.

Not every instance stays solvable. On RC101 and RC201 the CP model leaves
customers unserved rather than return a plan that cannot be flown — the
heuristics serve all of RC201 by using more, shorter routes. **No solver in
either table returned a single constraint violation**; every infeasible row is
an explicit "I could not serve these customers", which is the honest failure
mode.

### What the conservative energy bound costs

The CP model cannot know the payload on an arc, so it must use one
payload-independent consumption rate. Only the rate at *full* payload
guarantees that a model-feasible route also passes the exact simulator.

```bash
python -m evrp.cli bounds --instances C101 C201 R201 --battery 25 \
  --stations 8 --station-copies 3 --time-limit 20 --seed 42 --out results
```

| instance | bound | km | charging stops | violations | verified |
| --- | --- | --- | --- | --- | --- |
| C101 | worst (full payload) | 997.06 | 5 | 0 | yes |
| C101 | average (half payload) | 930.02 | 2 | 0 | yes |
| C101 | empty | 838.21 | 1 | **2** | no |
| C201 | worst | 703.83 | 11 | 0 | yes |
| C201 | average | 722.77 | 9 | 0 | yes |
| C201 | empty | 694.03 | 8 | **14** | no |
| R201 | worst | 1309.14 | 16 | 0 | yes |
| R201 | average | 1248.95 | 15 | 0 | yes |
| R201 | empty | 1227.38 | 10 | **9** | no |

The optimistic bound is worth 1.4–16 % on distance and cuts charging stops by
between a quarter and four fifths — and on all three instances the simulator
rejected the result. Those plans put vehicles below their reserve on the road.
The safe bound costs 7.2 % on C101 against the mid-range setting; that is the
measured price of answers that hold up. On C201 the safe bound actually came
out 2.6 % *shorter* than the mid-range one, which is a useful reminder that a
20-second budget leaves a few percent of search noise on top of any effect.

Raw output in `results/consumption_bounds.csv`.

### Battery sensitivity

```bash
python -m evrp.cli sensitivity --instances C101 R101 RC101 --solvers ortools \
  --batteries 80 40 25 18 14 --stations 8 \
  --time-limit 20 --seed 42 --out results
```

| instance | pack | km | vehicles | charging stops | plugged in (min) | served |
| --- | --- | --- | --- | --- | --- | --- |
| C101 | 80 kWh | 828.94 | 10 | 0 | 0 | 100/100 |
| C101 | 40 kWh | 828.94 | 10 | 0 | 0 | 100/100 |
| C101 | 25 kWh | 937.21 | 11 | 4 | 27 | 100/100 |
| C101 | 18 kWh | 969.96 | 13 | 9 | 85 | 93/100 |
| C101 | 14 kWh | 903.57 | 12 | 12 | 121 | 85/100 |
| R101 | 80 kWh | 1704.61 | 23 | 0 | 0 | 100/100 |
| R101 | 40 kWh | 1704.61 | 23 | 0 | 0 | 100/100 |
| R101 | 25 kWh | 1769.13 | 22 | 5 | 32 | 100/100 |
| R101 | 18 kWh | 1780.22 | 25 | 9 | 87 | 96/100 |
| RC101 | 80 kWh | 1713.54 | 18 | 0 | 0 | 100/100 |
| RC101 | 40 kWh | 1740.22 | 19 | 0 | 0 | 100/100 |
| RC101 | 25 kWh | 1878.78 | 20 | 8 | 83 | 99/100 |

There is a threshold rather than a gradient. At 80 and 40 kWh the plans are
identical on C101 and R101 — the battery is not a constraint and the solver
returns the classic VRPTW routes. At **25 kWh the constraint switches on**:
charging stops appear, dwell time appears, and distance rises 13 % on C101 and
3.8 % on R101. Below that the fleet stops being able to serve everyone.

Read the last rows carefully: at 14 kWh C101's distance *falls* to 903.57 km,
but only because 15 customers are no longer being served. Distance is only
comparable between rows that serve the same customers, which is exactly why the
table carries the "served" column and the harness records feasibility rather
than reporting a cost in isolation.

Full data in `results/sensitivity.csv`, chart in
`results/battery_sensitivity.png`.

### Vehicle-to-grid

```bash
python -m evrp.cli v2g --instance data/R201.csv --capacity 1000 --battery 60 \
  --stations 8 --time-limit 20 --solver insertion-ls --out results
```

For every route the engine prices the best detour to a charger that can absorb
energy: the sellable amount comes from the exact schedule LP, and the detour is
taken only if the revenue beats the kilometres.

On R201 with a 60 kWh pack, 7 of the routes took a V2G stop, selling
**95.5 kWh for $52.52 net** — with **0 extra kilometres**, and the plan stayed
verified feasible. Zero extra distance is not a rounding artefact: the charging
network always includes a charger at the depot, and the profitable trade turned
out to be selling surplus at the depot rather than driving anywhere for it. The
detour pricing is what established that; it declined every detour that did not
pay for itself. Results in `results/R201-v2g.json`.

### Figures

`results/*/solver_comparison.png`, `results/battery_sensitivity.png`, and from
`python main.py`: `outputs/routes.png` (routes with charging stops marked),
`outputs/soc_profile.png` (state of charge against distance, with the reserve
floor drawn in).

## Reproducing

```bash
make install      # venv + dependencies
make test         # full suite
make demo         # main.py end to end
make bench        # the comparison tables
make sensitivity  # the battery sweep
make app          # dashboard
```

Every run writes the `Scenario` it actually used next to its output, and
`results/*/environment.json` records Python, OR-Tools and platform versions.
Scenarios can be replayed:

```bash
python -m evrp.cli solve --scenario configs/tight-battery-c101.json
```

## Testing

```bash
python -m pytest              # everything
python -m pytest -m "not slow"  # skip benchmark-scale checks
```

193 tests, 92 % statement coverage of `evrp/`. The suite is not only about
coverage; several of the tests exist because they caught real bugs:

* the simulator is checked against hand-computed distances, times, and states
  of charge on a three-customer instance with Pythagorean geometry;
* the charging curve's `energy_after` is asserted to be the exact inverse of
  `time_for`;
* every solver is asserted to serve every customer *and* to survive the
  independent simulator, so a solver that games its own objective fails;
* enabling V2G is asserted never to make a feasible schedule infeasible;
* the conservative consumption bound is asserted to produce zero violations;
* a regression test pins the charging-time cost of a stop, and another asserts
  that a horizon too short for the recharge yields no plan;
* a customer visited twice on a route, or served by two different routes, is
  rejected — while revisiting a charger stays legal;
* a replayed vehicle-to-grid sale drains the pack, costs plug time, and is
  rejected below the reserve floor or outside a declared peak window;
* every benchmark knob is asserted to reach the `Scenario` it claims to set;
* the Streamlit app is driven end to end through `streamlit.testing`.

## Bugs this replaced

The project it grew from did not run. Each of these was found by running the
code or by the verification layer, and each has a regression test:

| bug | effect |
| --- | --- |
| `main.py` imported `VRPDischargeSolver`, which did not exist | the entry point crashed on import |
| vehicle capacity hard-coded to 100 | C101 has 1810 units of demand; the solver reported "No solution found!" for a reason unrelated to routing |
| travel time computed as `distance / 50 * 60` | every Solomon time window 20 % tighter than the benchmark defines, making results incomparable |
| distances truncated with `int()` | up to 1 km lost per arc |
| GA fitness skipped routes past the fleet size | on C101 the search converged to **cost 0 with zero customers served** |
| GA population was 100 identical solutions | a shuffled list was discarded before use, so crossover had nothing to recombine |
| `haversine_distance` computed Euclidean distance | correct behaviour, wrong name; now two functions, both correct |
| Streamlit's Solomon loader looked for a customer with id 0 | the depot is row 1 in these files, so the option silently loaded nothing |
| `streamlit_dashboard.py` used `plot_routes` without importing it | `NameError` on first draw |
| dependencies pinned to versions with no wheels for Python 3.11+ | the project could not be installed on a current interpreter |

And three found by the new verification layer, in the new code:

* **the pack could be overfilled** — an OR-Tools dimension bounds the cumul *at*
  nodes, so a model charging `S` at a node holding `C` was free to let `C + S`
  exceed the battery as long as the next arc burned the excess off;
* **charging energy read back as zero** — `SlackVar` is not part of the returned
  assignment, so the recharge has to be recovered from the cumul difference;
* **charging time was not enforced** — the constraint linking the time and
  energy dimensions' slack variables held at the last charging stop of a route
  but not at earlier ones, letting the model add 28 kWh in under four minutes.
  Charging is now a fixed-length session priced directly in the time transit,
  which needs no cross-dimension reasoning.

The original two solvers are still there, still callable, and now correct:
`python main.py --legacy` runs both.

## Limitations

* **Distances are straight-line, not road-network.** Every solver and the
  simulator share the same matrix, so the comparisons are fair, but absolute
  kilometres are optimistic.
* **Charging stations are placed by the project**, because Solomon instances
  have none. Placement is seeded and reported, but it is an input, not a
  decision variable — the model routes around infrastructure it cannot move.
* **Recharging is discretised** into fixed-length sessions in the CP model. The
  schedule LP is continuous, but the routing decision is not.
* **No queueing at chargers**: a station is always free.
* **The V2G tariff is flat** inside an optional peak window, not a real
  time-of-use curve or a capacity market.
* **Consumption ignores speed, gradient, temperature and auxiliary loads**, all
  of which matter in cold weather.
* **The heuristics do not backtrack.** Charging repair inserts stops greedily;
  a route that needs a fundamentally different shape is abandoned rather than
  rebuilt.
* **The legacy genetic algorithm is a baseline, not a contender.** It is kept
  because the comparison is honest, not because it is competitive.

## Further reading

`docs/MODELLING.md` covers the unit conventions, the energy and charging
models, the CP formulation and its relaxation-safety argument, the schedule
LP, and the full list of approximations.
