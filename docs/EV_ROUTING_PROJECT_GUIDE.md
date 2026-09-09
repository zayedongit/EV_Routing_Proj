# EV Routing Project — Understanding & Interview Guide

Written from the **actual code** on branch `autonomous-resume-upgrade`. Every
number, path and behaviour below was checked against the source or the committed
files in `results/`. Where the code and the docstrings/README disagree, this
guide states what the **code** does.

---

## 1. Project in one page

**What it is.** A Python system that plans delivery routes for a fleet of
**electric** vans and then independently verifies that those plans are physically
possible. It solves the same problem four ways so the approaches can be compared
on identical data.

**The real problem.** A depot has 100 parcels; each customer must be visited
inside a time window; each van has a payload limit *and* a battery. Which van
visits whom, in what order, and where does it stop to charge?

**Why EVs are different**

| Diesel VRP | This project (E-VRP) |
| --- | --- |
| range effectively unlimited | range = battery ÷ consumption; finite |
| refuelling ignored | charging is a *decision* (where, how much) |
| refuelling time ≈ 0 | a charging stop costs 30 min of schedule |
| fuel use ≈ constant/km | consumption rises with payload on board |
| — | energy can be sold back to the grid (V2G) |

**What the system can do**

- Load Solomon instances (`data/*.csv`) and build a routing problem.
- Generate a charging network (Solomon files have none) with seeded k-means /
  grid / random placement.
- Solve with four solvers: an OR-Tools CP model and three heuristics.
- Re-simulate every route independently and report exact violations.
- Run reproducible benchmarks and a battery sweep → CSV / Markdown / PNG in
  `results/`.
- Price vehicle-to-grid detours with a small LP/MILP.
- Show all of it in a Streamlit dashboard.

**Tiny example.** Depot `(0,0)`, one customer `(90,0)`, one charger `(50,0)`.
Pack 10 kWh, 0.1 kWh/km ⇒ 100 km range. The 180 km round trip is impossible, so
the solver inserts the charger twice — outbound and homebound — and the
simulator confirms SoC never drops below the reserve. This is the
`_corridor_instance` fixture in `tests/test_solvers.py`.

---

## 2. Problem statement and motivation

**VRP.** Given a depot, customers and a fleet, find routes (depot → customers →
depot) visiting every customer once at minimum cost. Generalises TSP; NP-hard.

**VRPTW.** Each customer has `[ready_time, due_time]` and a `service_time`.
Arriving early means waiting; arriving late is a violation. Order and timing now
interact, which is what makes it hard.

**What EVs add** — three coupled resources:

1. **Battery (SoC).** Every km costs energy; SoC must stay above a *reserve*
   (`reserve_soc`, default 10 %). Arriving at 0 kWh is a breakdown, not a
   solution.
2. **Charging.** Energy can only be added at stations, and adding it costs time
   that competes with the delivery windows. Charging is non-linear: fast to
   ~80 %, then a taper.
3. **Payload coupling.** Heavier load ⇒ more kWh/km, and a van sheds load as it
   delivers, so consumption falls along the route.

**Why V2G is here.** A van with surplus charge is a battery on wheels. Selling
that surplus turns "should I detour to a charger?" into an economic question:
revenue minus the cost of the extra kilometres.

**Core vs optional — be precise:**

| Part | Status |
| --- | --- |
| VRPTW + capacity | core, fully implemented |
| Battery / SoC constraint | core, fully implemented |
| Charging stops + charging time | core, implemented with a discretisation (§7) |
| Independent verification | core, fully implemented |
| Benchmarking / sensitivity | core, implemented |
| V2G / grid discharge | **optional extension**, post-processing only (§9) |
| Time-of-use peak windows | in code but **unreachable** in any default run (§14) |

---

## 3. End-to-end system flow

```
 data/C101.csv   (id, x, y, demand, ready, due, service)
        │  evrp/instance.py :: read_solomon_frame → normalise_columns
        ▼
 canonical DataFrame (7 numeric-validated columns)
        │  evrp/instance.py :: load_solomon
        ▼
 Node objects   [0]=depot, [1..n]=customers
        │  evrp/stations.py :: generate_stations   (seeded k-means)
        ▼
 + ChargingStation nodes [n+1 ..]
        │  evrp/instance.py :: Instance.build
        ▼
 Instance = nodes + NumPy distance & travel-time matrices + VehicleSpec
        │◄─ evrp/config.py :: Scenario(VehicleSpec, EnergyConfig,
        │                              ChargingConfig, SolverConfig)
        ▼
 ┌──────────── evrp/solvers/  (registry: create("ortools") …) ─────────────┐
 │ ortools_evrptw.py               heuristic.py                            │
 │  CP model, 4 dimensions:         savings / insertion / insertion-ls     │
 │   Distance, Capacity,            build greedily, repair energy by       │
 │   Time, Energy                   inserting chargers; a candidate is     │
 │                                  accepted only if the SIMULATOR agrees  │
 └────────────────────────┬────────────────────────────────────────────────┘
                          │ routes: list[list[int]] (+ charge plans)
                          ▼   evrp/solvers/base.py :: Solver.solve
                          ▼   evrp/solution.py :: Solution.evaluate
        evrp/feasibility.py :: simulate_route   ← INDEPENDENT VERIFIER
          replays payload, clock, SoC, charging → RouteSimulation
          + list[Violation]  (capacity | time_window | battery | duration | …)
                          │
        ┌─────────────────┼──────────────────────┐
        ▼                 ▼                      ▼
 evrp/benchmark.py   evrp/v2g.py+schedule.py   evrp/viz/
 CSV/MD/env.json     LP-priced V2G detours     route map, SoC plot
        └──────► evrp/cli.py  /  main.py  /  app.py (Streamlit) ◄──────┘
```

---

## 4. Understand the data

`data/` holds **12 Solomon CSVs**; benchmarks use **6**: C101, C201, R101,
R201, RC101, RC201. Each file has a header plus **101 rows** — row 1 is the
**depot**, rows 2–101 are the **100 customers**. Header spellings like
`CUST NO.`, `XCOORD.`, `DUE DATE` are mapped by `_COLUMN_ALIASES` in
`evrp/instance.py`.

| Column | Meaning here |
| --- | --- |
| `CUST NO.` | file row id; **not** the node index — customers are renumbered 1..100 |
| `XCOORD.`, `YCOORD.` | planar coordinates, read as **km** |
| `DEMAND` | parcel weight in **kg**, consumes payload capacity |
| `READY TIME` / `DUE DATE` | time window in **minutes** from day start |
| `SERVICE TIME` | minutes spent at the customer |

| Instance | Total demand | Horizon (min) | Service | Solomon capacity |
| --- | --- | --- | --- | --- |
| C101 | 1810 | 1236 | 90 | 200 |
| C201 | 1810 | 3390 | 90 | 700 |
| R101 | 1458 | 230 | 10 | 200 |
| R201 | 1458 | 1000 | 10 | 1000 |
| RC101 | 1724 | 240 | 10 | 200 |
| RC201 | 1724 | 960 | 10 | 1000 |

**Family letters, only as used here.** `C` = clustered customers, `R` = random,
`RC` = mixed; the digit is the class — `x1` short horizon / tight windows, `x2`
long horizon / big capacity. The project uses this **only** to pick vehicle
capacity: `SOLOMON_CAPACITY` in `evrp/benchmark.py` maps `C1/R1/RC1→200`,
`C2→700`, `R2/RC2→1000`. That matters: C101 needs 1810 units of capacity in
total, so a fleet of 100-unit vans can *never* serve it — one of the original
bugs.

**Vehicle capacity** is not in the data; it comes from
`VehicleSpec.payload_capacity` (default 200) or `solomon_capacity()`.

**Charging stations are not in the data either.** `evrp/stations.py ::
generate_stations` synthesises them: station 0 always **on the depot**, the rest
at k-means centroids of the customer coordinates (k-means++ seeding + Lloyd
iterations, hand-written in NumPy — no scikit-learn). Defaults: 6 stations,
50 kW. **This is an input we invented, not benchmark data.** Say so.

---

## 5. The EV model

