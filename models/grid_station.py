from dataclasses import dataclass
from typing import Optional

@dataclass
class GridStation:
    """
    Represents a grid discharge station where EVs can discharge energy back to the grid.
    
    Attributes:
        id: Unique identifier for the station
        x: x-coordinate location
        y: y-coordinate location
        peak_start: Hour when peak discharge period starts (default 14 for 2PM)
        peak_end: Hour when peak discharge period ends (default 18 for 6PM)
        capacity: Maximum energy capacity in kWh (default 100)
        price_per_unit: Revenue per kWh discharged in dollars (default 0.15)
    """
    id: int
    x: float
    y: float
    peak_start: float = 14  # 2PM
    peak_end: float = 18    # 6PM
    capacity: float = 100   # kWh
    price_per_unit: float = 0.15  # $/kWh

    def discharge_energy(self, amount: float) -> float:
        """
        Simulate discharging energy to grid.
        
        Args:
            amount: Energy to discharge in kWh
            
        Returns:
            Actual amount discharged (may be less than requested if capacity is exceeded)
            
        Raises:
            ValueError: If amount is negative
        """
        if amount < 0:
            raise ValueError("Discharge amount cannot be negative")
            
        if amount <= self.capacity:
            self.capacity -= amount
            return amount
            
        discharged = self.capacity
        self.capacity = 0
        return discharged

    def is_peak_time(self, current_time: float) -> bool:
        """
        Check if current time is within peak discharge hours.
        
        Args:
            current_time: Time in hours (e.g., 14.5 for 2:30PM)
            
        Returns:
            True if within peak hours, False otherwise
        """
        return self.peak_start <= current_time <= self.peak_end