import streamlit as st
import sys
import os
import traceback
import pandas as pd
import numpy as np

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from solver.task2_vrp_discharge_solver import VRPSolver, Customer, Vehicle

def load_csv_data(filename):
    """Load data from CSV file"""
    try:
        df = pd.read_csv(filename)
        
        # Expected CSV columns: ID, X, Y, Demand, ReadyTime, DueTime, ServiceTime
        # or: CustomerID, X_coord, Y_coord, Demand, ReadyTime, DueTime, ServiceTime
        # Handle different column naming conventions
        
        column_mapping = {
            # Standard mappings
            'ID': 'id', 'CustomerID': 'id', 'Customer_ID': 'id', 'customer_id': 'id', 'CUST NO.': 'id', 'CUSTNO': 'id',
            'X': 'x', 'X_coord': 'x', 'x_coord': 'x', 'X_coordinate': 'x', 'XCOORD.': 'x', 'XCOORD': 'x',
            'Y': 'y', 'Y_coord': 'y', 'y_coord': 'y', 'Y_coordinate': 'y', 'YCOORD.': 'y', 'YCOORD': 'y',
            'Demand': 'demand', 'DEMAND': 'demand', 'demand': 'demand',
            'ReadyTime': 'ready_time', 'Ready_Time': 'ready_time', 'ready_time': 'ready_time', 'READY TIME': 'ready_time', 'READYTIME': 'ready_time',
            'DueTime': 'due_time', 'Due_Time': 'due_time', 'due_time': 'due_time', 'DUE DATE': 'due_time', 'DUE TIME': 'due_time', 'DUETIME': 'due_time',
            'ServiceTime': 'service_time', 'Service_Time': 'service_time', 'service_time': 'service_time', 'SERVICE TIME': 'service_time', 'SERVICETIME': 'service_time'
        }
        
        # Rename columns to standard format
        df_renamed = df.copy()
        for old_name, new_name in column_mapping.items():
            if old_name in df.columns:
                df_renamed = df_renamed.rename(columns={old_name: new_name})
        
        # Check if we have the required columns
        required_cols = ['id', 'x', 'y', 'demand', 'ready_time', 'due_time', 'service_time']
        missing_cols = [col for col in required_cols if col not in df_renamed.columns]
        
        if missing_cols:
            # Try to map common alternative column names
            alt_mappings = {
                'id': ['CUST NO.', 'CUSTNO', 'Customer', 'Cust_No'],
                'x': ['XCOORD.', 'XCOORD', 'X_COORD', 'Longitude', 'Long'],
                'y': ['YCOORD.', 'YCOORD', 'Y_COORD', 'Latitude', 'Lat'],
                'demand': ['DEMAND', 'Load', 'Quantity', 'Qty'],
                'ready_time': ['READY TIME', 'READYTIME', 'Ready', 'Start_Time', 'Earliest'],
                'due_time': ['DUE DATE', 'DUE TIME', 'DUETIME', 'Due', 'End_Time', 'Latest'],
                'service_time': ['SERVICE TIME', 'SERVICETIME', 'Service', 'Duration']
            }
            
            # Try to find alternative column names
            for std_col in missing_cols[:]:  # Create a copy to modify during iteration
                for alt_col in alt_mappings.get(std_col, []):
                    if alt_col in df.columns:
                        df_renamed = df_renamed.rename(columns={alt_col: std_col})
                        missing_cols.remove(std_col)
                        break
            
            # If still missing columns, show error
            if missing_cols:
                st.error(f"CSV file is missing required columns: {missing_cols}")
                st.info("Expected columns: ID, X, Y, Demand, ReadyTime, DueTime, ServiceTime")
                st.info("Current columns: " + ", ".join(df.columns.tolist()))
                
                # Show column mapping suggestions
                st.subheader("Column Mapping Suggestions:")
                for missing_col in missing_cols:
                    possible_matches = [col for col in df.columns if any(keyword.lower() in col.lower() 
                                      for keyword in [missing_col, missing_col.replace('_', '')])]
                    if possible_matches:
                        st.write(f"For '{missing_col}', try renaming: {possible_matches}")
                
                return generate_sample_data()
        
        # Sort by ID to ensure depot (ID=0) comes first
        df_renamed = df_renamed.sort_values('id')
        
        customers = []
        depot = None
        
        for _, row in df_renamed.iterrows():
            customer = Customer(
                id=int(row['id']),
                x=float(row['x']),
                y=float(row['y']),
                demand=int(row['demand']),
                ready_time=int(row['ready_time']),
                due_time=int(row['due_time']),
                service_time=int(row['service_time'])
            )
            
            if int(row['id']) == 0:  # Depot
                depot = customer
            else:
                customers.append(customer)
        
        if depot is None:
            # Create a depot if not found - use strategic positioning
            st.warning("No depot (ID=0) found in data. Creating depot at optimal center location.")
            
            # Calculate the geometric center
            avg_x = df_renamed['x'].mean()
            avg_y = df_renamed['y'].mean()
            
            # Calculate bounds for better depot placement
            min_x, max_x = df_renamed['x'].min(), df_renamed['x'].max()
            min_y, max_y = df_renamed['y'].min(), df_renamed['y'].max()
            
            # Place depot at center but adjust if needed for better coverage
            depot_x = avg_x
            depot_y = avg_y
            
            # Set depot time window to cover all customer windows
            min_ready_time = df_renamed['ready_time'].min()
            max_due_time = df_renamed['due_time'].max()
            
            depot = Customer(
                id=0, 
                x=depot_x, 
                y=depot_y, 
                demand=0, 
                ready_time=min_ready_time, 
                due_time=max_due_time + 100,  # Extra buffer for return
                service_time=0
            )
            
            st.info(f"Created depot at coordinates ({depot_x:.1f}, {depot_y:.1f}) with time window [{min_ready_time}, {max_due_time + 100}]")
        
        if not customers:
            st.error("No customer data found in CSV file.")
            return generate_sample_data()
        
        st.success(f"Successfully loaded {len(customers)} customers from CSV file.")
        return depot, customers
        
    except Exception as e:
        st.error(f"Error loading CSV file: {e}")
        st.info("Using sample data instead.")
        return generate_sample_data()