| Concept | Code |
| --- | --- |
| pack size | `VehicleSpec.battery_kwh` (default **40 kWh**) |
| reserve | `VehicleSpec.reserve_soc` (default **0.10**) → `min_soc_kwh` |
| start SoC | always **full** (`soc = battery_kwh` at the top of `simulate_route`) |
| consumption rate | `EnergyModel.rate_kwh_per_km(payload)` = `(0.22 + 0.00008·payload)·regen_efficiency` |
| arc energy | `EnergyModel.consumption(distance_km, payload_kg)` |
| range | `EnergyModel.range_km(soc, payload)` = `(soc − reserve)/rate` |
| distance / travel time | `Instance.distance` (NumPy, Euclidean by default); `travel_time = distance / speed_km_per_min` |
| charging | `ChargingCurve` in `evrp/energy.py` |

**Numbers to remember.** Empty van 0.22 kWh/km; a 1000 kg payload adds
0.08 kWh/km (≈ +36 %). A 40 kWh pack with 10 % reserve = 36 usable kWh ⇒ ≈164 km
empty, ≈133 km at 200 kg.

**Speed convention.** `speed_km_per_min = 1.0` ⇒ travel time equals Euclidean
distance. That is the Solomon convention and is what makes results comparable
with published ones (km + minutes ⇒ 60 km/h). The original code divided by 50
and multiplied by 60, silently tightening every window by 20 %.

**Payload profile.** `payload_on_arc[k]` starts at the route's total demand and
decreases at each delivery, so the arc into the first customer carries the whole
load and the arc home carries ~0. This is a **delivery-only** model; no pickups.

**Charging curve.** `linear` = constant power. `piecewise` (default) = full
power `P` up to `cc_end_soc` (80 % of pack), then `taper_power_fraction · P`
(0.45·P). `P = min(station_power_kw, vehicle.onboard_charge_power_kw)` — both
default 50 kW. `fixed_time_min` (2 min) is a plug-in overhead.
`time_for(from,to)` gives minutes; `energy_after(soc, minutes)` is its exact
inverse (asserted by a test).

*Honest note:* `ChargingCurve.segments()` and `marginal_power_kw()` exist and are
tested but **no production code calls them**. The docstring saying `segments()`
is what the schedule LP uses is out of date — the LP uses a single conservative
power (§9).

---

## 6. Routing algorithms

### OR-Tools in plain terms

OR-Tools is Google's open-source optimisation toolkit; its **routing library**
is purpose-built for VRPs. You declare the problem — arc costs, and resources
that accumulate along a route within bounds — and it builds an initial solution
with a construction heuristic, then improves it with local search until a time
limit expires. It does **not** prove optimality here.

The core concept is a **dimension**: a quantity tracked along a route, with

```
cumul(next) = cumul(i) + transit(i, next) + slack(i),     slack(i) ≥ 0
```

### 6.1 `ortools` — the CP model
*`evrp/solvers/ortools_evrptw.py :: ORToolsEVRPTWSolver`*

**Why:** the strongest solver here, and the reference the heuristics are
measured against.

| Dimension | Transit | Bound |
| --- | --- | --- |
| `Distance` | arc km × 100 (centi-km) | arc cost = the objective |
| `Capacity` | node demand | `payload_capacity` per vehicle |
| `Time` | travel + service (+ a charging session at stations) × 10 (deci-min) | node `[ready, due]`; depot horizon |
| `Energy` | **−**(consumption × 1000, Wh) | cumul ∈ `[reserve_wh, battery_wh]` |

**The battery trick.** A dimension only accumulates, so "energy consumed" can't
be reset at a charger. Instead track **remaining SoC**: driving is a *negative*
transit, and `slack(i)` at a station node is the energy added. Slack is forced
to `0` at every non-station node, so energy can only appear at a charger.

Stations are **replicated** `station_copies` times (default 2), each replica
made optional by `AddDisjunction([index], 0)` — zero penalty, so skipping is
free. Replication lets one vehicle charge twice, or two vehicles share a
charger. Customers also get a disjunction, but with `drop_penalty = 1e6`, so
dropping one is a last resort rather than a crash.

**Strategy portfolio.** `_solve` tries `PATH_CHEAPEST_ARC`, then
`PARALLEL_CHEAPEST_INSERTION`, then `SAVINGS`, keeping whichever serves the most
customers and stopping early once one serves everyone. `PATH_CHEAPEST_ARC` builds
arc by arc and, on a tight battery, drives to the far customer before realising
it can't get home. **Reported runtime covers every attempt** — hence rows showing
40 s or 60 s against a 20 s limit.

**In:** `Instance` + `SolverConfig`. **Out:** routes + a `charge_plans` dict per
route. **+** best quality, all constraints handled jointly. **−** slowest; needs
a payload-independent consumption bound (§7); charging discretised.

### 6.2 `savings` — Clarke & Wright
*`evrp/solvers/heuristic.py :: SavingsSolver`*

One route per customer, then merge greedily by *saving* `d(0,i)+d(0,j)−d(i,j)` —
the depot legs avoided. A merge is accepted only if the merged route **passes
the simulator** (charging repair included).

- **+** extremely fast (~0.06 s on 100 customers).
- **−** greedy, no improvement phase; worst quality of the three; can leave
  customers unrouted when it overruns the fleet size.

### 6.3 `insertion` — Solomon-style construction
*`InsertionLocalSearchSolver(local_search=False)`*

Seed a route with the customer whose window closes earliest (ties by distance
from depot — the classic Solomon I1 rule), then repeatedly insert the
customer/position with the smallest detour `d(prev,c)+d(c,next)−d(prev,next)`,
accepting only feasible candidates. When nothing fits, open a new route.

- **+** fast, respects windows by construction.
- **−** purely greedy — it exists as the **ablation baseline** showing how much
  quality comes from the improvement phase rather than the seed.

### 6.4 `insertion-ls` — construction + local search

Same construction, then first-improvement local search over four classical
neighbourhoods until nothing improves or the budget expires:

| Move | Scope |
| --- | --- |
| 2-opt | reverse a segment inside one route |
| Or-opt | move a chunk of 1–3 stops within a route |
| relocate | move one customer to another route |
| swap | exchange two customers between routes |

Every candidate goes through a cached `_RouteEvaluator` (the cache matters — the
same routes are re-tested thousands of times).

- **+** near-CP quality at a fraction of the runtime (+2.8 % on RC101 in the
  measured run, ~2 s vs 20 s).
- **−** no restarts or perturbation, cannot escape a local optimum; charging
  repair is greedy and never backtracks.

*Honest note:* `_construct` takes an `rng` it never uses, and `max_no_improve` is
stored but never read. The heuristics are fully deterministic, so
`SolverConfig.seed` in practice only affects **station placement**.

---

## 7. Battery / charging logic

**State of charge.** In `evrp/feasibility.py` the van leaves the depot full; on
each arc `soc -= consumption(distance, payload_on_that_arc)`. If
`soc_arrival < min_soc_kwh` a `BATTERY` violation records the exact kWh shortfall.
**Charging stations** are ordinary nodes tagged `NodeKind.STATION` with zero
demand and zero service time; their cost is the charging dwell.

**How much is charged** — the `charge_policy` argument to `simulate_route`:

| Policy | Behaviour | Used by |
| --- | --- | --- |
| `minimal` | add just enough to reach the next station or the depot with the reserve intact | heuristics; the default |
| `full` | charge to 100 % | tests, UI |
| `none` | pass through without charging | pricing detours |
| `explicit` | obey `charge_plan[position]`, otherwise charge nothing | replaying the CP model's own plan |

`minimal` is exact, computed by a backward pass (`need_after`) over the route.
**Charging time** is `ChargingCurve.time_for(base, target)` — the piecewise CC-CV
curve plus the 2-minute overhead — added to the departure time, so it genuinely
competes with the windows.

**Inside the CP model, charging is a fixed-length session.** A station visit
adds `charge_stop_minutes` (default 30) to the *time transit*, and the energy
slack at that node is capped at what the charger is guaranteed to deliver in
that window **at its slowest (taper) rate**:

```
quantum_kWh = taper_power_kW × (charge_stop_minutes − fixed_time_min) / 60
```

