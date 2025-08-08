import matplotlib.pyplot as plt
from typing import List
from models.ev import Depot, Customer, GridStation

def plot_routes(depot: Depot, customers: List[Customer], grid_stations: List[GridStation], routes: List[dict]):
    """Plot vehicle routes on a map with a dark theme aesthetic"""
    fig, ax = plt.subplots(figsize=(14, 10))
    fig.patch.set_facecolor('#1C1C1E')
    ax.set_facecolor('#1C1C1E')

    # Plot depot
    ax.scatter(depot.x, depot.y, c='#FF453A', s=250, marker='s', label='Depot', zorder=5, edgecolors='#FFFFFF', linewidth=2)

    # Plot customers
    customer_x = [c.x for c in customers]
    customer_y = [c.y for c in customers]
    ax.scatter(customer_x, customer_y, c='#0A84FF', s=80, label='Customers', zorder=4, alpha=0.9)

    # Plot grid stations (if any)
    if grid_stations:
        grid_x = [g.x for g in grid_stations]
        grid_y = [g.y for g in grid_stations]
        ax.scatter(grid_x, grid_y, c='#30D158', s=200, marker='^', label='Grid Stations', zorder=5, edgecolors='#FFFFFF', linewidth=2)

    # Plot routes
    colors = plt.cm.get_cmap('viridis', len(routes) if routes else 1)
    for i, route_info in enumerate(routes):
        if route_info['customers_served'] > 0:
            route = route_info['route']
            color = colors(i)
            
            # Create a list of all points in the route including the depot
            all_points_x = [depot.x] + [customers[node - 1].x for node in route if node != 0] + [depot.x]
            all_points_y = [depot.y] + [customers[node - 1].y for node in route if node != 0] + [depot.y]
            
            ax.plot(all_points_x, all_points_y, color=color, linestyle='-', linewidth=2.5, label=f"EV {i+1}", zorder=3, alpha=0.9)

    # Style the plot for dark theme
    ax.set_xlabel('X Coordinate', fontsize=12, color='white')
    ax.set_ylabel('Y Coordinate', fontsize=12, color='white')
    ax.set_title('EV Routing Solution', fontsize=18, fontweight='bold', color='white')
    
    legend = ax.legend(frameon=True, facecolor='#2C2C2E', edgecolor='#38383A')
    for text in legend.get_texts():
        text.set_color("white")
        
    ax.tick_params(axis='x', colors='white')
    ax.tick_params(axis='y', colors='white')
    ax.grid(color='#38383A', linestyle='--', linewidth=0.5)
    
    # Set border colors
    for spine in ax.spines.values():
        spine.set_edgecolor('#38383A')

    plt.tight_layout()
    return fig