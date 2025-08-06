class GridStation:
    def __init__(self, id, x, y, capacity=100, price_per_unit=5):
        self.id = id
        self.x = x
        self.y = y
        self.capacity = capacity  # Max energy capacity the station can discharge
        self.price_per_unit = price_per_unit  # Revenue per unit of energy sold

    def discharge_energy(self, amount):
        """Simulate discharging energy to a vehicle."""
        if amount <= self.capacity:
            self.capacity -= amount
            return amount
        else:
            discharged = self.capacity
            self.capacity = 0
            return discharged