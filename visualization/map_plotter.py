import matplotlib.pyplot as plt
import matplotlib.patches as patches
from typing import List
from models.ev import Depot, Customer, GridStation

def plot_routes(depot: Depot, customers: List[Customer], grid_stations: List[GridStation], routes: List[dict]):
    """Plot vehicle routes on a map"""
    plt.figure(figsize=(12, 8))
    
    # Plot depot
    plt.scatter(depot.x, depot.y, c='red', s=200, marker='s', label='Depot')
    
    # Plot customers
    customer_x = [c.x for c in customers]
    customer_y = [c.y for c in customers]
    plt.scatter(customer_x, customer_y, c='blue', s=50, label='Customers')
    
    # Plot grid stations
    if grid_stations:
        grid_x = [g.x for g in grid_stations]
        grid_y = [g.y for g in grid_stations]
        plt.scatter(grid_x, grid_y, c='green', s=100, marker='^', label='Grid Stations')
    
    # Plot routes
    colors = plt.cm.tab10.colors
    for i, route in enumerate(routes):
        color = colors[i % len(colors)]
        path_x = [depot.x]
        path_y = [depot.y]
        
        for node_data in route['route']:
            if isinstance(node_data, dict):
                node = node_data['node']
                is_grid = node_data.get('is_grid', False)
            else:
                node = node_data
                is_grid = False
                
            if is_grid and 'x' in node_data and 'y' in node_data:
                path_x.append(node_data['x'])
                path_y.append(node_data['y'])
            elif node == 0:  # Depot
                path_x.append(depot.x)
                path_y.append(depot.y)
            elif node > 0 and node <= len(customers):
                cust = customers[node - 1]
                path_x.append(cust.x)
                path_y.append(cust.y)
        
        plt.plot(path_x, path_y, c=color, linestyle='-', linewidth=2, label=f"EV {i+1}")
    
    plt.xlabel('X Coordinate')
    plt.ylabel('Y Coordinate')
    plt.title('Vehicle Routing with Grid Discharge Stations')
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    return plt.gcf()  # Return figure for Streamlit