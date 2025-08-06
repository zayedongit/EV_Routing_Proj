from typing import List, Dict
from models.ev import ElectricVehicle, Customer, Depot
from utils.distance import haversine_distance
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

class VRPSolver:
    def __init__(self, depot: Depot, customers: List[Customer], vehicle_count: int):
        self.depot = depot
        self.customers = customers
        self.vehicle_count = vehicle_count
        self.vehicles = [
            ElectricVehicle(f"EV{i+1}") 
            for i in range(vehicle_count)
        ]
        
    def create_data_model(self):
        """Create the data model for OR-Tools"""
        data = {}
        data['distance_matrix'] = self._create_distance_matrix()
        data['demands'] = [0] + [c.demand for c in self.customers]  # Include depot demand (0)
        data['time_windows'] = [(int(self.depot.ready_time), int(self.depot.due_date))] + [
            (int(c.ready_time), int(c.due_date)) for c in self.customers
        ]
        data['service_times'] = [0] + [int(c.service_time) for c in self.customers]  # Include depot service time
        data['num_vehicles'] = self.vehicle_count
        data['depot'] = 0  # Depot is index 0
        return data
    
    def _create_distance_matrix(self) -> List[List[float]]:
        """Create distance matrix between all locations"""
        locations = [self.depot] + self.customers
        matrix = []
        for i in range(len(locations)):
            row = []
            for j in range(len(locations)):
                row.append(haversine_distance(
                    locations[i].x, locations[i].y,
                    locations[j].x, locations[j].y
                ))
            matrix.append(row)
        return matrix
    
    def solve(self):
        """Solve the VRP with time windows"""
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
            return int(data['distance_matrix'][from_node][to_node])  # Convert to int
        
        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
        
        # Add Distance constraint
        dimension_name = 'Distance'
        routing.AddDimension(
            transit_callback_index,
            0,  # no slack
            3000,  # vehicle maximum travel distance
            True,  # start cumul to zero
            dimension_name)
        distance_dimension = routing.GetDimensionOrDie(dimension_name)
        distance_dimension.SetGlobalSpanCostCoefficient(100)
        
        # Add Capacity constraint
        def demand_callback(from_index):
            from_node = manager.IndexToNode(from_index)
            return int(data['demands'][from_node])  # Convert to int
        
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
            return int(travel_time + service_time)  # Convert to int
        
        time_callback_index = routing.RegisterTransitCallback(time_callback)
        
        routing.AddDimension(
            time_callback_index,
            30,  # allow waiting time
            1440,  # maximum time per vehicle
            False,  # don't force start cumul to zero
            'Time')
        
        time_dimension = routing.GetDimensionOrDie('Time')
        
        # Add time window constraints for each location except depot
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
        """Extract routes from OR-Tools solution"""
        routes = []
        for vehicle_id in range(data['num_vehicles']):
            index = routing.Start(vehicle_id)
            route = []
            route_distance = 0
            route_load = 0
            
            while not routing.IsEnd(index):
                node_index = manager.IndexToNode(index)
                route.append(node_index)
                route_load += data['demands'][node_index]
                previous_index = index
                index = solution.Value(routing.NextVar(index))
                route_distance += routing.GetArcCostForVehicle(
                    previous_index, index, vehicle_id)
                
            # Only add routes that visit customers (not empty routes)
            if len(route) > 1:  # More than just depot
                routes.append({
                    'vehicle_id': vehicle_id,
                    'route': route,
                    'distance': route_distance,
                    'load': route_load
                })
        return routes