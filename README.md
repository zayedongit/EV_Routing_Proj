# EV Routing Optimization

**Vehicle Routing Problem (VRP) solvers for electric-vehicle fleets — with time windows and vehicle-to-grid (V2G) discharge — plus an interactive Streamlit dashboard.**

This project plans efficient delivery routes for a fleet of electric vehicles under real-world constraints, and adds a second mode where EVs can **discharge power back to the grid at grid stations during peak-demand hours** while still completing their deliveries.

---

## What it does

Two solver variants, built over the standard **Solomon VRP benchmark** format:

1. **Basic VRP with time windows** — assign customers to vehicles and order each route to minimize total distance/cost while respecting vehicle capacity and each customer's ready/due time window.
2. **VRP with grid discharge (V2G)** — the same routing problem, extended so vehicles can route via **grid stations** and feed energy back to the grid during configurable peak-hour windows, trading a little routing efficiency for grid support.

Both produce route plans and rendered route maps; the Streamlit app makes the whole thing interactive.

---

## Interactive dashboard (`app.py`)

A Streamlit web app to configure, solve, and compare scenarios without touching code:

- **Data sources** — built-in sample data, your own CSV upload, or the bundled Solomon datasets. CSV column names are auto-normalized (e.g. `CustomerID` / `CUST NO.` / `customer_id` → `id`) so messy inputs just work.
- **Configurable fleet** — number of vehicles (1–10), vehicle capacity (50–500 kg), battery capacity (50–200 kWh), and the peak-hour discharge windows.
- **Visual output** — route maps of vehicle paths and customer locations, summary metrics (total cost, distance, vehicles deployed, customers served), battery gauges, and radar charts comparing route characteristics.

---

## Project structure

```
EV_Routing_Proj/
├── main.py                         # CLI pipeline: solve both variants, save route plots to outputs/
├── app.py                          # Streamlit dashboard
├── data_utils.py                   # data helpers
├── parsers/
│   └── solomon_parser.py           # parse Solomon-format datasets (depot + customers)
├── solver/
│   ├── task1_vrp_solver.py         # basic VRP with time windows
│   └── task2_vrp_discharge_solver.py  # VRP + grid-discharge (V2G) variant
├── models/
│   └── ev.py                       # EV / GridStation domain models
├── visualization/
│   └── map_plotter.py              # route + grid-station map rendering
├── data/                           # Solomon datasets (e.g. C101.csv)
├── utils/  ·  assets/  ·  outputs/
└── requirements.txt
```

---

## Getting started

**Prerequisites:** Python 3.10+

```bash
git clone https://github.com/zayedongit/EV_Routing_Proj.git
cd EV_Routing_Proj
pip install -r requirements.txt
```

**Run the interactive dashboard:**
```bash
streamlit run app.py
```

**Or run the CLI pipeline** (solves both variants on `data/C101.csv` and writes plots to `outputs/`):
```bash
python main.py
```

You'll get `outputs/basic_vrp_routes.png` and `outputs/discharge_vrp_routes.png`.

---

## Data format

Uses the **Solomon VRP benchmark** convention — a depot plus customers, each with `x`, `y`, `demand`, `ready_time`, `due_time`, and `service_time`. Bring your own CSV (columns are auto-normalized) or use the bundled datasets in `data/`.

---

## Tech stack

Python · Google OR-Tools · Streamlit · Pandas · Matplotlib

---

## Notes

Built to explore how electric-fleet routing changes when vehicles are treated not just as consumers of energy but as **mobile grid assets** that can support the grid during peak load — a small step toward vehicle-to-grid-aware logistics.
