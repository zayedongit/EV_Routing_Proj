"""Constructive heuristics plus local search, with charging-station repair.

Two classical construction schemes are implemented so that the CP model has
something honest to be compared against:

``SavingsSolver``
    Clarke & Wright savings, adapted to time windows and energy: merges are
    accepted only if the merged route survives the exact simulator.

``InsertionLocalSearchSolver``
    Solomon-style sequential cheapest-insertion, then a local-search pass over
    the classic VRP neighbourhoods (intra-route 2-opt and Or-opt, inter-route
    relocate and swap) under a first-improvement strategy and a wall-clock
    budget.

Both share the same **charging repair**: whenever a candidate route runs the
pack below its reserve, the repair operator tries inserting the charging
station that fixes the deficit at the smallest detour, at the best position,
and re-checks with the simulator.  This keeps energy handling in one place and
makes the heuristics directly comparable with the CP model, which solves the
same decision jointly rather than in two stages.

Every acceptance test in this module goes through :func:`simulate_route`, so a
heuristic can never talk itself into an infeasible answer.
"""

from __future__ import annotations

import random
import time
from typing import Any, Sequence

from evrp.config import ChargingConfig, EnergyConfig, SolverConfig
from evrp.feasibility import RouteSimulation, ViolationKind, simulate_route
from evrp.instance import Instance
from evrp.solvers.base import Solver


class _RouteEvaluator:
    """Caches simulator calls; the local search re-tests the same routes a lot."""

    def __init__(
        self,
        instance: Instance,
        energy_config: EnergyConfig,
        charging_config: ChargingConfig,
    ) -> None:
        self.instance = instance
        self.energy_config = energy_config
        self.charging_config = charging_config
        self._cache: dict[tuple[int, ...], RouteSimulation] = {}
        self.calls = 0
        self.hits = 0

    def simulate(self, route: Sequence[int]) -> RouteSimulation:
        key = tuple(route)
        cached = self._cache.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        self.calls += 1
        sim = simulate_route(
            self.instance,
            key,
            energy_config=self.energy_config,
            charging_config=self.charging_config,
            charge_policy="minimal",
        )
        if len(self._cache) < 400_000:
            self._cache[key] = sim
        return sim

    def feasible(self, route: Sequence[int]) -> bool:
        return self.simulate(route).feasible

    def cost(self, route: Sequence[int]) -> float:
        return self.simulate(route).distance


def _battery_deficit(sim: RouteSimulation) -> float:
    """Total kWh by which a route dips under the reserve; 0 when energy is fine."""
    return sum(v.magnitude for v in sim.violations if v.kind is ViolationKind.BATTERY)


def _energy_only_violations(sim: RouteSimulation) -> bool:
    return bool(sim.violations) and all(
        v.kind is ViolationKind.BATTERY for v in sim.violations
    )


def repair_with_charging(
    evaluator: _RouteEvaluator,
    route: Sequence[int],
    max_inserts: int = 3,
) -> list[int] | None:
    """Insert charging stops until the route is feasible, or give up.

    Greedy on detour distance: for every (position, station) pair the operator
    prices the extra kilometres and keeps the cheapest insertion that makes the
    simulator happy.  Repeated up to ``max_inserts`` times because one stop is
    not always enough on a long route.
    """
    instance = evaluator.instance
    stations = instance.station_indices
    if not stations:
        return None

    current = list(route)
    for _ in range(max_inserts):
        sim = evaluator.simulate(current)
        if sim.feasible:
            return current
        if not _energy_only_violations(sim):
            return None
        deficit = _battery_deficit(sim)

        # Prefer an insertion that finishes the job; otherwise take the one that
        # shrinks the energy deficit most per kilometre of detour, and go again.
        # A single charger is often not enough -- a customer beyond half the
        # range needs one stop outbound and another on the way home.
        best_feasible: tuple[float, list[int]] | None = None
        best_partial: tuple[float, float, list[int]] | None = None
        seq = [0, *current, 0]
        for pos in range(1, len(seq)):
            a, b = seq[pos - 1], seq[pos]
            for s in stations:
                detour = float(
                    instance.distance[a][s]
                    + instance.distance[s][b]
                    - instance.distance[a][b]
                )
                if best_feasible is not None and detour >= best_feasible[0]:
                    continue
                candidate = current[: pos - 1] + [s] + current[pos - 1 :]
                cand_sim = evaluator.simulate(candidate)
                if cand_sim.feasible:
                    best_feasible = (detour, candidate)
                    continue
                if not _energy_only_violations(cand_sim):
                    continue
                cand_deficit = _battery_deficit(cand_sim)
                if cand_deficit >= deficit - 1e-9:
                    continue
                key = (cand_deficit, detour)
                if best_partial is None or key < best_partial[:2]:
                    best_partial = (cand_deficit, detour, candidate)

        if best_feasible is not None:
            return best_feasible[1]
        if best_partial is None:
            return None
        current = best_partial[2]

    return current if evaluator.feasible(current) else None


