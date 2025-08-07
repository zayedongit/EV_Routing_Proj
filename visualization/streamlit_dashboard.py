import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import json
from typing import List, Dict, Any

# Assuming these models are correctly defined in your 'models/ev.py' file
from models.ev import Depot, Customer, GridStation

def show_dashboard(depot: Depot, customers: List[Customer],
                   grid_stations: List[GridStation], routes: List[Dict[str, Any]]) -> None:
    """
    Display interactive dashboard with routing results.

    Args:
        depot: Central depot information
        customers: List of customer locations
        grid_stations: List of grid discharge stations
        routes: List of route solutions from solver
    """
    st.set_page_config(layout="wide")
    st.title("🚚 EV Fleet Routing Dashboard")

    # Summary statistics
    total_distance = sum(r['distance'] for r in routes)
    total_energy_sold = sum(r.get('energy_sold', 0) for r in routes)
    total_revenue = sum(r.get('revenue', 0) for r in routes)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Distance (km)", f"{total_distance:.1f}")
    col2.metric("Energy Sold (kWh)", f"{total_energy_sold:.1f}")
    col3.metric("Revenue ($)", f"${total_revenue:.2f}")

    # Route visualization
    st.subheader("Route Visualization")
    fig = plot_routes(depot, customers, grid_stations, routes)
    st.pyplot(fig)

    # Vehicle details
    st.subheader("Vehicle Route Details")
    vehicle_data = []
    for route in routes:
        stops = []
        for node_data in route['route']:
            node = node_data['node'] if isinstance(node_data, dict) else node_data
            is_grid = node_data.get('is_grid', False) if isinstance(node_data, dict) else False

            if is_grid:
                stops.append("⚡ Grid")
            elif node == 0:
                stops.append("🏭 Depot")
            else:
                stops.append(f"🏠 C{node}")

        vehicle_data.append({
            "Vehicle": f"EV{route['vehicle_id'] + 1}",
            "Route": " → ".join(stops),
            "Distance (km)": f"{route['distance']:.1f}",
            "Load (kg)": f"{route['load']:.1f}",
            "Energy Sold (kWh)": f"{route.get('energy_sold', 0):.1f}",
            "Revenue ($)": f"${route.get('revenue', 0):.2f}"
        })
    st.dataframe(pd.DataFrame(vehicle_data), use_container_width=True)

    # Sustainability metrics
    st.subheader("Sustainability Impact")
    co2_saved = total_distance * 0.13  # 0.13kg/km saved vs diesel
    col1, col2 = st.columns(2)
    col1.metric("CO₂ Savings", f"{co2_saved:.1f} kg")
    col2.metric("Equivalent Trees", f"{co2_saved / 21:.1f}")  # 21kg/tree/year

    # Export functionality
    st.subheader("Data Export")
    if st.button("📤 Export Report (JSON)"):
        try:
            export_report(routes)
            st.success("Report exported successfully!")
        except Exception as e:
            st.error(f"Export failed: {str(e)}")

def export_report(routes: List[Dict[str, Any]]) -> None:
    """
    Export route data to JSON file.

    Args:
        routes: List of route solutions from solver

    Raises:
        Exception: If export fails
    """
    report = {
        "summary": {
            "total_distance": sum(r['distance'] for r in routes),
            "total_energy_sold": sum(r.get('energy_sold', 0) for r in routes),
            "total_revenue": sum(r.get('revenue', 0) for r in routes)
        },
        "vehicles": [
            {
                "vehicle_id": r['vehicle_id'],
                "route": [
                    {
                        "node": (node_data['node'] if isinstance(node_data, dict) else node_data),
                        "type": (
                            "depot"
                            if (node_data['node'] if isinstance(node_data, dict) else node_data) == 0
                            else "grid"
                            if (isinstance(node_data, dict) and node_data.get('is_grid', False))
                            else "customer"
                        )
                    }
                    for node_data in r['route']
                ],
                "distance": r['distance'],
                "load": r['load'],
                "energy_sold": r.get('energy_sold', 0),
                "revenue": r.get('revenue', 0)
            }
            for r in routes
        ]
    }
    with open("ev_routing_report.json", "w") as f:
        json.dump(report, f, indent=2)

def plot_routes(depot: Depot, customers: List[Customer],
                grid_stations: List[GridStation], routes: List[Dict[str, Any]]) -> plt.Figure:
    """
    Generate route visualization plot.

    Args:
        depot: Central depot information
        customers: List of customer locations
        grid_stations: List of grid discharge stations
        routes: List of route solutions
    Returns:
        Matplotlib figure object
    """
    fig, ax = plt.subplots(figsize=(12, 8))

    # Plot depot
    ax.scatter(depot.x, depot.y, c='red', s=200, marker='s', label='Depot', zorder=5)

    # Plot customers
    customer_x = [c.x for c in customers]
    customer_y = [c.y for c in customers]
    ax.scatter(customer_x, customer_y, c='blue', s=50, label='Customers', zorder=4)

    # Plot grid stations
    if grid_stations:
        grid_x = [g.x for g in grid_stations]
        grid_y = [g.y for g in grid_stations]
        ax.scatter(grid_x, grid_y, c='green', s=100, marker='^', label='Grid Stations', zorder=5)

    # Plot routes
    colors = plt.cm.tab10.colors
    for i, route in enumerate(routes):
        color = colors[i % len(colors)]
        path_x = [depot.x]
        path_y = [depot.y]

        for node_data in route['route']:
            node = node_data['node'] if isinstance(node_data, dict) else node_data
            is_grid = node_data.get('is_grid', False) if isinstance(node_data, dict) else False

            if node == 0:  # Depot
                path_x.append(depot.x)
                path_y.append(depot.y)
            elif is_grid:
                try:
                    gs_index = node - len(customers) - 1
                    if 0 <= gs_index < len(grid_stations):
                        gs = grid_stations[gs_index]
                        path_x.append(gs.x)
                        path_y.append(gs.y)
                    else:
                        st.warning(f"Grid station with node index {node} not found. Skipping.")
                except IndexError:
                    st.warning(f"Grid station with node index {node} not found. Skipping.")
            else:  # Customer
                try:
                    cust = customers[node - 1]
                    path_x.append(cust.x)
                    path_y.append(cust.y)
                except IndexError:
                    st.warning(f"Customer with node index {node} not found. Skipping.")

        ax.plot(path_x, path_y, c=color, linestyle='-', linewidth=2, label=f"EV {i+1}", zorder=3)
        ax.scatter(path_x[1:-1], path_y[1:-1], c=color, s=30, zorder=4)

    ax.set_xlabel('X Coordinate')
    ax.set_ylabel('Y Coordinate')
    ax.set_title('Vehicle Routing with Grid Discharge Stations')
    ax.legend()
    ax.grid(True)
    plt.tight_layout()
    return fig