# EV Routing Optimization

Vehicle routing for electric fleets, modelled as a constrained optimization problem in Google OR-Tools,
with an interactive app for comparing strategies.

## The problem

An electric fleet can't be routed like a diesel one. Vehicles have finite range, recharging takes real
time, and deliveries have time windows that don't care about either. A route that looks cheapest on
distance can turn out to be infeasible once energy is accounted for — and a route that's feasible can
be needlessly expensive.

The goal here was to compare routing strategies rigorously rather than argue about them: same
scenarios, same constraints, measured on cost and feasibility.

## What it does

Two variants:

1. **VRP with time windows** — routing under delivery time-window and vehicle energy constraints.
2. **VRP with grid discharge** — vehicles can discharge back to the grid during peak hours, which
   changes the cost calculus and the optimal route shape.

Both are solved with OR-Tools and benchmarked across configurable fleet sizes and demand scenarios.

## Running it

```bash
pip install -r requirements.txt

streamlit run app.py      # interactive route explorer
python main.py            # CLI solve + benchmark
```

## Structure

```
.gitignore
README.md
app.py
assets/
data/
data_utils.py
main.py
models/
parsers/
requirements.txt
solver/
utils/
visualization/
```

## What I'd fix given another week

- **Real road-network distances.** The current distance model is a simplification; routing decisions
  are only as good as the matrix underneath them.
- **Charging-station placement as a decision variable** rather than a fixed input — right now the
  model routes around infrastructure it can't influence.
- **A proper benchmark suite with fixed seeds**, so results are comparable across code changes
  instead of across whatever scenario happened to be loaded.
