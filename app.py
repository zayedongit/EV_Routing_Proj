import streamlit as st
import sys
import os
import traceback
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from solver.task2_vrp_discharge_solver import VRPSolver, Customer, Vehicle
from visualization.map_plotter import plot_routes

# Configure Streamlit
st.set_page_config(
    page_title="EV Route - Smart Electric Vehicle Navigation",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for a polished dark theme
st.markdown("""
<style>
    /* Import SF Pro Display font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    /* Dark Theme Design System */
    :root {
        --primary: #0A84FF;
        --primary-light: #64D2FF;
        --primary-dark: #0040DD;
        --success: #30D158;
        --warning: #FF9F0A;
        --error: #FF453A;
        
        --background: #000000;
        --background-secondary: #1C1C1E;
        --background-tertiary: #2C2C2E;
        
        --text-primary: #FFFFFF;
        --text-secondary: #EBEBF599; /* 60% opacity */
        --text-tertiary: #EBEBF54D; /* 30% opacity */
        
        --border-color: #38383A;
        
        --font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif;
        
        --radius-md: 12px;
        --radius-lg: 16px;
        
        --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.4);
    }
    
    /* Global Styles */
    .stApp {
        background: var(--background);
        color: var(--text-primary);
    }
    
    h1, h2, h3, h4, h5, h6 {
        font-family: var(--font-family);
        color: var(--text-primary);
        font-weight: 600;
    }
    
    /* Main container and sidebar */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    .st-emotion-cache-16txtl3 {
        padding-top: 2rem;
    }

    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background-color: var(--background-secondary);
        border-right: 1px solid var(--border-color);
    }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
        color: var(--text-primary);
    }
    
    /* Button Styling */
    .stButton > button {
        background: var(--primary);
        color: white;
        border-radius: var(--radius-md);
        padding: 12px 24px;
        font-weight: 500;
        border: none;
        min-height: 44px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        background: var(--primary-light);
        box-shadow: 0 4px 8px rgba(0,0,0,0.3);
        transform: translateY(-1px);
    }
    
    /* Metric Cards */
    div[data-testid="metric-container"] {
        background-color: var(--background-secondary);
        border: 1px solid var(--border-color);
        padding: 1.5rem;
        border-radius: var(--radius-lg);
        box-shadow: var(--shadow-md);
    }
    div[data-testid="metric-container"] label {
        color: var(--text-secondary);
    }
    
    /* Expander Styling */
    .streamlit-expanderHeader {
        background-color: var(--background-tertiary);
        color: var(--text-primary);
        border-radius: var(--radius-md);
    }
    
    /* Plotly Chart Container */
    .js-plotly-plot {
        border-radius: var(--radius-lg);
        border: 1px solid var(--border-color);
    }
    
    /* Hide Streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

def create_battery_gauge(percentage):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=percentage,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': "State of Charge", 'font': {'size': 20, 'family': 'Inter'}},
        number={'font': {'size': 48, 'family': 'Inter'}},
        gauge={
            'axis': {'range': [None, 100], 'tickwidth': 1, 'tickcolor': "darkblue"},
            'bar': {'color': "#30D158" if percentage > 20 else "#FF9F0A"},
            'bgcolor': "rgba(0,0,0,0)",
            'borderwidth': 2,
            'bordercolor': "#38383A",
        }
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font={'color': "white", 'family': "Inter"}, height=250, margin=dict(l=20, r=20, t=50, b=20))
    return fig

def create_route_comparison_chart():
    categories = ['Time (min)', 'Distance (km)', 'Energy (%)', 'Cost ($)']
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=[42, 35.2, 18, 8.5], theta=categories, fill='toself', name='Fastest Route', line_color='#0A84FF'
    ))
    fig.add_trace(go.Scatterpolar(
        r=[48, 38.1, 14, 7.2], theta=categories, fill='toself', name='Most Efficient', line_color='#30D158'
    ))
    fig.update_layout(
        template="plotly_dark",
        polar=dict(radialaxis=dict(visible=True, range=[0, 60])),
        showlegend=True,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
        height=350, margin=dict(l=40, r=40, t=40, b=40)
    )
    return fig

# Load data functions (no changes needed)
def load_csv_data(filename):
    try:
        df = pd.read_csv(filename)
        column_mapping = {
            'ID': 'id', 'CustomerID': 'id', 'Customer_ID': 'id', 'customer_id': 'id', 'CUST NO.': 'id', 'CUSTNO': 'id',
            'X': 'x', 'X_coord': 'x', 'x_coord': 'x', 'X_coordinate': 'x', 'XCOORD.': 'x', 'XCOORD': 'x',
            'Y': 'y', 'Y_coord': 'y', 'y_coord': 'y', 'Y_coordinate': 'y', 'YCOORD.': 'y', 'YCOORD': 'y',
            'Demand': 'demand', 'DEMAND': 'demand',
            'ReadyTime': 'ready_time', 'Ready_Time': 'ready_time', 'READY TIME': 'ready_time', 'READYTIME': 'ready_time',
            'DueTime': 'due_time', 'Due_Time': 'due_time', 'DUE DATE': 'due_time', 'DUE TIME': 'due_time', 'DUETIME': 'due_time',
            'ServiceTime': 'service_time', 'Service_Time': 'service_time', 'SERVICE TIME': 'service_time', 'SERVICETIME': 'service_time'
        }
        df_renamed = df.copy()
        for old_name, new_name in column_mapping.items():
            if old_name in df.columns:
                df_renamed = df_renamed.rename(columns={old_name: new_name})
        required_cols = ['id', 'x', 'y', 'demand', 'ready_time', 'due_time', 'service_time']
        if any(col not in df_renamed.columns for col in required_cols):
            return None, None
        df_renamed = df_renamed.sort_values('id')
        customers = [Customer(**row) for _, row in df_renamed[df_renamed['id'] != 0].iterrows()]
        depot = Customer(**df_renamed[df_renamed['id'] == 0].iloc[0])
        return depot, customers
    except Exception:
        return None, None

def generate_sample_data():
    depot = Customer(0, 50, 50, 0, 0, 1000, 0)
    customers = []
    for i in range(20):
        customers.append(Customer(id=i+1, x=np.random.randint(0,100), y=np.random.randint(0,100), demand=np.random.randint(5,20), ready_time=0, due_time=1000, service_time=10))
    return depot, customers

def create_vehicles(num_vehicles, capacity, battery_capacity):
    return [Vehicle(capacity, battery_capacity, 0.5) for _ in range(num_vehicles)]

# --- App Layout ---

with st.sidebar:
    st.header("⚡ EV Route")
    data_source = st.selectbox("Data Source", ["Sample Data", "Upload CSV File", "Solomon C101"], help="Select the customer data to use for routing.")
    
    st.header("⚙️ Configuration")
    num_vehicles = st.slider("Number of Vehicles", 1, 10, 3)
    vehicle_capacity = st.slider("Vehicle Capacity (kg)", 50, 500, 200)
    battery_capacity = st.slider("Battery Capacity (kWh)", 50.0, 200.0, 100.0)
    enable_discharge = st.checkbox("Enable Grid Discharge", value=False)
    if enable_discharge:
        peak_hours = st.slider("Peak Hours", 0, 24, (17, 20))
    else:
        peak_hours = (17, 20)

# Load data based on selection
if data_source == "Sample Data":
    depot, customers = generate_sample_data()
elif data_source == "Upload CSV File":
    uploaded_file = st.sidebar.file_uploader("Upload your CSV file", type=['csv'])
    if uploaded_file:
        depot, customers = load_csv_data(uploaded_file)
    else:
        depot, customers = None, None
else: # Solomon C101
    depot, customers = load_csv_data("data/C101.csv")

if st.sidebar.button("🚀 Optimize Routes", type="primary", use_container_width=True):
    if depot and customers:
        with st.spinner("Finding the best routes..."):
            try:
                vehicles = create_vehicles(num_vehicles, vehicle_capacity, battery_capacity)
                solver = VRPSolver(customers, depot, vehicles, enable_discharge, peak_hours)
                solution = solver.solve()
                st.session_state['solution'] = solution
                st.session_state['depot'] = depot
                st.session_state['customers'] = customers
            except Exception as e:
                st.error(f"An error occurred during optimization: {e}")
                st.code(traceback.format_exc())
    else:
        st.sidebar.warning("Please upload a valid data file to optimize.")

# --- Main Content ---
st.title("Smart Electric Vehicle Navigation Dashboard")

if 'solution' in st.session_state:
    solution = st.session_state['solution']
    depot = st.session_state['depot']
    customers = st.session_state['customers']

    # Display summary metrics
    st.header("📊 Solution Summary")
    cols = st.columns(4)
    cols[0].metric("Total Cost", f"${solution['total_cost']:.2f}", help="Total routing cost.")
    cols[1].metric("Total Distance", f"{solution['total_distance']:.1f} km", help="Total distance for all routes.")
    cols[2].metric("Vehicles Used", solution['vehicles_used'], help="Number of vehicles deployed.")
    cols[3].metric("Customers Served", solution['customers_served'], help="Number of customers served.")
    
    # Display the map with routes
    st.header("🗺️ Route Visualization")
    fig = plot_routes(depot, customers, [], solution['routes'])
    st.pyplot(fig)

    # Display detailed route information
    st.header("📋 Route Details")
    for route_info in solution['routes']:
        if route_info['customers_served'] > 0:
            with st.expander(f"🚛 Vehicle {route_info['vehicle_id'] + 1} ({route_info['customers_served']} customers)"):
                st.write(f"**Path:** {' → '.join(map(str, route_info['route']))}")
                st.metric("Route Distance", f"{route_info['distance']:.1f} km")

else:
    # Initial state display
    st.header("Dashboard")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🔋 Vehicle Status")
        st.plotly_chart(create_battery_gauge(78), use_container_width=True)
    with col2:
        st.subheader("⚖️ Route Comparison")
        st.plotly_chart(create_route_comparison_chart(), use_container_width=True)

    st.info("⬅️ Use the sidebar to configure and optimize your vehicle routes.")