Since the real curve is at least that fast everywhere, the session always
finishes inside the time it paid for; charging more means another replica and
another session.

### Bugs found and fixed

**Pre-existing (original project):**

| Bug | Why it mattered |
| --- | --- |
| `main.py` imported `VRPDischargeSolver`, which never existed | the entry point crashed — the project did not run at all |
| vehicle capacity hard-coded to 100 | C101 needs 1810 units; "No solution found!" for a reason unrelated to routing |
| travel time = `distance / 50 * 60` | 1.2× the Solomon convention ⇒ every window 20 % tighter, results incomparable |
| distances truncated with `int()` | ~1 km of systematic error per arc |
| GA fitness skipped routes past the fleet size | serving **nobody** scored a perfect 0 — the search optimised for doing nothing |
| GA built 100 identical initial solutions | a shuffled list was discarded before use, so crossover had nothing to recombine |
| `haversine_distance` computed Euclidean distance | right behaviour, wrong name — a trap for the next reader |

**In the new CP model, caught by the verifier:**

1. **The pack could be overfilled.** The dimension bounds the cumul *at* nodes,
   so charging `S` at a node holding `C` was free to let `C+S` exceed the battery
   as long as the next arc burned off the excess. Fix: an explicit departure
   bound `CumulVar(i) + SlackVar(i) ≤ battery_wh`.
2. **Charged energy read back as zero.** `SlackVar` isn't in the returned
   OR-Tools assignment, so the reported charging plan was empty and the simulator
   then replayed the route with no charging and rejected it. Fix: recover the
   recharge from the cumul difference,
   `slack(i) = cumul(next) − cumul(i) − transit(i,next)`.
3. **Charging time was not enforced.** The first design tied the *time*
   dimension's slack to the *energy* dimension's slack. In the returned solutions
   that constraint held at a route's last charging stop but not at earlier ones —
   the model added 28 kWh in under four minutes and the simulator flagged a batch
   of late deliveries. It reproduced on a four-node instance. Fix: drop the
   cross-dimension constraint and use the fixed-length session above, which is an
   ordinary transit and cannot be silently ignored.
4. **Charge plans desynchronised from routes.** Pruning idle station stops could
   empty a route; routes and plans were then filtered independently, shifting
   every plan by one. Fix: filter them as pairs in `Solver.solve`.

Bug 3 is the most defensible story: *the OR-Tools internals were never
root-caused — the behaviour was reproduced, designed around, and pinned with a
regression test.* Say that honestly.

**Charging repair for the heuristics** (`repair_with_charging`): if a candidate
has *only* battery violations, try every (position, station) pair; take the
cheapest insertion that makes it fully feasible, otherwise take the one that
most reduces the total shortfall and repeat, up to `max_inserts = 3`. Two stops
are often needed — one outbound, one homebound.

---

## 8. Feasibility verification

### Why it exists

**"The solver does not grade its own homework."** A model expressed in OR-Tools
dimensions is easy to get subtly wrong: an off-by-one in a callback, a unit
mismatch in a scaled integer, a constraint that silently doesn't bind. If the only
source of truth is the solver's own bookkeeping, a broken model reports a
beautiful impossible answer — the original GA converged to "cost 0" by serving
nobody, because its fitness said that was perfect.

`evrp/feasibility.py :: simulate_route` shares **no code** with any solver: it
takes a route as a plain list of node indices and physically replays it.

### What it checks

| Check | Violation kind |
| --- | --- |
| route load ≤ payload capacity | `CAPACITY` |
| arrival ≤ `due_time` at every customer (early ⇒ wait) | `TIME_WINDOW` |
| the same at a charging station | `STATION_WINDOW` |
| SoC ≥ reserve on arrival at every stop **and** back at the depot | `BATTERY` |
| return before the depot closes | `DURATION` |
| route within `max_route_duration`, if set | `DURATION` |
| node index in range | `BAD_NODE` |

Each violation carries the offending node and the **magnitude** (kWh short,
minutes late, kg over).

Coverage is checked one level up: `Solution.feasible` in `evrp/solution.py` is
`n_violations == 0 AND customers_served == customers_total AND routes non-empty`.

Every solver's `solve()` (`evrp/solvers/base.py`) calls `Solution.evaluate`
before returning, so **no result reaches a report, a CSV or the dashboard
without passing through the verifier**. The heuristics go further and use the
simulator as their *acceptance test* during search, so they cannot construct an
infeasible route at all.

### Why it makes the project trustworthy

- It caught four real bugs in the new CP model (§7) that the solver considered
  perfectly valid.
- "Infeasible" becomes an *explicit, itemised* outcome: every benchmark row
  carries `violations` and `customers_served`.
- It lets aggressive modelling shortcuts be **measured** rather than trusted —
  see the consumption-bound experiment (§10E).

**Known gaps in the verifier — say these:**

- It does **not** detect a customer visited twice; `customers_served` counts a
  set. A test asserts no duplicates, but there is no runtime check.
- It does **not** enforce `vehicles_used ≤ fleet_size`; the solvers do that.
- It does **not** model V2G discharge — `Stop.discharged_kwh` is always `0.0`
  (§9).

---

## 9. V2G / grid discharge

**V2G** = vehicle-to-grid: a plugged-in van pushes energy *out* of its pack into
the grid. **Grid discharge** is the same thing seen from the grid. A fleet does
it because electricity is worth more at peak than the operator paid.

**How this project models it.** As a **post-process on an already solved plan**,
not part of the routing objective (`evrp/v2g.py`):

1. `best_v2g_detour` enumerates every (position, station) pair, computing the
   detour `d(a,s)+d(s,b)−d(a,b)`, cheapest first, capped at `max_candidates`
   (default 12).
2. Each candidate is first run through the **simulator**; infeasible ⇒ discard.
3. Then the **LP/MILP** (`evrp/schedule.py :: optimise_schedule`) decides how
   many kWh can actually be sold.
4. Accept only if
   `net_gain = v2g_revenue − energy_cost − detour_km × distance_cost_per_km > 0`.
5. `apply_v2g` repeats per route and returns a new `Solution` plus a `V2GReport`.

**Revenue** = `discharged_kWh × v2g_price` (default \$0.55/kWh), against
\$0.18/kWh bought and \$0.25/km for the detour. **Detour distance matters**
because without pricing the kilometres, "always detour to sell" would look free;
the module's job is to *decline* detours that don't pay.

**What the LP/MILP does.** With the sequence fixed, the physics are linear:

```
soc[k+1] = soc[k] + charge[k] − discharge[k] − arc_energy[k]
arr[k+1] = start[k] + service[k] + plug[k] + travel[k]
start[k] ≥ arr[k],  start[k] ≥ ready[k],  arr[k] ≤ due[k]
plug[k]  ≥ charge[k]·60/P + fixed_time,   plug[k] ≥ discharge[k]·60/P
```

Waiting for a window is a `max`, handled by splitting arrival from service
start. Objective: maximise `v2g_price·Σdischarge − energy_price·Σcharge`, minus
a tiny tie-break on finish time. With V2G on, **one binary per station** forces
a stop to be either a buyer or a seller — without it the LP round-trips energy
through a single plug whenever the sell price beats the buy price, which no real
charger allows. Backend: GLOP (pure LP) or SCIP/CBC (with binaries).

**Measured** (`results/R201-v2g.json`; R201, 60 kWh pack, 8 stations,
`insertion-ls` baseline): 7 routes took a V2G stop, **95.5 kWh sold for \$52.52
net, 0 extra km**, plan still verified feasible. Zero extra distance is not a
rounding artefact — station 0 sits *on the depot*, so the profitable trade was
selling surplus at the depot. Honest reading: **the detour machinery ran and
selected the free option.**

**Limitations:**

- Greedy post-process: at most **one** V2G stop per route; routing never
  optimises for V2G.
- **The discharge is not verified by the independent simulator.** The simulator
  never models selling; `apply_v2g` re-evaluates the route and then *writes the
  LP's discharge figures into the metrics*. SoC feasibility of the discharge is
  enforced by the LP only.
- The LP uses a **single conservative power** (the taper rate) for charge and
  discharge time, not the piecewise curve.
