import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# --- APP CONFIGURATION ---
st.set_page_config(page_title="Inventory Ageing Tracker", layout="wide")

# --- MOCK DATABASE (In-memory for this build) ---
if 'cost_prices' not in st.session_state:
    # Pre-populating with some data from your sample
    st.session_state.cost_prices = {
        "Dryfruit Instant Energy Laddubar Mini Pack of 15": 160.0,
        "LADDUBAR Diwali Gift Hamper (Gift Box)": 750.0,
        "Sabudana Farali Mixture (100 g)": 40.0
    }

if 'inventory_db' not in st.session_state:
    st.session_state.inventory_db = pd.DataFrame()

# --- HELPER FUNCTIONS ---
def calculate_ageing_bucket(shelf_life_str):
    try:
        pct = float(str(shelf_life_str).replace('%', ''))
        if pct > 80: return '>80% shelf life'
        if pct >= 60: return '60-80% shelf life'
        if pct >= 40: return '40-60% shelf life'
        return '<40% shelf life'
    except:
        return '<40% shelf life'

# --- SIDEBAR: AUTHENTICATION & UPLOAD ---
st.sidebar.title("🔐 Access Control")
user_role = st.sidebar.radio("Select Role:", ["Viewer", "Admin"])

st.sidebar.divider()

if user_role == "Admin":
    st.sidebar.header("📤 Upload Inventory")
    upload_date = st.sidebar.date_input("Inventory Date", datetime.now())
    channel = st.sidebar.selectbox("Channel", ["B2B", "B2C"])
    uploaded_file = st.sidebar.file_uploader(f"Upload {channel} CSV", type="csv")

    if uploaded_file and st.sidebar.button("Process & Save Snapshot"):
        new_data = pd.read_csv(uploaded_file)
        new_data['Snapshot_Date'] = upload_date
        new_data['Channel'] = channel
        
        # Append to main DB
        st.session_state.inventory_db = pd.concat([st.session_state.inventory_db, new_data], ignore_index=True)
        st.sidebar.success(f"Saved {channel} for {upload_date}")

# --- MAIN INTERFACE ---
st.title("📦 Inventory Ageing & Valuation Dashboard")

if st.session_state.inventory_db.empty:
    st.info("Please upload a CSV file in the Admin sidebar to begin.")
else:
    df = st.session_state.inventory_db.copy()
    
    # Data Cleaning & Logic
    df['Ageing Bucket'] = df['Shelf Life'].apply(calculate_ageing_bucket)
    df['Cost Price'] = df['Title'].map(st.session_state.cost_prices).fillna(0)
    df['Total Stock'] = pd.to_numeric(df['Total Stock'], errors='coerce').fillna(0)
    df['Inventory Value'] = df['Total Stock'] * df['Cost Price']

    # --- FILTERS ---
    col1, col2, col3 = st.columns(3)
    with col1:
        f_date = st.multiselect("Filter by Date", df['Snapshot_Date'].unique(), default=df['Snapshot_Date'].unique())
    with col2:
        f_item = st.multiselect("Filter by Product", df['Title'].unique())
    with col3:
        f_channel = st.multiselect("Filter by Channel", ["B2B", "B2C"], default=["B2B", "B2C"])

    filtered_df = df[df['Snapshot_Date'].isin(f_date) & df['Channel'].isin(f_channel)]
    if f_item:
        filtered_df = filtered_df[filtered_df['Title'].isin(f_item)]

    # --- METRICS ---
    total_val = filtered_df['Inventory Value'].sum()
    total_units = filtered_df['Total Stock'].sum()
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Inventory Value", f"₹{total_val:,.2f}")
    m2.metric("Total Units in Hand", f"{int(total_units):,}")
    m3.metric("New Items (Price Pending)", len(filtered_df[filtered_df['Cost Price'] == 0]['Title'].unique()))

    # --- VISUALS ---
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        st.subheader("Shelf Life Distribution (Units)")
        fig_pie = px.pie(filtered_df, values='Total Stock', names='Ageing Bucket', 
                         color='Ageing Bucket',
                         color_discrete_map={'>80% shelf life':'green', '60-80% shelf life':'blue', 
                                             '40-60% shelf life':'orange', '<40% shelf life':'red'})
        st.plotly_chart(fig_pie, use_container_width=True)

    with chart_col2:
        st.subheader("Inventory Value by Product")
        val_chart = filtered_df.groupby('Title')['Inventory Value'].sum().sort_values(ascending=False).head(10)
        st.bar_chart(val_chart)

    # --- DATA TABLE ---
    st.subheader("Detailed Inventory List")
    st.dataframe(filtered_df[['Snapshot_Date', 'Channel', 'Title', 'Total Stock', 'Mfg Date', 'Ageing Bucket', 'Cost Price', 'Inventory Value']])

# --- ADMIN: CONFIGURATION PANEL ---
if user_role == "Admin":
    st.divider()
    st.header("⚙️ Admin Configuration")
    
    tab1, tab2 = st.tabs(["Update Cost Prices", "Manage Snapshots"])
    
    with tab1:
        st.write("Set cost prices for items to calculate net inventory value.")
        if not st.session_state.inventory_db.empty:
            all_items = st.session_state.inventory_db['Title'].unique()
            for item in all_items:
                current_price = st.session_state.cost_prices.get(item, 0.0)
                new_price = st.number_input(f"Cost Price for {item}", value=float(current_price), key=item)
                st.session_state.cost_prices[item] = new_price
            if st.button("Save All Prices"):
                st.success("Prices updated successfully!")

    with tab2:
        st.write("Delete incorrect snapshots.")
        if not st.session_state.inventory_db.empty:
            snapshots = st.session_state.inventory_db[['Snapshot_Date', 'Channel']].drop_duplicates()
            for i, row in snapshots.iterrows():
                if st.button(f"Delete {row['Channel']} - {row['Snapshot_Date']}", key=f"del_{i}"):
                    st.session_state.inventory_db = st.session_state.inventory_db[
                        ~((st.session_state.inventory_db['Snapshot_Date'] == row['Snapshot_Date']) & 
                          (st.session_state.inventory_db['Channel'] == row['Channel']))
                    ]
                    st.rerun()
