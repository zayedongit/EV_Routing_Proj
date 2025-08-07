from dataclasses import dataclass
from typing import List, Optional
from utils.distance import haversine_distance

@dataclass
class Customer:
    """Represents a customer location with delivery requirements"""
    id: int
    x: float
    y: float
    demand: float
    ready_time: float
    due_date: float
    service_time: float

@dataclass
class Depot:
    """Represents the central depot where vehicles start and end"""
    x: float
    y: float
    ready_time: float = 0
    due_date: float = 2304  # Default from Solomon instances
    
@dataclass 
class GridStation:
    """Represents a grid discharge station"""
    id: int
    x: float
    y: float
    peak_start: float = 14  # 2PM
    peak_end: float = 18    # 6PM
    
@dataclass
class ElectricVehicle:
    """Represents an electric vehicle with battery constraints"""
    id: str
    capacity: float = 100   # kg
    battery_capacity: float = 100  # kWh
    consumption_rate: float = 0.2  # kWh/km
    current_soc: float = 100
    current_load: float = 0
    current_time: float = 0
    route: List = None
    
    def __post_init__(self):
        if self.route is None:
            self.route = []
        
    def can_visit_grid(self, station: GridStation, current_time: float) -> bool:
        """Check if vehicle can discharge at grid station"""
        return (
            self.current_soc >= 50 and
            station.peak_start <= current_time <= station.peak_end
        )
    
    def discharge_at_grid(self, energy: float):
        """Discharge specified energy amount to grid"""
        if energy > self.current_soc:
            raise ValueError("Cannot discharge more than current SoC")
        self.current_soc -= energy
        
    def move_to(self, x: float, y: float, current_x: float, current_y: float):
        """Update vehicle state after moving to new coordinates"""
        distance = haversine_distance(current_x, current_y, x, y)
        energy_used = distance * self.consumption_rate
        self.current_soc -= energy_used
        self.current_time += distance / 50 * 60  # Assuming 50km/h speed
        return distance
