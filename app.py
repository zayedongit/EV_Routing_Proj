"""Streamlit dashboard for the EV routing engine.

Keeps the original app's shape -- sidebar configuration, a route map, per-vehicle
detail -- and adds what the routing engine can now answer:

* which solver you want, and how the choices compare on the same instance;
* the state-of-charge trace of the plan, with the reserve floor drawn in;
* an explicit feasibility verdict from the independent simulator, including
  which constraint was violated and by how much when it fails;
* charging stops and the energy bought at each one;
* the vehicle-to-grid decision, priced against the detour it costs.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent))

from evrp.config import ChargingConfig, EnergyConfig, SolverConfig, VehicleSpec
from evrp.energy import EnergyModel
from evrp.instance import InstanceError, Instance, load_solomon
from evrp.solvers import available, create
from evrp.solvers.base import SolverError
from evrp.stations import generate_stations
from evrp.v2g import apply_v2g
from evrp.viz import plot_fleet_soc, plot_solution

DATA_DIR = Path(__file__).resolve().parent / "data"

st.set_page_config(
    page_title="EV Route - energy-aware fleet routing",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    :root {
        --primary: #4C9AFF; --success: #3ED598; --warning: #FFB020; --error: #FF6B5A;
        --background: #0E1013; --background-secondary: #1C1F24;
        --background-tertiary: #2C2F35; --text-primary: #F2F4F7;
        --text-secondary: #9AA4B2; --border-color: #2E333A;
        --font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        --radius-md: 12px; --radius-lg: 16px;
    }
    .stApp { background: var(--background); color: var(--text-primary); }
    h1, h2, h3, h4 { font-family: var(--font-family); color: var(--text-primary); font-weight: 600; }
    .main .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    [data-testid="stSidebar"] {
        background-color: var(--background-secondary);
        border-right: 1px solid var(--border-color);
    }
    .stButton > button {
        background: var(--primary); color: #0E1013; border-radius: var(--radius-md);
        padding: 10px 22px; font-weight: 600; border: none; min-height: 44px;
        transition: all 0.2s ease;
    }
    .stButton > button:hover { filter: brightness(1.1); transform: translateY(-1px); }
    div[data-testid="stMetric"] {
        background-color: var(--background-secondary); border: 1px solid var(--border-color);
        padding: 1rem 1.2rem; border-radius: var(--radius-lg);
    }
    #MainMenu, footer, header { visibility: hidden; }
</style>
""",
    unsafe_allow_html=True,
)


# -- data ------------------------------------------------------------------

def list_instances() -> list[str]:
    return sorted(p.stem for p in DATA_DIR.glob("*.csv"))


def solomon_capacity_for(name: str) -> int:
    from evrp.benchmark import solomon_capacity

    try:
        return solomon_capacity(name)
    except KeyError:
        return 200


def build_instance(source, name, vehicle, fleet_size, n_stations, station_power,
                   strategy, seed) -> Instance:
    base = load_solomon(source, name=name, vehicle=vehicle, fleet_size=fleet_size)
    if n_stations <= 0 or strategy == "none":
        return base
    stations = generate_stations(
        base, n_stations=n_stations, strategy=strategy,
        power_kw=station_power, seed=seed,
    )
    return base.with_stations(stations)


def battery_gauge(fraction: float, label: str = "Lowest state of charge"):
    percent = max(0.0, min(100.0, fraction * 100.0))
    colour = "#3ED598" if percent > 30 else ("#FFB020" if percent > 12 else "#FF6B5A")
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=percent,
            number={"suffix": "%", "font": {"size": 40, "family": "Inter"}},
            title={"text": label, "font": {"size": 16, "family": "Inter"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#9AA4B2"},
                "bar": {"color": colour},
                "bgcolor": "rgba(0,0,0,0)",
                "borderwidth": 1,
                "bordercolor": "#2E333A",
            },
        )
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", font={"color": "#F2F4F7", "family": "Inter"},
        height=240, margin=dict(l=20, r=20, t=50, b=10),
    )
    return fig


