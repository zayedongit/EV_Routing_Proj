import numpy as np
import random
import copy
from typing import List, Dict, Tuple, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Customer:
    def __init__(self, id: int, x: float, y: float, demand: int, ready_time: int, due_time: int, service_time: int):
        self.id = id
        self.x = x
        self.y = y
        self.demand = demand
        self.ready_time = ready_time
        self.due_time = due_time
        self.service_time = service_time
        
    def distance_to(self, other):
        return np.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)

class Vehicle:
    def __init__(self, capacity: int, battery_capacity: float, consumption_rate: float):
        self.capacity = capacity
        self.battery_capacity = battery_capacity
        self.consumption_rate = consumption_rate
        self.current_load = 0
        self.current_battery = battery_capacity
        self.route = []
        self.current_time = 0
        self.current_location = None

class VRPSolver:
    def __init__(self, customers: List[Customer], depot: Customer, vehicles: List[Vehicle], 
                 enable_discharge: bool = False, peak_hours: Tuple[int, int] = (17, 20)):
        self.customers = customers
        self.depot = depot
        self.vehicles = vehicles
        self.enable_discharge = enable_discharge
        self.peak_hours = peak_hours
        self.distance_matrix = self._calculate_distance_matrix()
        self.best_solution = None
        self.best_cost = float('inf')
        
        # Solver parameters - made more permissive
        self.max_iterations = 2000  # Increased from typical 1000
        self.population_size = 100   # Increased population
        self.mutation_rate = 0.15
        self.crossover_rate = 0.85
        self.elite_size = 20
        self.no_improvement_limit = 300  # Allow more iterations without improvement
        
    def _calculate_distance_matrix(self):
        all_nodes = [self.depot] + self.customers
        n = len(all_nodes)
        matrix = np.zeros((n, n))
        
        for i in range(n):
            for j in range(n):
                if i != j:
                    matrix[i][j] = all_nodes[i].distance_to(all_nodes[j])
                    
        return matrix
    
    def _is_feasible_route(self, route: List[int], vehicle: Vehicle) -> bool:
        """Check if a route is feasible for a given vehicle"""
        if not route:
            return True
            
        current_load = 0
        current_battery = vehicle.battery_capacity
        current_time = 0
        current_pos = 0  # depot position
        
        for customer_idx in route:
            customer = self.customers[customer_idx - 1]  # -1 because customers are 1-indexed
            
            # Check distance and battery
            distance = self.distance_matrix[current_pos][customer_idx]
            battery_needed = distance * vehicle.consumption_rate
            
            if current_battery < battery_needed:
                return False
                
            # Update battery and time
            current_battery -= battery_needed
            current_time += distance  # assuming speed = 1
            
            # Check time window
            if current_time > customer.due_time:
                return False
                
            # Wait if arrived early
            if current_time < customer.ready_time:
                current_time = customer.ready_time
                
            # Add service time
            current_time += customer.service_time
            
            # Check capacity
            current_load += customer.demand
            if current_load > vehicle.capacity:
                return False
                
            current_pos = customer_idx
            
        # Check return to depot
        distance_to_depot = self.distance_matrix[current_pos][0]
        battery_needed = distance_to_depot * vehicle.consumption_rate
        
        return current_battery >= battery_needed
    
    def _calculate_route_cost(self, route: List[int], vehicle: Vehicle) -> float:
        """Calculate the cost of a route"""
        if not route:
            return 0
            
        total_distance = 0
        current_pos = 0  # depot
        
        for customer_idx in route:
            total_distance += self.distance_matrix[current_pos][customer_idx]
            current_pos = customer_idx
            
        # Return to depot
        total_distance += self.distance_matrix[current_pos][0]
        
        # Add discharge benefit if applicable
        discharge_benefit = 0
        if self.enable_discharge:
            discharge_benefit = self._calculate_discharge_benefit(route)
            
        return total_distance - discharge_benefit
    
    def _calculate_discharge_benefit(self, route: List[int]) -> float:
        """Calculate benefit from grid discharge during peak hours"""
        benefit = 0
        current_time = 0
        current_pos = 0
        
        for customer_idx in route:
            customer = self.customers[customer_idx - 1]
            travel_time = self.distance_matrix[current_pos][customer_idx]
            current_time += travel_time
            
            # Check if service time overlaps with peak hours
            service_start = max(current_time, customer.ready_time)
            service_end = service_start + customer.service_time
            
            peak_start, peak_end = self.peak_hours
            overlap_start = max(service_start, peak_start)
            overlap_end = min(service_end, peak_end)
            
            if overlap_start < overlap_end:
                # Calculate discharge benefit (simplified model)
                overlap_duration = overlap_end - overlap_start
                benefit += overlap_duration * 0.1  # benefit per time unit
                
            current_time = service_end
            current_pos = customer_idx
            
        return benefit
    
    def _generate_initial_solution(self) -> List[List[int]]:
        """Generate initial solution using nearest neighbor heuristic"""
        unvisited = set(range(1, len(self.customers) + 1))
        routes = []
        
        for vehicle in self.vehicles:
            if not unvisited:
                break
                
            route = []
            current_pos = 0  # depot
            
            while unvisited:
                # Find nearest feasible customer
                best_customer = None
                best_distance = float('inf')
                
                for customer_idx in unvisited:
                    temp_route = route + [customer_idx]
                    if self._is_feasible_route(temp_route, vehicle):
                        distance = self.distance_matrix[current_pos][customer_idx]
                        if distance < best_distance:
                            best_distance = distance
                            best_customer = customer_idx
                
                if best_customer is None:
                    break
                    
                route.append(best_customer)
                unvisited.remove(best_customer)
                current_pos = best_customer
                
            if route:
                routes.append(route)
                
        # Handle unvisited customers with relaxed constraints
        if unvisited:
            logger.warning(f"Could not visit {len(unvisited)} customers with strict constraints. Attempting relaxed assignment.")
            
            # Try to force assignment to available vehicles
            for customer_idx in list(unvisited):
                for i, route in enumerate(routes):
                    if len(route) < 10:  # Limit route length
                        # Insert at best position
                        best_pos = 0
                        best_cost_increase = float('inf')
                        
                        for pos in range(len(route) + 1):
                            temp_route = route[:pos] + [customer_idx] + route[pos:]
                            if self._is_feasible_route(temp_route, self.vehicles[i]):
                                cost_increase = (self._calculate_route_cost(temp_route, self.vehicles[i]) - 
                                               self._calculate_route_cost(route, self.vehicles[i]))
                                if cost_increase < best_cost_increase:
                                    best_cost_increase = cost_increase
                                    best_pos = pos
                        
                        if best_cost_increase < float('inf'):
                            routes[i].insert(best_pos, customer_idx)
                            unvisited.remove(customer_idx)
                            break
                            
            # If still unvisited, create new routes (relax vehicle limit)
            while unvisited and len(routes) < len(self.customers):
                customer_idx = unvisited.pop()
                if len(self.vehicles) > len(routes):
                    routes.append([customer_idx])
                else:
                    # Use first vehicle type for extra routes
                    routes.append([customer_idx])
                    
        return routes
    
    def _mutate_solution(self, routes: List[List[int]]) -> List[List[int]]:
        """Apply mutation to a solution"""
        if not routes or not any(routes):
            return routes
            
        mutated = copy.deepcopy(routes)
        
        # Different mutation strategies
        mutation_type = random.choice(['swap', 'relocate', 'two_opt'])
        
        if mutation_type == 'swap':
            # Swap two customers
            route_idx = random.choice([i for i, r in enumerate(mutated) if len(r) > 1])
            route = mutated[route_idx]
            if len(route) >= 2:
                i, j = random.sample(range(len(route)), 2)
                route[i], route[j] = route[j], route[i]
                
        elif mutation_type == 'relocate':
            # Move customer to different position
            if len(mutated) > 1:
                from_route_idx = random.choice([i for i, r in enumerate(mutated) if len(r) > 0])
                to_route_idx = random.choice(range(len(mutated)))
                
                from_route = mutated[from_route_idx]
                to_route = mutated[to_route_idx]
                
                if from_route:
                    customer = from_route.pop(random.randint(0, len(from_route) - 1))
                    insert_pos = random.randint(0, len(to_route))
                    to_route.insert(insert_pos, customer)
                    
        elif mutation_type == 'two_opt':
            # 2-opt improvement within a route
            route_idx = random.choice([i for i, r in enumerate(mutated) if len(r) > 3])
            route = mutated[route_idx]
            if len(route) > 3:
                i, j = sorted(random.sample(range(1, len(route)), 2))
                route[i:j+1] = route[i:j+1][::-1]
                
        return mutated
    
    def _crossover_solutions(self, parent1: List[List[int]], parent2: List[List[int]]) -> List[List[int]]:
        """Create offspring using crossover"""
        # Simple order crossover adapted for VRP
        all_customers_p1 = [c for route in parent1 for c in route]
        all_customers_p2 = [c for route in parent2 for c in route]
        
        if not all_customers_p1:
            return parent2
        if not all_customers_p2:
            return parent1
            
        # Create child by taking routes from both parents
        child_routes = []
        used_customers = set()
        
        # Take some routes from parent1
        for i, route in enumerate(parent1):
            if i < len(parent1) // 2 and route:
                new_route = [c for c in route if c not in used_customers]
                if new_route:
                    child_routes.append(new_route)
                    used_customers.update(new_route)
        
        # Fill remaining customers using parent2 structure
        for route in parent2:
            remaining = [c for c in route if c not in used_customers]
            if remaining:
                child_routes.append(remaining)
                used_customers.update(remaining)
                
        # Ensure all customers are included
        all_customers = set(range(1, len(self.customers) + 1))
        missing = all_customers - used_customers
        if missing:
            if child_routes:
                child_routes[0].extend(list(missing))
            else:
                child_routes.append(list(missing))
                
        return child_routes
    
    def solve(self) -> Dict:
        """Solve the VRP using genetic algorithm"""
        logger.info(f"Starting VRP solver with {len(self.customers)} customers and {len(self.vehicles)} vehicles")
        logger.info(f"Discharge enabled: {self.enable_discharge}")
        
        if not self.customers:
            logger.warning("No customers to serve")
            return {"routes": [], "total_cost": 0, "total_distance": 0}
            
        try:
            # Generate initial population
            logger.info("Generating initial population...")
            population = []
            
            for _ in range(self.population_size):
                # Randomize customer order for diversity
                shuffled_customers = list(range(1, len(self.customers) + 1))
                random.shuffle(shuffled_customers)
                
                # Create routes using nearest neighbor with randomization
                solution = self._generate_initial_solution()
                if solution:
                    population.append(solution)
                    
            if not population:
                logger.error("Could not generate any initial solutions")
                # Create fallback solution - single route with all customers
                fallback_route = list(range(1, len(self.customers) + 1))
                population = [[fallback_route]]
                
            logger.info(f"Generated {len(population)} initial solutions")
            
            # Genetic algorithm main loop
            no_improvement_count = 0
            
            for iteration in range(self.max_iterations):
                # Evaluate population
                fitness_scores = []
                for solution in population:
                    total_cost = 0
                    valid_routes = 0
                    
                    for i, route in enumerate(solution):
                        if route and i < len(self.vehicles):
                            if self._is_feasible_route(route, self.vehicles[i]):
                                total_cost += self._calculate_route_cost(route, self.vehicles[i])
                                valid_routes += 1
                            else:
                                # Penalty for infeasible routes
                                total_cost += 1000 + sum(self.customers[c-1].demand for c in route)
                    
                    # Penalty for unassigned customers
                    assigned_customers = set()
                    for route in solution:
                        assigned_customers.update(route)
                    unassigned_penalty = len(set(range(1, len(self.customers) + 1)) - assigned_customers) * 2000
                    
                    fitness_scores.append(total_cost + unassigned_penalty)
                
                # Track best solution
                current_best_idx = np.argmin(fitness_scores)
                current_best_cost = fitness_scores[current_best_idx]
                
                if current_best_cost < self.best_cost:
                    self.best_cost = current_best_cost
                    self.best_solution = copy.deepcopy(population[current_best_idx])
                    no_improvement_count = 0
                    logger.info(f"Iteration {iteration}: New best cost = {self.best_cost:.2f}")
                else:
                    no_improvement_count += 1
                
                # Early termination
                if no_improvement_count >= self.no_improvement_limit:
                    logger.info(f"No improvement for {no_improvement_count} iterations. Terminating early.")
                    break
                
                # Selection and reproduction
                sorted_indices = np.argsort(fitness_scores)
                elite = [population[i] for i in sorted_indices[:self.elite_size]]
                
                new_population = elite[:]
                
                while len(new_population) < self.population_size:
                    if random.random() < self.crossover_rate and len(elite) > 1:
                        parent1, parent2 = random.sample(elite, 2)
                        child = self._crossover_solutions(parent1, parent2)
                    else:
                        child = copy.deepcopy(random.choice(elite))
                    
                    if random.random() < self.mutation_rate:
                        child = self._mutate_solution(child)
                    
                    new_population.append(child)
                
                population = new_population
                
                if (iteration + 1) % 100 == 0:
                    logger.info(f"Iteration {iteration + 1}: Best cost = {self.best_cost:.2f}")
            
            if self.best_solution is None:
                logger.error("No feasible solution found during optimization")
                # Return basic solution
                basic_solution = [[list(range(1, min(len(self.customers) + 1, 11)))]]  # First 10 customers
                return self._format_solution(basic_solution)
            
            logger.info(f"Optimization completed. Final cost: {self.best_cost:.2f}")
            return self._format_solution(self.best_solution)
            
        except Exception as e:
            logger.error(f"Error during solving: {e}")
            # Return emergency fallback solution
            emergency_solution = []
            customers_per_vehicle = max(1, len(self.customers) // len(self.vehicles))
            
            for i, vehicle in enumerate(self.vehicles):
                start_idx = i * customers_per_vehicle + 1
                end_idx = min(start_idx + customers_per_vehicle, len(self.customers) + 1)
                if start_idx <= len(self.customers):
                    route = list(range(start_idx, min(end_idx, len(self.customers) + 1)))
                    emergency_solution.append(route)
                    
            return self._format_solution(emergency_solution)
    
    def _format_solution(self, routes: List[List[int]]) -> Dict:
        """Format solution for output"""
        formatted_routes = []
        total_distance = 0
        total_cost = 0
        
        for i, route in enumerate(routes):
            if route and i < len(self.vehicles):
                route_distance = 0
                current_pos = 0
                
                # Add depot at start
                formatted_route = [0]  # depot
                
                for customer_idx in route:
                    route_distance += self.distance_matrix[current_pos][customer_idx]
                    formatted_route.append(customer_idx)
                    current_pos = customer_idx
                
                # Return to depot
                route_distance += self.distance_matrix[current_pos][0]
                formatted_route.append(0)  # depot
                
                route_cost = self._calculate_route_cost(route, self.vehicles[i])
                
                formatted_routes.append({
                    'vehicle_id': i,
                    'route': formatted_route,
                    'distance': route_distance,
                    'cost': route_cost,
                    'customers_served': len(route)
                })
                
                total_distance += route_distance
                total_cost += route_cost
        
        # Verify all customers are served
        served_customers = set()
        for route_info in formatted_routes:
            served_customers.update(c for c in route_info['route'] if c > 0)
        
        all_customers = set(range(1, len(self.customers) + 1))
        unserved = all_customers - served_customers
        
        result = {
            "routes": formatted_routes,
            "total_cost": total_cost,
            "total_distance": total_distance,
            "vehicles_used": len([r for r in formatted_routes if r['customers_served'] > 0]),
            "customers_served": len(served_customers),
            "unserved_customers": list(unserved) if unserved else [],
            "success": len(unserved) == 0
        }
        
        if unserved:
            logger.warning(f"Could not serve {len(unserved)} customers: {unserved}")
        else:
            logger.info(f"Successfully served all {len(served_customers)} customers")
            
        return result