- `optimise_solution_schedules()` exists but is **never called** — dead code.
- **Peak / time-of-use windows are unreachable**: nothing passes `peak_window`
  to `generate_stations`, so `peak_start`/`peak_end` are always `None` and the
  big-M peak branch never runs. `ChargingStation.is_peak()` is never called.

---

## 10. Benchmarks and results

**Three categories, kept separate throughout.**
**Measured** = produced by this code, raw file in `results/`.
**Published reference** = a literature value, *not* computed here.
**Interpretation** = my reading, which an interviewer may challenge.

Environment (`results/unconstrained/environment.json`): Python 3.13.5,
OR-Tools 9.15.6755, macOS arm64, seed 42.

### A. Battery not binding (80 kWh, 6 stations, 20 s) — *measured*

`results/unconstrained/benchmark.csv`. Distance in km; % relative to `ortools`.

| Instance | ortools | insertion-ls | insertion | savings |
| --- | --- | --- | --- | --- |
| C101 | **828.94** | 904.87 (+9.2 %) | 1022.53 (+23.4 %) | 1018.36 (+22.9 %) |
| C201 | **607.94** | 712.10 (+17.1 %) | 755.68 (+24.3 %) | 856.56 (+40.9 %) |
| R101 | **1701.51** | 1751.35 (+2.9 %) | 2159.57 (+26.9 %) | infeasible (96/100) |
| R201 | **1206.38** | 1301.03 (+7.8 %) | 1569.85 (+30.1 %) | 1542.18 (+27.8 %) |
| RC101 | **1744.55** | 1792.54 (+2.8 %) | 2299.24 (+31.8 %) | 2098.17 (+20.3 %) |
| RC201 | **1299.85** | 1413.68 (+8.8 %) | 1841.32 (+41.7 %) | 1757.66 (+35.2 %) |

Mean runtime: ortools 20.0 s, insertion-ls 3.8 s, insertion 0.5 s, savings
0.06 s. **Violations: 0 in every row.** *Interpretation:* local search buys most
of what the CP model buys at a fraction of the cost, and the `insertion` column
shows the gain comes from the improvement phase, not the seed.

### B. The C101 result — read carefully

*Measured:* OR-Tools returned **828.94 km with 10 vehicles**, 100/100 customers,
verified feasible.
*Published reference:* 828.94 km / 10 vehicles is the optimum reported for C101 in
the classical VRPTW literature — **that value was not computed here.**
*You may claim:* "on C101 the solver reproduces the published optimum."
*You must not claim* the other instances match published results: published
Solomon results use a **hierarchical objective** (minimise vehicles first, then
distance) while **this project minimises distance only, with 25 vehicles
available**. C101 is comparable because our solution also uses 10 vehicles; R201
at 1206.38 km with 8 vehicles is a different optimisation problem.
*One more caveat:* R101 is 1704.61 km in the sensitivity sweep versus 1701.51 km
here — same battery, same seed, but a different charging network (8 stations /
3 copies vs 6 / 2). Optional station nodes change the search even when nobody
charges.

### C. Energy-constrained (25 kWh, 8 stations, 3 copies, 20 s) — *measured*

`results/constrained/benchmark.csv`, selected rows:

| Instance | Solver | km | Veh. | Charging stops | Plugged in (min) | Served | Feasible |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C101 | ortools | 937.21 | 11 | 4 | 27.4 | 100/100 | yes |
| C101 | insertion-ls | 984.71 | 12 | 1 | 9.8 | 100/100 | yes |
| C201 | ortools | 681.63 | 4 | 12 | 165.9 | 100/100 | yes |
| R101 | ortools | 1769.13 | 22 | 5 | 32.2 | 100/100 | yes |
| R201 | ortools | 1341.46 | 15 | 11 | 151.4 | 100/100 | yes |
| RC101 | ortools | 1878.78 | 20 | 8 | 83.1 | 99/100 | **no** |
| RC201 | ortools | 1155.12 | 12 | 11 | 173.5 | 85/100 | **no** |

*Measured:* shrinking C101's pack from 80 → 25 kWh costs **+13.1 % distance**
(828.94 → 937.21) and one extra vehicle, buying 4 charging stops. **The
`violations` column is 0 in all 24 rows** — every "infeasible" row is an explicit
*unserved customers* count, never a broken constraint. *Interpretation:* on
RC101/RC201 the CP model drops customers rather than return a plan it cannot fly,
while `insertion-ls` serves all of RC201 with more, shorter routes.

### D. Battery sensitivity — *measured* (`results/sensitivity.csv`, ortools)

| Instance | 80 kWh | 40 kWh | 25 kWh | 18 kWh | 14 kWh |
| --- | --- | --- | --- | --- | --- |
| C101 km / served | 828.94 / 100 | 828.94 / 100 | 937.21 / 100 | 969.96 / 93 | 903.57 / 85 |
| C101 charging stops | 0 | 0 | 4 | 9 | 12 |
| R101 km / served | 1704.61 / 100 | 1704.61 / 100 | 1769.13 / 100 | 1780.22 / 96 | 1376.97 / 80 |
| RC101 km / served | 1713.54 / 100 | 1740.22 / 100 | 1878.78 / 99 | 1704.33 / 87 | 1061.66 / 59 |

*Interpretation:* a **threshold, not a gradient**. At 80 and 40 kWh the C101 and
R101 plans are identical — the battery isn't binding. At 25 kWh charging appears
and distance rises. Below that distance *falls* again — **only because customers
are being dropped**. Distance is comparable only between rows serving the same
customers, which is why the harness always reports `customers_served` beside it.

### E. Cost of the conservative energy bound — *measured*

`results/consumption_bounds.csv`. The CP model can't know the payload on a given
arc, so it picks one rate (`SolverConfig.model_consumption_mode`).

| Instance | worst (full payload) | average (half) | empty |
| --- | --- | --- | --- |
| C101 | 997.06 km, 5 stops, **0 viol.** | 930.02 km, 2 stops, 0 | 838.21 km, 1 stop, **2 viol.** |
| C201 | 703.83 km, 11 stops, **0** | 722.77 km, 9 stops, 0 | 694.03 km, 8 stops, **14 viol.** |
| R201 | 1309.14 km, 16 stops, **0** | 1248.95 km, 15 stops, 0 | 1227.38 km, 10 stops, **9 viol.** |

*Measured:* the optimistic `empty` bound gives 1.4–16 % shorter routes and the
simulator **rejected all three**. *Interpretation:* only `worst` is
relaxation-safe — it over-estimates consumption, so anything the model accepts the
simulator accepts too. `average` was clean here but carries no guarantee. On C201
`worst` came out 2.6 % *shorter* than `average`, a reminder that a 20 s budget
leaves a few percent of search noise on top of any real effect.

### Metric glossary

`distance_km` total km (simulator-measured) · `vehicles` routes with ≥1 stop ·
`charging_stops` station visits kept (idle ones pruned) · `charge_time_min`
minutes plugged in · `energy_kwh`/`charged_kwh` consumed / bought ·
`min_soc_kwh` lowest SoC at any arrival · `violations` count of `Violation`
objects (**should always be 0**) · `customers_served` distinct customers ·
`runtime_s` wall clock **including all portfolio attempts**.

---

## 11. Codebase walkthrough