def comparison_chart(rows: list[dict]):
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[r["solver"] for r in rows],
            y=[r["distance_km"] for r in rows],
            marker_color=["#4C9AFF" if r["feasible"] else "#FF6B5A" for r in rows],
            text=[f"{r['distance_km']:.0f} km" for r in rows],
            textposition="outside",
        )
    )
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", height=330,
        yaxis_title="Total distance (km)", xaxis_title="",
        margin=dict(l=20, r=20, t=30, b=20),
    )
    return fig


# -- sidebar ---------------------------------------------------------------

with st.sidebar:
    st.header("⚡ EV Route")

    source_kind = st.selectbox(
        "Data source", ["Solomon instance", "Upload CSV"],
        help="Solomon benchmark instances ship with the project.",
    )
    uploaded = None
    instance_name = "C101"
    if source_kind == "Solomon instance":
        instance_name = st.selectbox("Instance", list_instances(), index=0)
    else:
        uploaded = st.file_uploader("Solomon-format CSV", type=["csv"])

    st.header("🚚 Fleet")
    fleet_size = st.slider("Vehicles available", 1, 40, 25)
    default_capacity = solomon_capacity_for(instance_name)
    capacity = st.number_input(
        "Payload capacity", min_value=10, max_value=2000, value=int(default_capacity),
        step=10, help="Solomon prescribes 200 for C1/R1/RC1, 700 for C2, 1000 for R2/RC2.",
    )

    st.header("🔋 Battery")
    battery = st.slider("Usable pack (kWh)", 8.0, 120.0, 40.0, step=1.0)
    reserve = st.slider("Reserve held back", 0.0, 0.4, 0.10, step=0.05)
    consumption = st.slider("Consumption (kWh/km, empty)", 0.10, 0.50, 0.22, step=0.01)

    st.header("🔌 Charging")
    n_stations = st.slider("Charging stations", 0, 15, 6)
    station_power = st.select_slider("Charger power (kW)", [7.4, 11.0, 22.0, 50.0, 150.0], 50.0)
    station_strategy = st.selectbox("Placement", ["kmeans", "grid", "random", "none"])
    curve = st.selectbox("Charging curve", ["piecewise", "linear"],
                         help="Piecewise approximates CC-CV tapering above 80 %.")

    st.header("🏭 Grid discharge (V2G)")
    enable_v2g = st.checkbox("Price V2G detours after routing", value=False)
    v2g_price = st.number_input("V2G price ($/kWh)", 0.0, 5.0, 0.55, step=0.05)
    energy_price = st.number_input("Charging price ($/kWh)", 0.0, 5.0, 0.18, step=0.01)

    st.header("🧠 Solver")
    solvers = st.multiselect("Solvers to run", available(), default=["ortools", "insertion-ls"])
    time_limit = st.slider("Time limit per solver (s)", 1, 120, 15)
    seed = st.number_input("Random seed", 0, 10_000, 42, step=1)

    run = st.button("🚀 Optimise routes", type="primary", use_container_width=True)


# -- solve -----------------------------------------------------------------

def resolve_source():
    if source_kind == "Upload CSV":
        if uploaded is None:
            return None, None
        return uploaded, Path(uploaded.name).stem
    return str(DATA_DIR / f"{instance_name}.csv"), instance_name


