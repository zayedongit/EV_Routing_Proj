def calculate_energy_used(distance: float, consumption_rate: float) -> float:
    """Calculate energy used for a given distance"""
    return distance * consumption_rate

def check_soc_constraints(vehicle, distance_to_next: float) -> bool:
    """Check if vehicle has enough charge for next leg"""
    return vehicle.current_soc >= distance_to_next * vehicle.consumption_rate