| Path | What it does |
| --- | --- |
| `main.py` | End-to-end demo: scenario → 3 solvers → best *verified* plan → route + SoC plots → V2G pricing. `--legacy` also runs the two original solvers. |
| `app.py` | Streamlit dashboard: sidebar config, 5 tabs (routes / SoC / solver comparison / per-route detail / V2G). Builds the instance via its own `build_instance()` rather than a `Scenario`. |
| `evrp/config.py` | Frozen dataclasses `VehicleSpec`, `EnergyConfig`, `ChargingConfig`, `SolverConfig`, `Scenario`, each with `validate()`. `Scenario` serialises to/from JSON — the reproducibility contract. |
| `evrp/instance.py` | `Node`, `ChargingStation`, `Instance`. Solomon parsing (`read_solomon_frame`, `load_solomon`), NumPy matrices, three metrics, and `diagnostics()` explaining *why* an instance is unsolvable. |
| `evrp/energy.py` | `EnergyModel` (load-dependent consumption, range) and `ChargingCurve` (linear / piecewise CC-CV, `time_for`, `energy_after`). |
| `evrp/feasibility.py` | **The verifier.** `simulate_route` → `RouteSimulation` with per-stop `Stop` records, typed `Violation`s, and `soc_profile()` for plotting. |
| `evrp/solution.py` | `Solution` + `SolutionMetrics`; `evaluate()` re-simulates everything, `feasible` combines violations and coverage; JSON export. |
| `evrp/stations.py` | `generate_stations` — k-means++/Lloyd (hand-written NumPy), grid, random; station 0 on the depot. |
| `evrp/schedule.py` | `optimise_schedule` — the LP/MILP over a fixed sequence, via `ortools.linear_solver` (GLOP/SCIP/CBC). `optimise_solution_schedules` is unused. |
| `evrp/v2g.py` | `best_v2g_detour`, `apply_v2g`, `V2GDecision`, `V2GReport`. |
| `evrp/benchmark.py` | `run_benchmark`, `make_scenarios`, `summarise`, `gap_table`, `to_markdown`, `environment_info`, `SOLOMON_CAPACITY`. Writes `benchmark.csv/.md` + `environment.json`. |
| `evrp/cli.py` | argparse front end: `solve`, `compare`/`benchmark`, `sensitivity`, `v2g`, `bounds`, `validate`, `env`. Writes the `Scenario` beside every result. |
| `evrp/solvers/__init__.py` | Name→factory registry (`create`, `available`). Adding a solver = implement `_solve` + register. |
| `evrp/solvers/base.py` | Abstract `Solver`; `solve()` times the run, aligns charge plans with routes, forces verification. `SolverError`. |
| `evrp/solvers/ortools_evrptw.py` | The CP model, `_prune_idle_charging_stops`, the strategy portfolio; `last_model` kept for debugging/tests. |
| `evrp/solvers/heuristic.py` | `SavingsSolver`, `InsertionLocalSearchSolver`, cached `_RouteEvaluator`, `repair_with_charging`. |
| `evrp/viz/` | `routes.py` (map, charging stops circled), `soc.py` (SoC vs distance with the reserve band), `benchmarks.py` (comparison + sensitivity charts), `theme.py` (palette). Matplotlib on the `Agg` backend, so it works headless. |
| `solver/task1_vrp_solver.py` | **Legacy** OR-Tools VRPTW, bugs fixed (capacity parameterised, Solomon speed, scaled distances, `NoSolutionError` with diagnosis). |
| `solver/task2_vrp_discharge_solver.py` | **Legacy** genetic algorithm, bugs fixed; `VRPDischargeSolver` aliases `VRPSolver` so the original import works. |
| `models/`, `parsers/`, `utils/`, `visualization/`, `data_utils.py` | Original modules, preserved and importable. `utils/distance.py` now has correct `euclidean_distance`, `manhattan_distance` and a real `haversine_distance`. |
| `tests/` | 13 modules, 177 tests; `conftest.py` fixtures (`tiny`, `tiny_with_station`) use hand-computable geometry. |
| `configs/`, `docs/`, `results/`, `Makefile`, `.github/workflows/ci.yml` | Saved scenarios, modelling notes, committed benchmark output, task shortcuts, CI. |

---

## 12. Technology stack — what and why

| Technology | What it is | Why here / where |
| --- | --- | --- |
| **Python 3.11+** | general-purpose language | fast iteration; OR-Tools, NumPy and pandas all have first-class bindings and the heavy work is delegated to C++. Everywhere. |
| **Google OR-Tools** | OR toolkit (C++ core, Python bindings) | its **routing library** gives dimensions, disjunctions, tuned first-solution heuristics and guided local search — months of work otherwise, and slower. Its **linear solver** (`pywraplp`) also supplies GLOP/SCIP for the schedule LP, so one dependency covers both. `evrp/solvers/ortools_evrptw.py`, `evrp/schedule.py`, `solver/task1_vrp_solver.py`. |
| **NumPy** | arrays / matrices | distance and travel-time matrices built in one vectorised `O(n²)` pass instead of a Python double loop, then read thousands of times per search; also powers the hand-written k-means. `evrp/instance.py`, `evrp/stations.py`. |
| **pandas** | dataframes | reads Solomon CSVs with flexible headers; the natural container for benchmark rows → `.to_csv()` and Markdown tables. `evrp/instance.py`, `evrp/benchmark.py`. |
| **Matplotlib** | plotting | route maps, SoC profiles, benchmark charts; forced to the `Agg` backend so figures render headless (CI, CLI) and still embed in Streamlit. `evrp/viz/`, `visualization/map_plotter.py`. |
| **Streamlit** | Python-only web UI | turns the engine into an interactive dashboard with no frontend code, and is testable headlessly via `streamlit.testing.v1.AppTest`. `app.py`. |
| **Plotly** | interactive charts | the SoC gauge and solver-comparison bars in the dashboard, where hover is worth having. `app.py` only. |
| **pytest** + **pytest-cov** | testing | fixtures, parametrisation, the custom `slow` marker, coverage. `tests/`. |
| **GitHub Actions** | CI | fast tests on Python 3.11 and 3.12 plus a CLI smoke test on every push. `.github/workflows/ci.yml`. |
| **pydeck** | map rendering | listed in `requirements.txt`, inherited from the original project, **not imported by any current source file**. Be honest about this. |

---

## 13. Testing and software engineering

**What "177 tests passing" actually means.** Not 177 trivia assertions — a
layered suite:

| Layer | Modules (count) | What it proves |
| --- | --- | --- |
| Configuration | `test_config.py` (22) | invalid parameters rejected at construction; `Scenario` survives a JSON round trip |
| Data & geometry | `test_instance.py` (19) | headers normalised, depot is row 1, customers renumbered, C101 demand = 1810, `haversine` really is great-circle (London–Paris ≈ 344 km), range diagnostics spot unreachable customers |
| Physics | `test_energy.py` (12) | consumption linear; range accounts for the reserve; the taper makes the last fifth of the pack disproportionately slow; `energy_after` is the exact inverse of `time_for` |
| Verifier | `test_feasibility.py` (23) | distances/times/SoC match **hand-computed** values on a 3-customer instance; every violation type fires; early arrival waits; all four charge policies behave |
| Solvers | `test_solvers.py` (30) | all four solvers serve every customer **and** survive an independently recomputed simulation; a charger is used when the pack is too small; regression tests pin the charging-time cost and the conservative bound's zero-violation guarantee; one `slow` test reproduces C101 end to end |
| LP / V2G | `test_schedule.py` (10), `test_v2g.py` (8) | the LP buys exactly the minimum energy, reports infeasible sequences, respects windows, never lets a stop both buy and sell; enabling V2G never removes feasibility |
| Plumbing | `test_benchmark.py` (16), `test_cli.py` (9), `test_stations.py` (10), `test_solution_and_metrics.py` (8), `test_viz.py` (6) | Solomon capacities, gap tables, CLI exit codes and output files, seeded reproducible placement, figures build headless |
| End-to-end UI | `test_app.py` (4) | the Streamlit app starts, lists the shipped instances, reaches a feasibility verdict after clicking *Optimise*, and warns instead of crashing on an empty upload — via `streamlit.testing.v1.AppTest` |

**The key design decision:** solver tests never assert against the solver's own
bookkeeping — they re-simulate the returned routes. That is what makes "serves
100 customers" a meaningful claim.

**Coverage.** `pytest --cov=evrp` reports **90 % of statements** in `evrp`.
Weakest module: `evrp/solvers/heuristic.py` at 75 % — many local-search branches
only fire on larger instances.

**CI.** `.github/workflows/ci.yml` installs `requirements-dev.txt`, runs
`pytest -m "not slow" --cov=evrp` on Python 3.11 and 3.12, then smoke-tests two
CLI commands. *Honest note:* the workflow is committed, but I have no evidence
it has actually run on GitHub Actions.

**Limitations of the testing:**

- 3 tests are marked `slow` and skipped in CI, including the C101-optimum check
  — so CI verifies correctness, not solution quality.