def _try_route(evaluator: _RouteEvaluator, route: Sequence[int]) -> list[int] | None:
    """Return a feasible version of ``route``, adding charging stops if needed."""
    if not route:
        return list(route)
    sim = evaluator.simulate(route)
    if sim.feasible:
        return list(route)
    if _energy_only_violations(sim):
        return repair_with_charging(evaluator, route)
    return None


class _HeuristicBase(Solver):
    def __init__(
        self,
        solver_config: SolverConfig | None = None,
        energy_config: EnergyConfig | None = None,
        charging_config: ChargingConfig | None = None,
    ) -> None:
        super().__init__(solver_config, energy_config, charging_config)

    def _evaluator(self, instance: Instance) -> _RouteEvaluator:
        return _RouteEvaluator(instance, self.energy_config, self.charging_config)


# -- Clarke & Wright ------------------------------------------------------

class SavingsSolver(_HeuristicBase):
    """Clarke & Wright savings with time-window and energy screening."""

    name = "savings"

    def _solve(self, instance: Instance) -> tuple[list[list[int]], str, dict[str, Any]]:
        ev = self._evaluator(instance)
        d = instance.distance

        routes: dict[int, list[int]] = {}
        unrouted: list[int] = []
        for c in instance.customer_indices:
            single = _try_route(ev, [c])
            if single is None:
                unrouted.append(c)
            else:
                routes[c] = single

        savings = [
            (float(d[0][i] + d[0][j] - d[i][j]), i, j)
            for i in routes
            for j in routes
            if i < j
        ]
        savings.sort(key=lambda t: -t[0])

        owner = {c: c for c in routes}
        for s, i, j in savings:
            if s <= 0:
                break
            ri, rj = owner.get(i), owner.get(j)
            if ri is None or rj is None or ri == rj:
                continue
            a, b = routes[ri], routes[rj]
            if len(a) + len(b) > instance.n_customers:
                continue
            for merged in (a + b, b + a):
                if merged[0] == 0:
                    continue
                fixed = _try_route(ev, merged)
                if fixed is not None:
                    routes[ri] = fixed
                    del routes[rj]
                    for c in fixed:
                        if not instance.is_station(c):
                            owner[c] = ri
                    break

        final = list(routes.values())
        if len(final) > instance.fleet_size:
            final.sort(key=lambda r: -ev.cost(r))
            overflow = final[instance.fleet_size :]
            final = final[: instance.fleet_size]
            for r in overflow:
                unrouted.extend(c for c in r if not instance.is_station(c))

        meta = {
            "unrouted": sorted(unrouted),
            "simulator_calls": ev.calls,
            "simulator_cache_hits": ev.hits,
        }
        return final, "heuristic", meta


# -- insertion + local search ---------------------------------------------

