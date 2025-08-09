📦 EV Routing Project
📌 Overview
The EV Routing Project is a Python-based solution for optimizing Electric Vehicle (EV) delivery routes. It uses real-world road network and delivery demand data to compute the most efficient paths for EV fleets, considering battery constraints and charging requirements. The system can run as both a command-line tool and a Streamlit web application for interactive visualization.

It is designed for logistics, delivery, and energy optimization scenarios — where EVs need to deliver goods and may also perform V2G (Vehicle-to-Grid) operations.

⚙️ Features
Route Optimization: Finds shortest or most efficient EV delivery paths.
Battery Constraints: Considers energy capacity and recharging points.
Data Parsing: Reads structured delivery datasets (Solomon/CSV formats).
Visualization: Plots routes on maps for easy interpretation.
Web Interface: Streamlit app for interactive exploration.
Modular Codebase: Separate modules for data handling, solving, and visualization.

📂 Project Structure
bash
Copy
Edit
EV_Routing_Proj/
│── app.py              # Streamlit web app entry point
│── main.py             # CLI entry point for route solving
│── data_utils.py       # Data loading and preprocessing utilities
│── solver/             # Core algorithms for routing optimization
│── visualization/      # Plotting functions for routes & stats
│── data/               # Sample datasets (CSV/route files)
│── requirements.txt    # Python dependencies
│── README.md           # Project documentation

🔍 How It Works
1️⃣ Data Loading
The data_utils.py module loads delivery and vehicle data from CSV files.
Expected dataset includes:
Customer locations (x, y)
Demand
Time windows
Service times
Charging station locations

2️⃣ Route Optimization
The solver/ package implements algorithms to assign customers to EVs and determine route order.
Considers:
Vehicle capacity
Battery range
Recharging needs
Time constraints

3️⃣ Visualization
The visualization/ package plots optimized routes using matplotlib or plotly.
Displays:
Route paths
Charging stops
Distance and time summaries

4️⃣ Running the Project
Command-line mode: Runs optimization and outputs results to console and plots.
Streamlit mode (app.py): Launches a UI for selecting datasets, running optimizations, and viewing results interactively.

🚀 Installation & Usage
Prerequisites
Python 3.8+

Install dependencies:
bash
Copy
Edit
pip install -r requirements.txt
Run from Command Line
bash
Copy
Edit
python main.py --data data/r101.csv --vehicles 5 --battery 300
Run Streamlit Web App
bash
Copy
Edit
streamlit run app.py

📊 Example Output
Optimized route assignment for each EV.
Total distance and energy used.
Charging points visited.

Interactive route maps.

