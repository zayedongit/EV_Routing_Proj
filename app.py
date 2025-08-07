import streamlit as st

# Importing necessary components from your project structure
from visualization.streamlit_dashboard import show_dashboard
from parsers.solomon_parser import parse_solomon_dataset
from solver.task2_vrp_discharge_solver import VRPDischargeSolver
from models.ev import GridStation # Correct import for GridStation

def main():
    st.set_page_config(page_title="EV Routing", layout="wide")

    # Load sample data
    # Ensure 'data/C101.csv' exists relative to where app.py is run
    data_file = "data/C101.csv"
    depot, customers = parse_solomon_dataset(data_file)

    # Create some grid stations
    grid_stations = [
        GridStation(id=1, x=40, y=50),
        GridStation(id=2, x=60, y=60)
    ]

    # Solve the problem
    # MODIFICATION: Increased vehicle_count to make the problem potentially more feasible
    solver = VRPDischargeSolver(depot, customers, grid_stations, vehicle_count=10) # Changed from 5 to 10
    routes = solver.solve()

    # Show dashboard
    show_dashboard(depot, customers, grid_stations, routes)

if __name__ == "__main__":
    main()
