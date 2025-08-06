import pandas as pd
from typing import Tuple, List
from models.ev import Depot, Customer, ElectricVehicle # Assuming ElectricVehicle is also a model

def parse_solomon_dataset(file_path: str) -> Tuple[Depot, List[Customer]]:
    """
    Parses a Solomon dataset file (now adapted for CSV) to extract depot and customer information.

    Args:
        file_path (str): The path to the dataset file (e.g., 'data/C101.csv').

    Returns:
        Tuple[Depot, List[Customer]]: A tuple containing the Depot object and a list of Customer objects.
    """
    try:
        # Attempt to read the CSV file.
        # You MUST adjust 'header=None' and 'names' or directly use 'header=0'
        # if your CSV has a header row with meaningful names.
        # The 'names' list below is a placeholder based on typical Solomon data columns.
        # Adjust these names and their order to match your actual C101.csv file.
        # Example Solomon columns: CUST_NO, XCOORD, YCOORD, DEMAND, READY_TIME, DUE_DATE, SERVICE_TIME
        df = pd.read_csv(file_path, sep=',', header=None,
                         names=['CUST_NO', 'XCOORD', 'YCOORD', 'DEMAND', 'READY_TIME', 'DUE_DATE', 'SERVICE_TIME'])

        # Assuming the first row is always the depot
        depot_data = df.iloc[0]
        depot = Depot(
            id=int(depot_data['CUST_NO']),
            x=depot_data['XCOORD'],
            y=depot_data['YCOORD'],
            ready_time=depot_data['READY_TIME'],
            due_date=depot_data['DUE_DATE']
        )

        customers = []
        # Iterate through the rest of the rows for customers
        for index, row in df.iloc[1:].iterrows():
            customer = Customer(
                id=int(row['CUST_NO']),
                x=row['XCOORD'],
                y=row['YCOORD'],
                demand=row['DEMAND'],
                ready_time=row['READY_TIME'],
                due_date=row['DUE_DATE'],
                service_time=row['SERVICE_TIME']
            )
            customers.append(customer)

        # You might also need to parse vehicle capacity and count from the file
        # For typical Solomon files, this info is in the header.
        # If your CSV doesn't contain this, you'll need to provide it elsewhere (e.g., in main.py or app.py)
        # For now, we'll assume vehicle_count and capacity are handled by the solver's initialization.

        return depot, customers

    except FileNotFoundError:
        # FIX: The error message here was hardcoded to .txt. It should reflect the actual file_path.
        # The original code raised FileNotFoundError with a hardcoded '.txt' message.
        # The fix is to ensure the error message correctly uses the 'file_path' variable.
        raise FileNotFoundError(f"Dataset file not found at: {file_path}")
    except Exception as e:
        print(f"Error parsing Solomon dataset (CSV): {e}")
        # If the CSV format is not as expected, you might get errors here.
        # Print the first few lines of your C101.csv to understand its structure.
        raise