- No property-based / fuzz testing of the simulator.
- No test asserts a solution respects `fleet_size`.
- No runtime detection of duplicate customer visits.
- Benchmark *results* are committed artefacts, not regression-tested.

---

## 14. Limitations — what NOT to claim

### Modelling simplifications, and how to phrase them

| Simplification | Say this |
| --- | --- |
| Euclidean, not road-network distances | "Distances are straight-line. Every solver and the simulator share the same matrix, so the *comparisons* are fair, but absolute kilometres are optimistic." |
| Charging stations invented by us | "Solomon instances have no chargers, so I generate them with seeded k-means. Placement is an input, not a decision variable." |
| Charging discretised in the CP model | "Inside the CP model a stop is a fixed 30-minute session with a capped energy quantum. The LP is continuous; the routing decision is not." |
| Conservative consumption bound | "The CP model uses the full-payload rate because it's the only bound that keeps model-feasibility and true feasibility aligned. I measured the cost: ~7 % on C101 against a mid-range bound." |
| No charger queueing | "A station is always free. Contention would need a cross-route resource model." |
| Flat V2G tariff | "One sell price, no time-of-use curve, no capacity market." |
| Consumption ignores speed / gradient / temperature / HVAC | "First-order model: base rate plus a linear payload term." |
| Homogeneous fleet, always starting full | "Every van is identical and leaves at 100 %. No mixed fleet, no partial start SoC." |
| Deliveries only | "Payload only decreases — no pickups or backhauls." |

### Implemented only in simplified form, or unreachable

- **V2G is a greedy post-process** — at most one stop per route, and routing
  never optimises for it.
- **V2G discharge is not checked by the independent simulator**; the LP enforces
  it, then the numbers are written into the metrics.
- **Peak / time-of-use windows never execute** in any default run.
  `ChargingStation.is_peak()` is never called.
- **`optimise_solution_schedules()` is dead code.**
- **`ChargingCurve.segments()` / `marginal_power_kw()` are unused**; the LP uses
  one conservative taper power despite the docstring.
- **The heuristics' `rng` is unused**, so `SolverConfig.seed` effectively only
  controls station placement; OR-Tools' search isn't explicitly seeded (a test
  asserts run-to-run determinism instead).
- **The simulator does not detect duplicate customer visits.**

### Benchmark comparability

- **Only C101 is comparable to a published result.** This project minimises
  distance with 25 vehicles available; classical Solomon results minimise vehicle
  count first. Never present the other rows as literature comparisons.
- **20-second budgets leave a few percent of search noise** — visible where the
  safe bound beat the mid-range one on C201.
- One machine, one seed, single-threaded wall clock. No multi-seed variance
  study.

### Environment inconsistency (found while writing this guide)

`requirements.txt` pins `pandas>=2.1,<3` and `plotly>=5.20,<7`, but the `.venv`
that produced the committed results has **pandas 3.0.5** and **plotly 7.0.0** —
outside those ranges. A fresh `pip install -r requirements.txt` would install
different versions than `results/*/environment.json` records. Also `pydeck` is in
`requirements.txt` but imported nowhere. Flag this before an interviewer finds it.

**General phrasing rule:** lead with the decision, then the cost, then the
measurement. *"I used straight-line distances because the benchmark instances are
planar and it keeps the solver comparison fair. Absolute distances are therefore
optimistic — for a real deployment I'd swap in an OSRM matrix, which is a drop-in
change since everything reads `Instance.distance`."* Never say "it's just a
student project".

---

## 15. Interview preparation

Format: **Q** → a tight answer you can say out loud. *(Italics = a likely
follow-up.)*

### A. Project understanding

**A1. What is this project?** "It plans delivery routes for electric vans on the
Solomon benchmark instances, under time windows, capacity and a battery that must
be recharged mid-route. Four solvers, plus an independent simulator that verifies
every plan before any number is reported."

**A2. Why is this an EVRP, not a VRP?** "Because energy is a constrained but
*replenishable* resource. A normal VRP tracks distance, load and time; here state
of charge falls on every arc, must stay above a reserve, can only be restored at
a station — and restoring it costs schedule time, which couples it to the time
windows." *(What if the battery were huge? → "It degenerates to a VRPTW. I
measured that: at 80 and 40 kWh the C101 plans are identical.")*

**A3. Walk me through `python main.py`.** "Builds a `Scenario`, loads C101,
generates six chargers by k-means, runs `ortools`, `insertion-ls` and `savings`,
verifies each with the simulator, picks the best *verified* plan, writes a route
map and SoC plot, then prices V2G detours and writes the solution JSON."

**A4. Why did the original implementation have problems?** "Three fatal ones.
`main.py` imported a class that didn't exist. Vehicle capacity was hard-coded to
100 while C101 needs 1810 units total, so OR-Tools correctly said 'no solution'
for a reason unrelated to routing. And the GA's fitness skipped every route past
the fleet size, so serving nobody scored zero — a perfect score. That last one is
why the verifier exists."

### B. Python / codebase

**B1. Why frozen dataclasses for config?** "Immutability makes a `Scenario` safe
to pass around, and `asdict`/`from_dict` give JSON serialisation for free. Every
run writes the scenario it actually used next to its output — the reproducibility
contract."

**B2. How do you add a fifth solver?** "Subclass `Solver`, implement `_solve`
returning `(routes, status, meta)`, register it in `evrp/solvers/__init__.py`.
The CLI, benchmark harness and dashboard all read `available()`, so they pick it
up automatically."

### C. Algorithms

**C1. What does your local search do, and why first-improvement?** "2-opt and
Or-opt within a route, relocate and swap between routes. First-improvement
because every candidate costs a full simulation." *(Escaping local optima? → "I
don't — no perturbation or restart. ALNS-style ruin-and-recreate is the first
thing I'd add.")*

**C2. Why keep `insertion` when `insertion-ls` dominates it?** "It's the ablation.
Construction alone is 24–42 % worse than OR-Tools; local search closes that to
2.8–17 %. Without it I couldn't say whether the quality came from the seed or the
improvement phase."

**C3. Why heuristics at all if OR-Tools exists?** "Comparison, speed and
robustness. `insertion-ls` is within 2.9 % on R101 in about a second versus
twenty — and on RC201 at 25 kWh the heuristics served all 100 customers while the
CP model dropped 15, because they use exact load-dependent consumption while the
CP model is stuck with a conservative bound."

### D. OR-Tools

**D1. Why OR-Tools?** "A mature routing library with the machinery I'd otherwise
write badly: dimensions, disjunctions, tuned construction heuristics, guided
local search. It also ships `pywraplp`, so one dependency gives me GLOP and SCIP
for the schedule LP." *(Alternatives? → "A MILP gives proven optimality but
doesn't scale to 100 customers with windows in seconds; a custom metaheuristic is
what my heuristics already are.")*

**D2. How do you model the battery as a dimension?** *The key technical answer.*
"A dimension only accumulates — `cumul(next) = cumul(i) + transit + slack`, slack
non-negative — so you can't reset 'energy consumed' at a charger. I track
**remaining SoC** instead: transit is *negative* consumption, slack at a station
is the energy added, slack is forced to zero everywhere else, and the cumul is
bounded to `[reserve, battery]`. Stations are replicated and made optional with
zero-penalty disjunctions so one vehicle can charge twice."

**D3. How does the model know charging takes time?** "A station visit adds a fixed
30-minute session to the *time* transit, and the energy slack there is capped at
what the charger guarantees in 30 minutes at its slowest taper rate — so the
session always finishes inside the time it paid for." *(Why not link the two
dimensions' slack variables? → "I tried. It held at a route's last charging stop
but not earlier ones — the model added 28 kWh in under four minutes and the
simulator caught it. I reproduced it on a four-node instance, decided not to
root-cause OR-Tools internals inside this project, and designed around it with a
regression test.")*

**D4. What is a disjunction, and why two penalties?** "It makes a node optional at
a stated cost. Station replicas get penalty 0 — skipping a charger should be
free. Customers get 1e6, so dropping one is a last resort. That turns 'no
solution' into 'here's a plan plus the customers I couldn't serve'."

### E. EV / battery / charging