if run:
    source, name = resolve_source()
    if source is None:
        st.sidebar.warning("Upload a CSV, or switch back to a Solomon instance.")
    elif not solvers:
        st.sidebar.warning("Pick at least one solver.")
    else:
        try:
            vehicle = VehicleSpec(
                payload_capacity=float(capacity),
                battery_kwh=float(battery),
                reserve_soc=float(reserve),
            )
            energy_cfg = EnergyConfig(base_kwh_per_km=float(consumption))
            charging_cfg = ChargingConfig(
                curve=curve, energy_price=float(energy_price),
                v2g_price=float(v2g_price), v2g_enabled=bool(enable_v2g),
            )
            solver_cfg = SolverConfig(time_limit_s=float(time_limit), seed=int(seed))

            instance = build_instance(
                source, name, vehicle, int(fleet_size), int(n_stations),
                float(station_power), station_strategy, int(seed),
            )

            results = {}
            progress = st.progress(0.0, text="Solving...")
            for i, solver_name in enumerate(solvers, start=1):
                progress.progress(i / len(solvers), text=f"Running {solver_name}...")
                try:
                    results[solver_name] = create(
                        solver_name, solver_config=solver_cfg,
                        energy_config=energy_cfg, charging_config=charging_cfg,
                    ).solve(instance)
                except SolverError as exc:
                    st.warning(f"{solver_name}: {exc}")
            progress.empty()

            if results:
                st.session_state.update(
                    instance=instance, results=results, energy_cfg=energy_cfg,
                    charging_cfg=charging_cfg, enable_v2g=bool(enable_v2g),
                )
            else:
                st.error("No solver produced a solution for this configuration.")
        except (InstanceError, FileNotFoundError, ValueError) as exc:
            st.error(f"Could not build the problem: {exc}")
        except Exception as exc:  # pragma: no cover - surfaced in the UI
            st.error(f"Unexpected error: {exc}")
            st.code(traceback.format_exc())


# -- main ------------------------------------------------------------------

st.title("Energy-aware EV fleet routing")

if "results" not in st.session_state:
    st.info(
        "Configure the fleet, battery and charging network in the sidebar, then "
        "press **Optimise routes**. Every result is re-checked by an independent "
        "route simulator before it is shown."
    )
    left, right = st.columns(2)
    with left:
        st.subheader("What the model enforces")
        st.markdown(
            "- delivery **time windows** and vehicle **capacity**\n"
            "- **state of charge**, never below the reserve you set\n"
            "- **charging stops** as a decision, with the time they cost\n"
            "- a **CC-CV charging curve**, so topping up past 80 % is slow\n"
            "- **payload-dependent consumption** — a full van uses more per km"
        )
    with right:
        st.subheader("How results are checked")
        st.markdown(
            "Routes come out of the solver and go straight into a simulator that "
            "shares no code with it. The simulator replays the route stop by stop "
            "and reports the exact violation if there is one, so a solver cannot "
            "mark its own homework."
        )
