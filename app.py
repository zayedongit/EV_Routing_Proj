from visualization.streamlit_dashboard import show_dashboard
from parsers.solomon_parser import parse_solomon_dataset
from solver.task2_vrp_discharge_solver import VRPDischargeSolver
from models.ev import GridStation
import streamlit as st

def main():
    st.set_page_config(page_title="EV Routing", layout="wide")
    
    # Load sample data
    data_file = "data/C101.txt"
    depot, customers = parse_solomon_dataset(data_file)
    
    # Create some grid stations
    grid_stations = [
        GridStation(id=1, x=40, y=50),
        GridStation(id=2, x=60, y=60)
    ]
    
    # Solve the problem
    solver = VRPDischargeSolver(depot, customers, grid_stations, vehicle_count=5)
    routes = solver.solve()
    
    # Show dashboard
    show_dashboard(depot, customers, grid_stations, routes)

if __name__ == "__main__":
    main()