**E1. How does the battery constraint work?** "In the verifier: start full,
subtract `rate(payload) × distance` per arc, flag a `BATTERY` violation with the
exact kWh shortfall whenever arrival SoC drops below `battery × reserve_soc`. In
the CP model: the energy dimension's cumul is bounded below by the reserve. Note
it's the reserve, not zero."

**E2. How is charging time calculated?** "`ChargingCurve.time_for` with a
piecewise CC-CV curve — full power to 80 % of the pack, then 45 % of that power,
plus a 2-minute plug-in overhead, at `min(station, on-board)` power. The last
fifth of the pack costs disproportionately, which is exactly what a linear model
misses and what pushes routes out of their windows."

**E3. Why does consumption depend on load?** "Rolling resistance and the
acceleration component both scale with mass, so I model it linearly:
`(0.22 + 0.00008·payload_kg) kWh/km`. A van sheds load as it delivers, so the leg
home is cheapest — and the battery is tightest exactly then." *(Where did 0.00008
come from? → "A chosen parameter, not fitted: a 1000 kg payload adds about 36 %,
the right order for a light commercial vehicle. Real telemetry would calibrate
it.")*

**E4. How do you stop a route becoming energy-infeasible?** "In the CP model the
energy dimension makes it a hard constraint, so the search never produces one. In
the heuristics, `repair_with_charging` sees a battery-only violation and inserts
the station that fixes it at the smallest detour, up to three times — a customer
beyond half the range needs a stop out and a stop back."

**E5. Where do the charging stations come from?** "I generate them — Solomon
instances predate electric fleets. Station 0 sits on the depot, the rest at
k-means centroids, seeded for reproducibility. Placement is an input, not a
decision variable, and I flag that."

### F. Optimisation

**F1. What exactly are you optimising?** "Total distance. There's a
`vehicle_fixed_cost` knob for a fleet-size term but it defaults to 0 — a
deliberate simplification, and it's why my results aren't comparable with
published Solomon figures, which minimise vehicles first."

**F2. Is your solution optimal?** "No, and I don't claim it. OR-Tools returns the
best solution found in the time budget; it isn't proving optimality. On C101 it
reaches 828.94 km with 10 vehicles, matching the published optimum — evidence the
model is right, not a proof."

**F3. Why decompose into routing then LP scheduling?** "With the sequence fixed,
the energy and timing recursions are affine, so the charging plan is an LP
solvable to proven optimality. Solving both jointly needs a MILP that doesn't
scale. In this repo the LP is only wired into the V2G path — I should be clear it
isn't part of the main routing loop."

**F4. What's the relaxation-safety argument?** "The CP model must never accept a
route the exact simulator rejects, so both approximations lean pessimistic:
consumption at full payload, charging at the taper rate — both upper bounds. I
measured the cost: the optimistic bound is 1.4–16 % shorter and got rejected on
all three instances tested."

### G. Testing / software engineering

**G1. Why an independent feasibility simulator?** *The question to ace.*
"Because a solver that grades its own homework will report an impossible route as
optimal — the original GA converged to 'cost 0' by serving nobody. The simulator
shares no code with any solver: it takes a route as a list of node indices and
physically replays it. It caught four real bugs in my own CP model, including one
where the pack was overfilled and one where charging took zero minutes."

**G2. What does 90 % coverage mean — and not mean?** "90 % of statements in
`evrp` execute during the suite. It does *not* mean the logic is right; coverage
measures execution, not correctness. The tests that matter assert hand-computed
values and re-simulate solver output independently."

**G3. What's in CI, and what isn't?** "Push and PR, Python 3.11 and 3.12, the fast
tests with coverage, plus a CLI smoke test. Three `slow` tests are skipped —
including the C101 optimum — so CI verifies correctness, not quality. And I
haven't actually seen the workflow run on GitHub."

### H. V2G

**H1. What is V2G and how do you model it?** "A plugged-in van pushes energy back
to the grid. I model it as a post-process: enumerate detours to a charger,
simulate feasibility, run a small MILP to decide how much can be sold given the
reserve, charger power and time windows, and take the detour only if revenue
beats the extra kilometres at \$0.25/km."

**H2. Why a binary variable in the schedule model?** "With a flat LP, if the sell
price exceeds the buy price the optimiser buys and sells at the same plug and
prints money. No charger allows that. One binary per station forces a stop to be
either a buyer or a seller."

**H3. Your V2G result shows 0 extra km — suspicious?** "Honest and explainable.
Station 0 is always placed on the depot, so the profitable trade was selling
surplus at the depot rather than driving anywhere. The detour machinery still ran
and declined every detour that didn't pay."

**H4. Is the V2G energy verified?** "Only by the LP, not by the independent
simulator — the simulator doesn't model discharge, so `Stop.discharged_kwh` is
always zero and the LP's figures are folded into the metrics afterwards. That's a
real gap."

### I. Benchmarks / results

**I1. What does the C101 result mean?** "OR-Tools returned 828.94 km with 10
vehicles, all 100 customers, zero violations. That value is the one reported as
optimal for C101 in the VRPTW literature — I didn't compute the reference, I'm
comparing against it. Reproducing it end to end is strong evidence that distance,
capacity and time windows are modelled correctly, including the Solomon
convention that travel time equals Euclidean distance."

**I2. Limitations of that comparison?** *The most important thing not to
overclaim.* "Published Solomon results minimise vehicles first, then distance. I
minimise distance with 25 vehicles available. C101 happens to be comparable
because my solution also uses 10 vehicles; R201 at 1206 km with 8 vehicles isn't
the same problem as the published figure. I only claim the C101 match."

**I3. How do you know your results are correct?** "Every reported number comes
from the simulator, not the solver. The `violations` column is zero in all 48
benchmark rows. The scenario and the environment — Python and OR-Tools versions,
timestamp — are written next to each result, and it regenerates with `make
bench`."

**I4. What does the battery sweep show?** "A threshold, not a gradient. At 80 and
40 kWh the C101 and R101 plans are identical. At 25 kWh charging appears and
distance rises 13 % on C101. Below that distance *falls*, but only because
customers are being dropped — which is why the table reports `customers_served`
next to distance."

### J. Challenging follow-ups

**J1. Hardest technical problem?** "Getting charging time enforced in the CP
model. My first design linked the time dimension's slack to the energy
dimension's slack; it looked right and passed on small instances, but on C201 the
simulator flagged a batch of late deliveries because the constraint bound at a
route's last charging stop and not earlier ones. I reduced it to a four-node
repro, decided root-causing OR-Tools internals wasn't the right use of time, and
redesigned charging as a fixed-length session in the time transit — an ordinary
constraint that can't be ignored — then pinned it with two regression tests."

**J2. What would you improve next?** "Road-network distances via OSRM; ALNS-style
ruin-and-recreate so the heuristics can escape local optima; making V2G part of
the routing objective rather than a post-process; and charger queueing, the
biggest gap to a deployable system."

**J3. How would you scale to a real fleet?** "The `O(n²)` matrix and the
per-candidate simulation dominate. For thousands of stops: cluster geographically
and solve sub-problems, cache a sparse k-nearest-neighbour matrix, and replace
the exact simulator in the local-search inner loop with incremental delta
evaluation, keeping full simulation as an acceptance gate. OR-Tools handles a few
thousand nodes; my Python simulator is the bottleneck long before that."

**J4. What if charging stations have queues?** "A shared resource my model doesn't
have. Either a station-capacity constraint — but OR-Tools dimensions are
per-route, so cross-route resources need a scheduling model — or solve routing
first and then a queueing model over the charging stops, accepting the routing
was optimistic. Both distance and dwell time would rise."

**J5. What if electricity prices change dynamically?** "Today the prices are flat
scalars. The schedule LP already has explicit arrival and service-start
variables, so I'd make price a piecewise-constant function of time with binaries
selecting the tariff interval — a natural extension of the peak-window logic
sketched in `schedule.py` but never activated. It would make *when* you charge a
real decision."

**J6. What if you had 10 000 customers?** "Nothing here works unchanged — the
distance matrix alone is 10⁸ entries. I'd need a two-level decomposition, a
sparse candidate-arc list, and a compiled inner loop or a proper LNS. 100
customers is the scale this is validated at."

