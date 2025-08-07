import matplotlib.pyplot as plt
import os

# Importing necessary components from your project structure
from parsers.solomon_parser import parse_solomon_dataset
from solver.task1_vrp_solver import VRPSolver
from solver.task2_vrp_discharge_solver import VRPDischargeSolver
from visualization.map_plotter import plot_routes
from models.ev import GridStation # Correct import for GridStation

def main():
    # Ensure the 'outputs' directory exists for saving plots
    output_dir = "outputs"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Example usage
    # Ensure 'data/C101.csv' exists relative to where main.py is run
    data_file = "data/C101.csv"
    depot, customers = parse_solomon_dataset(data_file)

    # Task 1: Basic VRP
    print("Solving basic VRP...")
    # MODIFICATION: Increased vehicle_count to make the problem potentially more feasible
    solver1 = VRPSolver(depot, customers, vehicle_count=10) # Changed from 5 to 10
    routes1 = solver1.solve()

    # Visualize routes
    fig = plot_routes(depot, customers, [], routes1)
    plt.savefig(os.path.join(output_dir, "basic_vrp_routes.png"))
    print(f"Basic VRP solution saved to {os.path.join(output_dir, 'basic_vrp_routes.png')}")
    plt.close(fig) # Close the figure to free up memory

    # Task 2: VRP with Grid Discharge
    print("\nSolving VRP with grid discharge...")
    grid_stations = [
        GridStation(id=1, x=40, y=50),
        GridStation(id=2, x=60, y=60)
    ]
    # MODIFICATION: Increased vehicle_count to make the problem potentially more feasible
    solver2 = VRPDischargeSolver(depot, customers, grid_stations, vehicle_count=10) # Changed from 5 to 10
    routes2 = solver2.solve()

    # Visualize routes with grid stations
    fig = plot_routes(depot, customers, grid_stations, routes2)
    plt.savefig(os.path.join(output_dir, "discharge_vrp_routes.png"))
    print(f"Discharge VRP solution saved to {os.path.join(output_dir, 'discharge_vrp_routes.png')}")
    plt.close(fig) # Close the figure to free up memory

if __name__ == "__main__":
    main()
