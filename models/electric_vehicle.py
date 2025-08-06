class ElectricVehicle:
    def __init__(self, vehicle_id, battery_capacity=100, consumption_rate=0.2):
        self.vehicle_id = vehicle_id
        self.battery_capacity = battery_capacity
        self.current_soc = battery_capacity  # full charge at start
        self.consumption_rate = consumption_rate  # energy per unit distance

    def drive(self, distance):
        energy_used = distance * self.consumption_rate
        self.current_soc -= energy_used
        return energy_used

    def recharge(self, amount):
        self.current_soc = min(self.battery_capacity, self.current_soc + amount)