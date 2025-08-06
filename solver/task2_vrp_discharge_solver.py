from typing import List, Dict, Tuple
from models.ev import ElectricVehicle, Customer, Depot, GridStation
from utils.distance import haversine_distance
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

class VRPDischargeSolver:
    def __init__(
        self, 
        depot: Depot, 
        customers: List[Customer], 
        grid_stations: List[GridStation],
        vehicle_count: int,
        energy_price: float = 0.15  # $/kWh
    ):
        self.depot = depot
        self.customers = customers
        self.grid_stations = grid_stations
        self.vehicle_count = vehicle_count
        self.energy_price = energy_price
        self.vehicles = [
            ElectricVehicle(f"EV{i+1}") 
            for i in range(vehicle_count)
        ]
        self.grid_station_indices = []  # Initialize this
        
    def create_data_model(self):
        """Create the data model for OR-Tools including grid stations"""
        data = {}
        all_locations = [self.depot] + self.customers + self.grid_stations
        data['distance_matrix'] = self._create_distance_matrix(all_locations)
        
        # Create demands array: depot=0, customers=their demand, grid_stations=0
        data['demands'] = []
        data['demands'].append(0)  # depot
        data['demands'].extend([c.demand for c in self.customers])  # customers
        data['demands'].extend([0 for _ in self.grid_stations])  # grid stations
        
        # Create time windows
        data['time_windows'] = []
        data['time_windows'].append((int(self.depot.ready_time), int(self.depot.due_date)))  # depot
        data['time_windows'].extend([(int(c.ready_time), int(c.due_date)) for c in self.customers])  # customers
        data['time_windows'].extend([(0, 2304) for _ in self.grid_stations])  # grid stations - open all day
        
        # Service times
        data['service_times'] = []
        data['service_times'].append(0)  # depot
        data['service_times'].extend([int(c.service_time) for c in self.customers])  # customers
        data['service_times'].extend([10 for _ in self.grid_stations])  # grid stations - 10 min service
        
        data['num_vehicles'] = self.vehicle_count
        data['depot'] = 0
        
        # Grid station indices
        self.grid_station_indices = list(range(
            len(self.customers) + 1,  # Start after depot + customers
            len(self.customers) + 1 + len(self.grid_stations)  # End after grid stations
        ))
        data['grid_station_indices'] = self.grid_station_indices
        
        return data
    
    def _create_distance_matrix(self, all_locations) -> List[List[float]]:
        """Create distance matrix between all locations"""
        matrix = []
        for i in range(len(all_locations)):
            row = []
            for j in range(len(all_locations)):
                row.append(haversine_distance(
                    all_locations[i].x, all_locations[i].y,
                    all_locations[j].x, all_locations[j].y
                ))
            matrix.append(row)
        return matrix
    
    def solve(self):
        """Solve the VRP with time windows and grid discharge options"""
        data = self.create_data_model()
        
        # Create routing index manager
        manager = pywrapcp.RoutingIndexManager(
            len(data['distance_matrix']),
            data['num_vehicles'],
            data['depot']
        )
        
        # Create routing model
        routing = pywrapcp.RoutingModel(manager)
        
        # Define cost of each arc
        def distance_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return int(data['distance_matrix'][from_node][to_node])
        
        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
        
        # Add Distance constraint
        routing.AddDimension(
            transit_callback_index,
            0,  # no slack
            3000,  # vehicle maximum travel distance
            True,  # start cumul to zero
            'Distance')
        
        # Add Capacity constraint
        def demand_callback(from_index):
            from_node = manager.IndexToNode(from_index)
            return int(data['demands'][from_node])
        
        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_callback_index,
            0,  # null capacity slack
            [100] * data['num_vehicles'],  # vehicle maximum capacities
            True,  # start cumul to zero
            'Capacity')
        
        # Add Time Window constraint
        def time_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            travel_time = data['distance_matrix'][from_node][to_node] / 50 * 60  # 50km/h
            service_time = data['service_times'][from_node] if from_node != data['depot'] else 0
            return int(travel_time + service_time)
        
        time_callback_index = routing.RegisterTransitCallback(time_callback)
        
        routing.AddDimension(
            time_callback_index,
            30,  # allow waiting time
            1440,  # maximum time per vehicle
            False,  # don't force start cumul to zero
            'Time')
        
        time_dimension = routing.GetDimensionOrDie('Time')
        
        # Add time window constraints for each location
        for location_idx, time_window in enumerate(data['time_windows']):
            if location_idx == data['depot']:
                continue
            index = manager.NodeToIndex(location_idx)
            time_dimension.CumulVar(index).SetRange(time_window[0], time_window[1])
        
        # Add time window constraints for depot
        depot_idx = data['depot']
        for vehicle_id in range(data['num_vehicles']):
            index = routing.Start(vehicle_id)
            time_dimension.CumulVar(index).SetRange(
                int(self.depot.ready_time),
                int(self.depot.due_date)
            )
        
        # Add grid station constraints (only visit during peak hours)
        for grid_idx in data['grid_station_indices']:
            index = manager.NodeToIndex(grid_idx)
            time_dimension.CumulVar(index).SetRange(14*60, 18*60)  # 2PM-6PM
        
        # Setting first solution heuristic
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search_parameters.time_limit.FromSeconds(30)
        
        # Solve the problem
        solution = routing.SolveWithParameters(search_parameters)
        
        # Process the solution
        if solution:
            return self._get_routes(data, manager, routing, solution)
        else:
            raise Exception("No solution found!")
    
    def _get_routes(self, data, manager, routing, solution):
        """Extract routes from OR-Tools solution with grid discharge info"""
        routes = []
        for vehicle_id in range(data['num_vehicles']):
            index = routing.Start(vehicle_id)
            route = []
            route_distance = 0
            route_load = 0
            energy_sold = 0
            revenue = 0
            
            while not routing.IsEnd(index):
                node_index = manager.IndexToNode(index)
                is_grid = node_index in data['grid_station_indices']
                
                if is_grid:
                    # Simulate discharging 10kWh at grid station
                    discharge_amount = 10  # kWh
                    energy_sold += discharge_amount
                    revenue += discharge_amount * self.energy_price
                
                route.append({
                    'node': node_index,
                    'is_grid': is_grid
                })
                
                previous_index = index
                index = solution.Value(routing.NextVar(index))
                route_distance += routing.GetArcCostForVehicle(
                    previous_index, index, vehicle_id)
                
                if not is_grid and node_index != data['depot']:
                    route_load += data['demands'][node_index]
            
            # Only add routes that visit customers (not empty routes)
            if len(route) > 1:  # More than just depot
                routes.append({
                    'vehicle_id': vehicle_id,
                    'route': route,
                    'distance': route_distance,
                    'load': route_load,
                    'energy_sold': energy_sold,
                    'revenue': revenue
                })
        return routes