**J7. Why not reinforcement learning or a genetic algorithm?** "There *is* a GA
here — the legacy `task2` solver — and it's the worst performer, which is
instructive: a naive GA over routes spends most of its effort repairing
infeasibility that OR-Tools handles by construction. RL could learn a
construction policy but needs training, gives no feasibility guarantee, and would
still need this verifier. For 100 customers with hard constraints, CP plus local
search is the right tool."

**J8. What if the solver returns an infeasible solution?** "It can't reach a
report as feasible. `Solver.solve` always evaluates through the simulator, and
`Solution.feasible` requires zero violations *and* full coverage. If OR-Tools
finds nothing at all it raises `SolverError` with the instance diagnostics, and
the benchmark harness records an error row instead of crashing."

**J9. What does your `seed` actually control?** "Less than the name suggests. It
seeds the k-means station placement. The heuristics create a
`random.Random(seed)` but never use it, and OR-Tools' search isn't explicitly
seeded either, though a test asserts run-to-run determinism. I'd either wire it
through or rename it."

---

## 16. Explaining this project in an interview

**30 seconds**

> It's a route planner for electric delivery fleets. On top of the usual routing
> constraints — time windows and capacity — it models the battery: how much
> energy each leg costs, where to stop and charge, and how much time that
> charging eats out of the schedule. I implemented it four ways and built a
> separate simulator that verifies every plan, because an optimiser that checks
> its own work will happily report an impossible route.

**60 seconds**

> A depot, 100 customers with delivery windows, and electric vans with a payload
> limit and a battery. The battery is the interesting part — range is finite,
> consumption rises with the load on board, and recharging costs real schedule
> time because packs charge fast to 80 % and then taper.
>
> I model it as an electric VRP with time windows. The main solver is an OR-Tools
> constraint-programming model where the battery is a dimension tracking
> remaining state of charge: driving is a negative transit, and charging stations
> are optional replicated nodes where energy can be added. I also built three
> heuristics — savings, insertion, and insertion plus local search — so there's
> something to compare against.
>
> The piece I'm most pleased with is the verification layer: an independent
> simulator that replays every route physically and reports exactly which
> constraint broke and by how much. It caught four real bugs in my own CP model
> that the solver considered perfectly valid.

**2 minutes** — the 60-second version, then:

> On results: with a large battery, so energy doesn't bind, the model reduces to
> a classic VRPTW and OR-Tools reaches 828.94 km with 10 vehicles on C101, which
> matches the published optimum. I'm careful there — published Solomon results
> minimise vehicle count first and then distance, while I minimise distance with
> a large fleet, so only C101 is directly comparable.
>
> Shrink the pack to 25 kWh and the EV part switches on: C101 costs 13 % more
> distance, one extra vehicle, four charging stops and 27 minutes plugged in.
> Across 48 benchmark rows there are zero constraint violations — every failure
> is an explicit "these customers couldn't be served", never a silently broken
> plan.
>
> There's a vehicle-to-grid extension too — pricing detours to sell surplus
> energy back, with a small MILP for the energy schedule — but it's an extension,
> and a post-process on an already-solved plan.

**5 minutes** — the 2-minute version, then pick one deep-dive:

*The battery dimension.* "An OR-Tools dimension only accumulates —
`cumul(next) = cumul(i) + transit + slack`, slack non-negative — so you can't
reset 'energy used' at a charger. I invert it and track remaining SoC: transit is
negative consumption, the slack at a station node *is* the recharge, forced to
zero everywhere else, cumul bounded to `[reserve, battery]`. Two things bit me.
The dimension bounds the cumul *at* nodes, so the model was free to overfill the
pack as long as the next arc burned off the excess — I added an explicit
departure bound. And `SlackVar` isn't in the returned assignment, so reading the
charged energy gave zero; I recover it from the cumul difference instead. Then
the charging-time constraint failed in a way I couldn't fully explain, so I
replaced it with a fixed-length session priced directly in the time transit —
which is an ordinary constraint that can't be silently ignored — and pinned it
with regression tests. Every one of those three problems was found by the
simulator, not by the solver."

---

## 17. Final cheat sheet

### 10 concepts

1. **VRPTW** — routing with time windows and capacity; NP-hard.
2. **State of charge** — remaining battery in kWh; must stay ≥ reserve.
3. **OR-Tools dimension** — `cumul(next) = cumul(i) + transit + slack`.
4. **Negative-transit SoC trick** — track *remaining* charge so driving is a
   negative transit and slack-at-stations is the recharge.
5. **Station replication + zero-penalty disjunction** — how one charger becomes
   visitable multiple times, optionally.
6. **CC-CV taper** — fast to ~80 %, then slow; the last fifth is
   disproportionately expensive in time.
7. **Load-dependent consumption** — `(0.22 + 0.00008·payload) kWh/km`.
8. **Relaxation safety** — the CP model's approximations must be pessimistic so
   model-feasible ⟹ truly feasible.
9. **Independent verification** — the solver does not grade its own homework.
10. **Two-stage decomposition** — fix the sequence, then the charging schedule is
    an LP (here used only for V2G).

### 10 numbers

| # | Value |
| --- | --- |
| 1 | **C101 = 828.94 km, 10 vehicles** — matches the published optimum |
| 2 | 100 customers + 1 depot per instance; 6 instances benchmarked |
| 3 | C101 total demand **1810**; Solomon capacities 200 / 700 / 1000 |
| 4 | Default pack **40 kWh**, reserve **10 %**, **0.22 kWh/km** empty |
| 5 | 25 kWh pack ⇒ **+13.1 %** distance on C101, 4 stops, 27 min plugged in |
| 6 | `insertion-ls` **+2.8 %** over OR-Tools on RC101, ~2 s vs 20 s |
| 7 | Optimistic consumption bound: **1.4–16 %** shorter, **rejected 3/3** |
| 8 | **0 constraint violations** across all 48 benchmark rows |
| 9 | **177 tests**, 3 slow, **90 %** statement coverage of `evrp/` |
| 10 | V2G on R201: **95.5 kWh sold, \$52.52 net, 0 extra km** |

### 10 files

`evrp/feasibility.py` (verifier) · `evrp/solvers/ortools_evrptw.py` (CP model) ·
`evrp/solvers/heuristic.py` (3 heuristics) · `evrp/energy.py` (consumption +
charging curve) · `evrp/instance.py` (data + matrices) · `evrp/config.py`
(parameters) · `evrp/schedule.py` (LP/MILP) · `evrp/v2g.py` (detour pricing) ·
`evrp/benchmark.py` + `evrp/cli.py` (experiments) · `tests/test_solvers.py`

### 10 must-answer questions

1. Why is this an EVRP and not a VRP?
2. How is the battery modelled as an OR-Tools dimension?
3. Why do you need an independent simulator?
4. How is charging time calculated and enforced?
5. What does the C101 result mean — and what does it *not* mean?
6. Why keep heuristics when OR-Tools exists?
7. What was the hardest bug and how did you handle it?
8. What is the conservative consumption bound and what does it cost?
9. What are the biggest limitations of this project?
10. How would you scale it to a real fleet?

### Terminology

| Term | One line |
| --- | --- |
| VRP / VRPTW / E-VRPTW | routing / + time windows / + battery and charging |
| Time window | `[ready, due]`; early ⇒ wait, late ⇒ violation |
| SoC | state of charge, kWh remaining |
| Reserve | fraction of the pack routing may not spend (default 10 %) |
| Dimension | OR-Tools resource accumulated along a route |
| Cumul / transit / slack | value at a node / change on an arc / extra added at a node |
| Disjunction | makes a node optional at a stated penalty |
| 2-opt / Or-opt / relocate / swap | classical local-search moves |
| Savings | `d(0,i)+d(0,j)−d(i,j)` — distance saved by merging two routes |
| CC-CV | constant-current then constant-voltage charging; the taper |
| Charging quantum | max kWh one 30-minute session may deliver in the CP model |
| Relaxation safety | model approximations lean pessimistic so feasibility is preserved |
| V2G | vehicle-to-grid: selling pack energy back |
| Solomon instances | the standard VRPTW benchmark set (C/R/RC families) |
| BKS | best-known solution — a published reference, not computed here |
