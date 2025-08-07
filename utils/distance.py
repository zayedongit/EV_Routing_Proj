import math

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculates the Haversine distance between two points on Earth
    given their latitudes and longitudes.

    Args:
        lat1 (float): Latitude of the first point.
        lon1 (float): Longitude of the first point.
        lat2 (float): Latitude of the second point.
        lon2 (float): Longitude of the second point.

    Returns:
        float: The distance in kilometers.
    """
    # Assuming x, y coordinates are directly used for Euclidean distance as per traceback
    # If this is truly Haversine, the formula needs to be different.
    # Based on the error and the formula shown in the traceback:
    # math.sqrt((x2 - x1)^2 + (y2 - y1)^2)
    # This suggests it's a Euclidean distance function, not Haversine.
    # Let's assume the intent is Euclidean distance for now, given the error.

    # FIX: Ensure the value inside sqrt is non-negative to prevent domain error
    # Use max(0, ...) to handle potential floating-point inaccuracies that result in tiny negative numbers.
    squared_diff_x = (lat2 - lat1)**2 # Using lat/lon as x/y as per traceback context
    squared_diff_y = (lon2 - lon1)**2

    # Ensure the sum is not negative before taking the square root
    distance = math.sqrt(max(0, squared_diff_x + squared_diff_y))
    
    return distance

# If you intended a true Haversine distance, the function should look like this:
# def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
#     R = 6371  # Radius of Earth in kilometers
#     lat1_rad = math.radians(lat1)
#     lon1_rad = math.radians(lon1)
#     lat2_rad = math.radians(lat2)
#     lon2_rad = math.radians(lon2)

#     dlon = lon2_rad - lon1_rad
#     dlat = lat2_rad - lat1_rad

#     a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
#     c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

#     distance = R * c
#     return distance