def load_solomon_data(filename):
    """Load Solomon benchmark data from text file"""
    try:
        if not os.path.exists(filename):
            st.warning(f"Data file {filename} not found. Using sample data.")
            return generate_sample_data()
        
        with open(filename, 'r') as f:
            lines = f.readlines()
        
        customers = []
        depot = None
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            parts = line.split()
            if len(parts) >= 7 and parts[0].isdigit():
                cust_id = int(parts[0])
                x = float(parts[1])
                y = float(parts[2])
                demand = int(parts[3])
                ready_time = int(parts[4])
                due_time = int(parts[5])
                service_time = int(parts[6])
                
                customer = Customer(cust_id, x, y, demand, ready_time, due_time, service_time)
                
                if cust_id == 0:  # Depot
                    depot = customer
                else:
                    customers.append(customer)
                    
        if depot is None or not customers:
            st.warning("Could not parse text file properly. Using sample data.")
            return generate_sample_data()
            
        return depot, customers
        
    except Exception as e:
        st.error(f"Error loading text file: {e}")
        st.info("Using sample data instead.")
        return generate_sample_data()

def generate_sample_data():
    """Generate sample problem data"""
    # Depot at center
    depot = Customer(0, 50, 50, 0, 0, 1000, 0)
    
    # Generate 20 customers in a realistic pattern
    customers = []
    customer_id = 1
    
    # Create customers in clusters around the depot
    for cluster in range(4):
        cluster_center_x = 30 + (cluster % 2) * 40 + np.random.uniform(-5, 5)
        cluster_center_y = 30 + (cluster // 2) * 40 + np.random.uniform(-5, 5)
        
        for i in range(5):
            x = cluster_center_x + np.random.uniform(-15, 15)
            y = cluster_center_y + np.random.uniform(-15, 15)
            demand = np.random.randint(5, 25)
            ready_time = np.random.randint(0, 100)
            due_time = ready_time + np.random.randint(50, 300)
            service_time = np.random.randint(10, 30)
            
            customer = Customer(customer_id, x, y, demand, ready_time, due_time, service_time)
            customers.append(customer)
            customer_id += 1
            
    return depot, customers

def create_vehicles(num_vehicles=3, capacity=200, battery_capacity=100.0):
    """Create vehicle fleet"""
    vehicles = []
    for i in range(num_vehicles):
        vehicle = Vehicle(capacity, battery_capacity, consumption_rate=0.5)
        vehicles.append(vehicle)
    return vehicles

def main():
    st.set_page_config(page_title="EV Routing Solver", layout="wide")
    st.title("🚛⚡ Electric Vehicle Routing Problem Solver")
    
    st.sidebar.header("Configuration")
    
    # Problem parameters
    enable_discharge = st.sidebar.checkbox("Enable Grid Discharge", value=False)
    num_vehicles = st.sidebar.slider("Number of Vehicles", min_value=1, max_value=10, value=3)
    vehicle_capacity = st.sidebar.slider("Vehicle Capacity", min_value=50, max_value=500, value=200)
    battery_capacity = st.sidebar.slider("Battery Capacity (kWh)", min_value=50.0, max_value=200.0, value=100.0)
    
    # Peak hours for discharge
    if enable_discharge:
        peak_start = st.sidebar.slider("Peak Hour Start", min_value=0, max_value=23, value=17)
        peak_end = st.sidebar.slider("Peak Hour End", min_value=peak_start + 1, max_value=24, value=20)
        peak_hours = (peak_start, peak_end)
    else:
        peak_hours = (17, 20)
    
    # Data source selection
    data_source = st.sidebar.selectbox("Data Source", ["Sample Data", "Upload CSV File", "Upload Text File", "Solomon C101"])
    
    try:
        # Load data based on selection
        if data_source == "Sample Data":
            depot, customers = generate_sample_data()
        elif data_source == "Upload CSV File":
            uploaded_file = st.sidebar.file_uploader("Upload CSV file", type=['csv'])
            if uploaded_file:
                # Save uploaded file temporarily
                with open("temp_data.csv", "wb") as f:
                    f.write(uploaded_file.getbuffer())
                depot, customers = load_csv_data("temp_data.csv")
                os.remove("temp_data.csv")
            else:
                st.info("Please upload a CSV file or select 'Sample Data'")
                depot, customers = generate_sample_data()
        elif data_source == "Upload Text File":
            uploaded_file = st.sidebar.file_uploader("Upload Solomon format file", type=['txt'])
            if uploaded_file:
                # Save uploaded file temporarily
                with open("temp_data.txt", "wb") as f:
                    f.write(uploaded_file.getbuffer())
                depot, customers = load_solomon_data("temp_data.txt")
                os.remove("temp_data.txt")
            else:
                st.info("Please upload a text file or select 'Sample Data'")
                depot, customers = generate_sample_data()
        else:  # Solomon C101
            depot, customers = load_solomon_data("data/C101.txt")
        
        # Display problem info
        st.subheader("Problem Information")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Customers", len(customers))
        with col2:
            st.metric("Vehicles", num_vehicles)
        with col3:
            st.metric("Grid Discharge", "Enabled" if enable_discharge else "Disabled")
        
        # Create vehicles
        vehicles = create_vehicles(num_vehicles, vehicle_capacity, battery_capacity)
        
        # Solve button
        if st.button("🔧 Solve Routing Problem", type="primary"):
            with st.spinner("Solving VRP... This may take a few moments."):
                try:
                    # Initialize solver
                    solver = VRPSolver(
                        customers=customers,
                        depot=depot,
                        vehicles=vehicles,
                        enable_discharge=enable_discharge,
                        peak_hours=peak_hours
                    )
                    
                    # Solve the problem
                    solution = solver.solve()
                    
                    # Display results
                    st.success("✅ Solution found!")
                    
                    # Summary metrics
                    st.subheader("Solution Summary")
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        st.metric("Total Cost", f"{solution['total_cost']:.2f}")
                    with col2:
                        st.metric("Total Distance", f"{solution['total_distance']:.2f}")
                    with col3:
                        st.metric("Vehicles Used", solution['vehicles_used'])
                    with col4:
                        st.metric("Customers Served", solution['customers_served'])
                    
                    # Route details
                    st.subheader("Route Details")
                    
                    for route_info in solution['routes']:
                        if route_info['customers_served'] > 0:
                            with st.expander(f"🚛 Vehicle {route_info['vehicle_id']} - {route_info['customers_served']} customers"):
                                col1, col2 = st.columns(2)
                                
                                with col1:
                                    st.write(f"**Route:** {' → '.join(map(str, route_info['route']))}")
                                    st.write(f"**Distance:** {route_info['distance']:.2f}")
                                    st.write(f"**Cost:** {route_info['cost']:.2f}")
                                
                                with col2:
                                    # Route visualization data
                                    route_data = []
                                    for node_id in route_info['route']:
                                        if node_id == 0:  # Depot
                                            route_data.append({
                                                'Node': 'Depot',
                                                'X': depot.x,
                                                'Y': depot.y,
                                                'Type': 'Depot'
                                            })
                                        else:
                                            customer = customers[node_id - 1]
                                            route_data.append({
                                                'Node': f'C{customer.id}',
                                                'X': customer.x,
                                                'Y': customer.y,
                                                'Type': 'Customer'
                                            })
                                    
                                    df_route = pd.DataFrame(route_data)
                                    st.dataframe(df_route, use_container_width=True)
                    
                    # Unserved customers warning
                    if solution.get('unserved_customers'):
                        st.warning(f"⚠️ Could not serve {len(solution['unserved_customers'])} customers: {solution['unserved_customers']}")
                        st.info("Try increasing the number of vehicles or adjusting vehicle parameters.")
                    
                    # Additional metrics if discharge is enabled
                    if enable_discharge:
                        st.subheader("Grid Discharge Analysis")
                        st.info(f"Peak hours configured: {peak_hours[0]}:00 - {peak_hours[1]}:00")
                        
                except Exception as e:
                    st.error(f"❌ Error solving the problem: {str(e)}")
                    st.error("**Traceback:**")
                    st.code(traceback.format_exc())
                    
                    # Provide troubleshooting suggestions
                    st.subheader("Troubleshooting Suggestions:")
                    st.write("1. **Increase vehicle capacity** - Current demand might exceed vehicle limits")
                    st.write("2. **Add more vehicles** - Problem might need more vehicles to serve all customers")
                    st.write("3. **Increase battery capacity** - Vehicles might not have enough range")
                    st.write("4. **Check time windows** - Some customers might have conflicting time constraints")
                    st.write("5. **Use sample data** - Try with the built-in sample data to verify the solver works")
        
        # Display raw data
        with st.expander("📊 View Problem Data"):
            st.subheader("Depot Information")
            depot_data = pd.DataFrame([{
                'ID': depot.id,
                'X': depot.x,
                'Y': depot.y,
                'Ready Time': depot.ready_time,
                'Due Time': depot.due_time
            }])
            st.dataframe(depot_data, use_container_width=True)
            
            st.subheader("Customer Information")
            customer_data = []
            for customer in customers:
                customer_data.append({
                    'ID': customer.id,
                    'X': customer.x,
                    'Y': customer.y,
                    'Demand': customer.demand,
                    'Ready Time': customer.ready_time,
                    'Due Time': customer.due_time,
                    'Service Time': customer.service_time
                })
            
            df_customers = pd.DataFrame(customer_data)
            st.dataframe(df_customers, use_container_width=True)
            
            # Summary statistics
            st.subheader("Problem Statistics")
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**Total Demand:** {sum(c.demand for c in customers)}")
                st.write(f"**Average Demand:** {np.mean([c.demand for c in customers]):.1f}")
                st.write(f"**Max Demand:** {max(c.demand for c in customers)}")
                
            with col2:
                st.write(f"**Earliest Ready Time:** {min(c.ready_time for c in customers)}")
                st.write(f"**Latest Due Time:** {max(c.due_time for c in customers)}")
                st.write(f"**Average Service Time:** {np.mean([c.service_time for c in customers]):.1f}")
        
        # CSV format guide
        with st.expander("📋 CSV File Format Guide"):
            st.subheader("Expected CSV Format")
            st.write("Your CSV file should have these columns (column names are flexible):")
            
            sample_csv = pd.DataFrame({
                'ID': [0, 1, 2, 3, 4, 5],
                'X': [50, 20, 30, 35, 25, 55],
                'Y': [50, 20, 40, 35, 45, 20],
                'Demand': [0, 10, 7, 13, 19, 26],
                'ReadyTime': [0, 161, 50, 116, 149, 34],
                'DueTime': [1000, 171, 60, 126, 159, 44],
                'ServiceTime': [0, 10, 10, 10, 10, 10]
            })
            
            st.dataframe(sample_csv)
            
            st.write("**Accepted column names (case-insensitive):**")
            st.write("- **ID**: ID, CustomerID, Customer_ID, CUST NO., CUSTNO")
            st.write("- **X**: X, X_coord, XCOORD., XCOORD, X_COORD")
            st.write("- **Y**: Y, Y_coord, YCOORD., YCOORD, Y_COORD")
            st.write("- **Demand**: Demand, DEMAND, Load")
            st.write("- **ReadyTime**: ReadyTime, READY TIME, READYTIME")
            st.write("- **DueTime**: DueTime, DUE DATE, DUE TIME, DUETIME")
            st.write("- **ServiceTime**: ServiceTime, SERVICE TIME, SERVICETIME")
        
    except Exception as e:
        st.error(f"❌ Critical error in application: {str(e)}")
        st.error("**Traceback:**")
        st.code(traceback.format_exc())
        
        st.subheader("Emergency Recovery:")
        st.write("The application encountered a critical error. Please try:")
        st.write("1. Refresh the page")
        st.write("2. Use 'Sample Data' option")
        st.write("3. Reduce the problem size (fewer customers/vehicles)")
        st.write("4. Check your CSV file format")

if __name__ == "__main__":
    main()