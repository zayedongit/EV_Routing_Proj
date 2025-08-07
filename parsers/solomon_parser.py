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
        # Read the CSV, assuming the first row is the header.
        # Ensure 'names' match your CSV columns if they differ from the header.
        df = pd.read_csv(file_path, sep=',', header=0,
                         names=['CUST_NO', 'XCOORD', 'YCOORD', 'DEMAND', 'READY_TIME', 'DUE_DATE', 'SERVICE_TIME'])

        # Assuming the first row of data (after header) is the depot's information
        depot_data = df.iloc[0] # Accessing the first data row (index 0 after header)
        
        # FIX: Instantiate Depot without the 'id' argument, as per models/ev.py
        depot = Depot(
            x=depot_data['XCOORD'],
            y=depot_data['YCOORD'],
            ready_time=depot_data['READY_TIME'],
            due_date=depot_data['DUE_DATE']
        )

        customers = []
        # Iterate through the rest of the rows for customers (starting from the second data row)
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

        return depot, customers

    except FileNotFoundError:
        raise FileNotFoundError(f"Dataset file not found at: {file_path}")
    except Exception as e:
        print(f"Error parsing Solomon dataset (CSV): {e}")
        # Provide more context for debugging if the error persists
        print(f"File path: {file_path}")
        print(f"DataFrame head:\n{df.head()}")
        raise