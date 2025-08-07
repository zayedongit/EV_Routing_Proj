"""
Utility functions for loading and generating VRP data
"""
import os
import numpy as np
from solver.task2_vrp_discharge_solver import Customer

def create_sample_solomon_data():
    """Create a sample Solomon-format data file"""
    data_dir = "data"
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    
    # Create sample C101.txt file
    sample_data = """# Sample Solomon C101 format data
# Customer: ID X Y Demand ReadyTime DueTime ServiceTime
0 50 50 0 0 1000 0
1 20 20 10 161 171 10
2 30 40 7 50 60 10
3 35 35 13 116 126 10
4 25 45 19 149 159 10
5 55 20 26 34 44 10
6 55 45 3 99 109 10
7 60 20 5 81 91 10
8 60 40 9 95 105 10
9 65 35 16 97 107 10
10 70 30 16 124 134 10
11 75 55 12 67 77 10
12 80 25 17 23 33 10
13 85 25 18 39 49 10
14 75 45 29 17 27 10
15 80 40 3 78 88 10
16 85 35 6 35 45 10
17 75 20 15 73 83 10
18 70 45 14 145 155 10
19 68 58 26 175 185 10
20 66 62 7 182 192 10
"""
    
    with open(os.path.join(data_dir, "C101.txt"), "w") as f:
        f.write(sample_data)
    
    print(f"Created sample data file: {os.path.join(data_dir, 'C101.txt')}")

def validate_problem_parameters(customers, vehicles):
    """Validate that the problem parameters make sense"""
    issues = []
    
    # Check if total demand can be satisfied
    total_demand = sum(c.demand for c in customers)
    total_capacity = sum(v.capacity for v in vehicles)
    
    if total_demand > total_capacity:
        issues.append(f"Total demand ({total_demand}) exceeds total vehicle capacity ({total_capacity})")
    
    # Check time windows
    for customer in customers:
        if customer.ready_time >= customer.due_time:
            issues.append(f"Customer {customer.id} has invalid time window: ready={customer.ready_time}, due={customer.due_time}")
    
    # Check for very tight time windows
    tight_windows = [c for c in customers if (c.due_time - c.ready_time) < c.service_time]
    if tight_windows:
        issues.append(f"{len(tight_windows)} customers have time windows shorter than their service time")
    
    return issues

def adjust_problem_for_feasibility(customers, vehicles):
    """Adjust problem parameters to improve feasibility"""
    adjusted_customers = []
    
    for customer in customers:
        # Ensure time windows are reasonable
        ready_time = customer.ready_time
        due_time = max(customer.due_time, ready_time + customer.service_time + 10)
        
        # Cap individual demands
        max_single_demand = min(v.capacity for v in vehicles) * 0.8
        demand = min(customer.demand, int(max_single_demand))
        
        adjusted_customer = Customer(
            customer.id, customer.x, customer.y, demand,
            ready_time, due_time, customer.service_time
        )
        adjusted_customers.append(adjusted_customer)
    
    return adjusted_customers

if __name__ == "__main__":
    create_sample_solomon_data()