else:
    instance: Instance = st.session_state["instance"]
    results = st.session_state["results"]
    energy_cfg = st.session_state["energy_cfg"]
    charging_cfg = st.session_state["charging_cfg"]

    model = EnergyModel(energy_cfg, instance.vehicle)
    feasible = [s for s in results.values() if s.feasible]
    best = min(
        feasible or results.values(), key=lambda s: s.metrics.total_distance
    )

    st.caption(
        f"{instance.name} · {instance.n_customers} customers · "
        f"{len(instance.stations)} chargers · "
        f"{instance.vehicle.battery_kwh:g} kWh pack "
        f"({model.full_range_km:.0f} km empty, "
        f"{model.range_km(instance.vehicle.battery_kwh, instance.vehicle.payload_capacity):.0f} km loaded)"
    )

    m = best.metrics
    cols = st.columns(5)
    cols[0].metric("Distance", f"{m.total_distance:,.1f} km")
    cols[1].metric("Vehicles", m.vehicles_used)
    cols[2].metric("Customers", f"{m.customers_served}/{m.customers_total}")
    cols[3].metric("Charging stops", m.charging_stops,
                   help=f"{m.energy_charged_kwh:.1f} kWh bought, "
                        f"{m.total_charge_time:.0f} min plugged in")
    cols[4].metric("Energy used", f"{m.energy_consumed_kwh:,.1f} kWh")

    if best.feasible:
        st.success(f"**{best.solver}** — verified feasible by the route simulator.")
    else:
        st.error(
            f"**{best.solver}** — the simulator rejected this plan: "
            f"{m.n_violations} violation(s), "
            f"{m.customers_total - m.customers_served} customer(s) unserved."
        )
        with st.expander("What went wrong", expanded=True):
            for violation in best.violations[:20]:
                st.write(f"- {violation}")

    tabs = st.tabs(["🗺️ Routes", "🔋 State of charge", "⚖️ Solver comparison",
                    "📋 Route details", "🏭 Grid discharge"])

    with tabs[0]:
        st.pyplot(plot_solution(instance, best), use_container_width=True)

    with tabs[1]:
        left, right = st.columns([2, 1])
        with left:
            st.pyplot(plot_fleet_soc(instance, best), use_container_width=True)
        with right:
            st.plotly_chart(
                battery_gauge(m.min_soc_kwh / instance.vehicle.battery_kwh),
                use_container_width=True,
            )
            st.metric("Reserve floor", f"{instance.vehicle.min_soc_kwh:.1f} kWh")
            st.metric("Time plugged in", f"{m.total_charge_time:.0f} min")
            st.metric("Energy bought", f"{m.energy_charged_kwh:.1f} kWh "
                                       f"(${m.energy_cost:,.2f})")

    with tabs[2]:
        rows = [
            {
                "solver": name,
                "distance_km": s.metrics.total_distance,
                "vehicles": s.metrics.vehicles_used,
                "charging_stops": s.metrics.charging_stops,
                "customers_served": s.metrics.customers_served,
                "runtime_s": round(s.runtime_s, 2),
                "feasible": s.feasible,
            }
            for name, s in results.items()
        ]
        st.plotly_chart(comparison_chart(rows), use_container_width=True)
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("Red bars are plans the simulator rejected; their distance is not comparable.")

    with tabs[3]:
        for i, sim in enumerate(best.simulations):
            if not sim.stops:
                continue
            flag = "" if sim.feasible else "  ⚠️"
            with st.expander(
                f"EV {i + 1} — {sim.n_customers} customers, {sim.distance:.1f} km, "
                f"{sim.n_charging_stops} charging stops{flag}"
            ):
                frame = pd.DataFrame(
                    [
                        {
                            "stop": ("depot" if s.node == 0 else
                                     f"charger {s.node}" if instance.is_station(s.node)
                                     else f"customer {s.node}"),
                            "arrive": round(s.arrival, 1),
                            "wait": round(s.wait, 1),
                            "depart": round(s.departure, 1),
                            "SoC in (kWh)": round(s.soc_arrival, 2),
                            "charged (kWh)": round(s.charged_kwh, 2),
                            "SoC out (kWh)": round(s.soc_departure, 2),
                            "payload": round(s.payload_on_arrival, 1),
                        }
                        for s in sim.stops
                    ]
                )
                st.dataframe(frame, use_container_width=True, hide_index=True)
                for violation in sim.violations:
                    st.warning(str(violation))

    with tabs[4]:
        if not st.session_state.get("enable_v2g"):
            st.info(
                "Enable **Price V2G detours after routing** in the sidebar. The "
                "engine then prices, for every route, the most profitable detour "
                "to a charger that can absorb energy: the amount sellable is "
                "decided by a linear program over the route's schedule, and the "
                "detour is only taken if the revenue beats the extra kilometres."
            )
        elif not instance.stations:
            st.info("Add at least one charging station to enable grid discharge.")
        else:
            with st.spinner("Pricing V2G detours..."):
                v2g_solution, report = apply_v2g(
                    instance, best, energy_cfg, charging_cfg
                )
            payload = report.to_dict()
            cols = st.columns(4)
            cols[0].metric("Routes selling energy", payload["routes_with_v2g"])
            cols[1].metric("Energy sold", f"{payload['discharged_kwh']:.1f} kWh")
            cols[2].metric("Extra distance", f"{payload['extra_km']:.2f} km")
            cols[3].metric("Net gain", f"${payload['net_gain']:,.2f}")
            if payload["routes_with_v2g"]:
                st.pyplot(plot_solution(instance, v2g_solution), use_container_width=True)
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "route": d.route_index + 1,
                                "charger": d.station,
                                "detour_km": round(d.detour_km, 2),
                                "sold_kwh": round(d.discharged_kwh, 2),
                                "revenue": round(d.revenue, 2),
                                "net_gain": round(d.net_gain, 2),
                            }
                            for d in report.accepted
                        ]
                    ),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.info(
                    "No detour paid for itself at these prices. Raise the V2G "
                    "price, add chargers, or give the vehicles a bigger pack so "
                    "there is surplus energy to sell."
                )
