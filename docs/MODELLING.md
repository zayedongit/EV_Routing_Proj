# Modelling notes

How the electric vehicle routing problem is written down here, and which
approximations were made deliberately.

## 1. Units and the Solomon convention

| quantity | unit | note |
| --- | --- | --- |
| distance | km | Solomon coordinate units read as kilometres |
| time | min | Solomon time units read as minutes |
| speed | km/min | default 1.0, i.e. 60 km/h |
| energy | kWh | |
| power | kW | |
| payload | kg | Solomon "demand" units |

Speed 1.0 is not arbitrary. The Solomon benchmark defines **travel time as the
Euclidean distance between two points**; any other speed silently rescales
every time window relative to the published instances and makes results
incomparable with the literature. The original code divided distance by 50 and
multiplied by 60, tightening every window by 20 %.

## 2. Energy

Consumption is linear in distance and in the payload carried on that arc:

```
E(d, m) = (base + slope · m) · d
```

Payload matters because a van that has already delivered half its load uses
measurably less per kilometre; a model that ignores it overstates the energy
needed at the end of a route, which is exactly where the battery is tightest.
Keeping the dependence linear is what lets the same model be embedded in an
OR-Tools dimension and in a linear program.

Deliveries, not pickups: a vehicle leaves the depot carrying the whole route
demand and sheds each customer's demand on service.

## 3. Charging

Charging is modelled with a **piecewise-linear CC-CV approximation**: full
power up to `cc_end_soc` (80 % by default), then a taper. The last fifth of a
pack takes roughly as long as the first two fifths. This matters for routing
because a linear model makes "just top it up at the end" look cheap, and it is
not: the time it costs is what pushes a route out of its remaining windows.

`ChargingCurve` exposes the curve three ways — `time_for` (energy → time),
`energy_after` (time → energy, its exact inverse) and `segments` (the linear
pieces, for the LP).

## 4. The CP model (`evrp.solvers.ortools_evrptw`)

Standard VRPTW dimensions for distance, capacity and time, plus an energy
dimension that is the interesting part.

An OR-Tools dimension only accumulates:

```
cumul(j) = cumul(i) + transit(i, j) + slack(i),   slack(i) >= 0
```

so a battery, which can be *refilled mid-route*, does not fit the obvious
encoding. The trick is to track **remaining state of charge** instead of energy
consumed:

* `transit(i, j) = -energy(i, j)` — driving is a negative transit;
* `slack(i)` — energy pushed into the pack at `i`, forced to zero everywhere
  except at charging nodes;
* `cumul` bounded to `[reserve, battery]`.

Charging stations are replicated `station_copies` times as optional nodes
(zero-penalty disjunctions), the usual reformulation that lets several
vehicles — or the same vehicle twice — use one charger.

Charging **time** is tied to charging **energy** by a constraint between the
two dimensions' slack variables at each station node, so a longer recharge
really does eat into the time windows.

### Two bugs this formulation invites

Both were found by the independent simulator, not by the solver:

1. **The pack could be overfilled.** The dimension bounds the cumul *at* nodes,
   so a model charging `S` at a node holding `C` was free to let `C + S` exceed
   the battery as long as the next arc burned the excess off. The fix is an
   explicit bound on the state at departure:
   `cumul(i) + slack(i) <= battery`.
2. **Slack variables read back as zero.** `SlackVar` is not part of the
   returned assignment, so reading it gives a meaningless zero and the reported
   charging plan was empty. The recharge has to be recovered from the cumul
   difference: `slack(i) = cumul(next) - cumul(i) - transit(i, next)`.

### Relaxation safety

The CP model must never call a route feasible that the exact simulator
rejects, so both of its approximations lean conservative:

* consumption uses a payload-independent **upper bound** (the rate at full
  payload) while the simulator uses the true, lighter, load-dependent rate;
* charging power uses the **taper** power of the CC-CV curve, an upper bound on
  the time any amount of energy takes.

`SolverConfig.model_charge_power_mode` switches the second to the optimistic
nominal power, so the cost of the conservatism can be measured rather than
assumed.

### First-solution strategies

`PATH_CHEAPEST_ARC` builds routes arc by arc and, on an energy-tight instance,
drives to the far customer before discovering it cannot get home — with no
charging stop left to insert, the customer is dropped and local search never
recovers. Insertion-based construction places the charger first. The solver
therefore runs a small portfolio of first-solution strategies and keeps the
best verified result.

## 5. The schedule LP/MILP (`evrp.schedule`)

Once the *sequence* is fixed, deciding how much to charge at each stop — and,
with V2G, how much to sell and when — is linear:

```
soc[k+1] = soc[k] + charge[k] - discharge[k] - arc_energy[k]
arr[k+1] = start[k] + service[k] + plug[k] + travel[k]
start[k] >= arr[k],  start[k] >= ready[k],  arr[k] <= due[k]
```

Waiting for a window is a `max`, handled the standard way by splitting arrival
from service start. The objective maximises V2G revenue minus energy bought,
with a small tie-break penalty on finish time.

One binary per station makes a stop either a buyer or a seller. Without it the
LP round-trips energy through a single plug whenever the sell price beats the
buy price — free money that no charger actually offers.

Solved with GLOP when there are no binaries, SCIP/CBC when there are.

## 6. Verification

`evrp.feasibility.simulate_route` shares no code with any solver. It replays a
route stop by stop and returns the full trajectory plus typed violations with
magnitudes. Every solver's output goes through it before any number is
reported, and the heuristics use it as their acceptance test, so no search can
talk itself into an infeasible answer.

It also replays the schedule LP's decisions rather than trusting them: a
`discharge_plan` puts the sold energy back through the same state-of-charge
recursion, and selling below the V2G floor, at a station that cannot absorb
energy, or outside a declared peak window each raises a violation. A repeat
visit to a customer on one route is a violation too; a customer served by two
different routes is caught one level up, in `Solution.evaluate`.

## 7. Known approximations

* Distances are straight-line, not road-network. Every solver and the simulator
  share the same matrix, so comparisons between them are fair, but absolute
  kilometres are optimistic.
* Charging stations are placed by the project (k-means on customer locations by
  default), because Solomon instances have none. Placement is seeded and
  reported; it is an input, not a decision variable.
* Queueing at chargers is not modelled: a station is always free.
* The V2G tariff is a flat price inside an optional peak window
  (`Scenario.peak_start_min` / `peak_end_min`, or `--peak-window`), not a real
  time-of-use curve or a capacity market.  Windows are off by default.
* Consumption ignores speed, gradient, temperature and auxiliary loads.
