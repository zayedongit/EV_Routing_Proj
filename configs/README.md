# Scenario files

A scenario is the complete, serialisable description of one experiment:
instance, fleet, battery, charging network, tariffs, solver and seed.  Anything
that changes a number lives in here, so a result can be replayed later.

```bash
python -m evrp.cli solve --instance data/C101.csv --battery 25 --out results
# results/C101-ortools-scenario.json is the scenario that actually ran
```

Load one back in code:

```python
from evrp.config import Scenario
from evrp.instance import instance_from_scenario

scenario = Scenario.from_json("configs/tight-battery.json")
instance = instance_from_scenario(scenario)
```

The files here are starting points, not a fixed list — write your own.