class InsertionLocalSearchSolver(_HeuristicBase):
    """Sequential cheapest insertion followed by classical local search."""

    name = "insertion-ls"

    def __init__(
        self,
        solver_config: SolverConfig | None = None,
        energy_config: EnergyConfig | None = None,
        charging_config: ChargingConfig | None = None,
        local_search: bool = True,
        max_no_improve: int = 3,
    ) -> None:
        super().__init__(solver_config, energy_config, charging_config)
        self.local_search = local_search
        self.max_no_improve = max_no_improve
        if not local_search:
            self.name = "insertion"

    # -- construction --------------------------------------------------
    def _construct(self, instance: Instance, ev: _RouteEvaluator, rng: random.Random):
        d = instance.distance
        remaining = set(instance.customer_indices)
        routes: list[list[int]] = []
        unrouted: list[int] = []

        while remaining and len(routes) < instance.fleet_size:
            # Seed with the customer whose window closes first, breaking ties by
            # distance from the depot: the classic Solomon I1 seed rule.
            seed = min(remaining, key=lambda c: (instance.nodes[c].due_time, -d[0][c]))
            route = _try_route(ev, [seed])
            remaining.discard(seed)
            if route is None:
                unrouted.append(seed)
                continue

            while True:
                best: tuple[float, list[int], int] | None = None
                for c in remaining:
                    for pos in range(len(route) + 1):
                        candidate = route[:pos] + [c] + route[pos:]
                        prev = route[pos - 1] if pos > 0 else 0
                        nxt = route[pos] if pos < len(route) else 0
                        delta = float(d[prev][c] + d[c][nxt] - d[prev][nxt])
                        if best is not None and delta >= best[0]:
                            continue
                        if ev.feasible(candidate):
                            best = (delta, candidate, c)
                if best is None:
                    break
                route = best[1]
                remaining.discard(best[2])

            routes.append(route)

        unrouted.extend(sorted(remaining))
        return routes, unrouted

    # -- local search ---------------------------------------------------
    def _local_search(self, instance, ev, routes, is_expired) -> list[list[int]]:
        improved = True
        while improved and not is_expired():
            improved = False
            improved |= self._intra_route(ev, routes, is_expired)
            improved |= self._relocate(instance, ev, routes, is_expired)
            improved |= self._swap(instance, ev, routes, is_expired)
        return [r for r in routes if r]

    def _intra_route(self, ev, routes, is_expired) -> bool:
        """2-opt and Or-opt inside each route (first improvement)."""
        changed = False
        for idx, route in enumerate(routes):
            n = len(route)
            if n < 3:
                continue
            base = ev.cost(route)
            done = False
            for i in range(n - 1):
                if is_expired():
                    return changed
                for j in range(i + 2, n + 1):
                    cand = route[:i] + route[i:j][::-1] + route[j:]
                    if ev.feasible(cand) and ev.cost(cand) < base - 1e-9:
                        routes[idx] = cand
                        changed = done = True
                        break
                if done:
                    break
            if done:
                continue
            for seg in (1, 2, 3):
                for i in range(n - seg + 1):
                    if is_expired():
                        return changed
                    chunk = route[i : i + seg]
                    rest = route[:i] + route[i + seg :]
                    for pos in range(len(rest) + 1):
                        if pos == i:
                            continue
                        cand = rest[:pos] + chunk + rest[pos:]
                        if ev.feasible(cand) and ev.cost(cand) < base - 1e-9:
                            routes[idx] = cand
                            changed = done = True
                            break
                    if done:
                        break
                if done:
                    break
        return changed

    def _relocate(self, instance, ev, routes, is_expired) -> bool:
        """Move one customer to another route if the pair gets cheaper."""
        changed = False
        for a in range(len(routes)):
            for b in range(len(routes)):
                if a == b or is_expired():
                    continue
                ra, rb = routes[a], routes[b]
                if not ra:
                    continue
                base = ev.cost(ra) + ev.cost(rb)
                moved = False
                for i, node in enumerate(ra):
                    if instance.is_station(node):
                        continue
                    new_a = ra[:i] + ra[i + 1 :]
                    for pos in range(len(rb) + 1):
                        new_b = rb[:pos] + [node] + rb[pos:]
                        if ev.feasible(new_a) and ev.feasible(new_b):
                            if ev.cost(new_a) + ev.cost(new_b) < base - 1e-9:
                                routes[a], routes[b] = new_a, new_b
                                changed = moved = True
                                break
                    if moved:
                        break
        return changed

    def _swap(self, instance, ev, routes, is_expired) -> bool:
        """Exchange two customers between routes."""
        changed = False
        for a in range(len(routes)):
            for b in range(a + 1, len(routes)):
                if is_expired():
                    return changed
                ra, rb = routes[a], routes[b]
                if not ra or not rb:
                    continue
                base = ev.cost(ra) + ev.cost(rb)
                done = False
                for i, na in enumerate(ra):
                    if instance.is_station(na):
                        continue
                    for j, nb in enumerate(rb):
                        if instance.is_station(nb):
                            continue
                        new_a = ra[:i] + [nb] + ra[i + 1 :]
                        new_b = rb[:j] + [na] + rb[j + 1 :]
                        if (
                            ev.feasible(new_a)
                            and ev.feasible(new_b)
                            and ev.cost(new_a) + ev.cost(new_b) < base - 1e-9
                        ):
                            routes[a], routes[b] = new_a, new_b
                            changed = done = True
                            break
                    if done:
                        break
        return changed

    def _solve(self, instance: Instance) -> tuple[list[list[int]], str, dict[str, Any]]:
        cfg = self.solver_config
        rng = random.Random(cfg.seed)
        ev = self._evaluator(instance)
        deadline = time.perf_counter() + cfg.time_limit_s

        def is_expired() -> bool:
            return time.perf_counter() >= deadline

        routes, unrouted = self._construct(instance, ev, rng)
        construction_distance = sum(ev.cost(r) for r in routes)

        if self.local_search:
            routes = self._local_search(instance, ev, routes, is_expired)

        meta = {
            "unrouted": unrouted,
            "construction_distance": round(construction_distance, 3),
            "simulator_calls": ev.calls,
            "simulator_cache_hits": ev.hits,
            "local_search": self.local_search,
        }
        return [r for r in routes if r], "heuristic", meta
