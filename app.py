import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3
from datetime import datetime, timedelta
import os

# --- 1. DATABASE ENGINE (IMPROVED) ---
# Use absolute path to ensure database persistence
DB_PATH = os.path.join(os.getcwd(), 'inventory_master.db')

@st.cache_resource
def get_db_connection():
    """Create a cached database connection that persists across reruns"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn

def init_database():
    """Initialize database tables if they don't exist"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS inventory 
                 (date TEXT, channel TEXT, sku TEXT, title TEXT, stock REAL, 
                  mfg_date TEXT, shelf_life_pct REAL, ageing_bucket TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS prices 
                 (title TEXT PRIMARY KEY, cost_price REAL)''')
    conn.commit()
    return conn

# Initialize database
conn = init_database()
c = conn.cursor()

# --- 2. APP SETTINGS ---
st.set_page_config(page_title="Inventory Master Dashboard", layout="wide")

# --- 3. LOGIN SYSTEM ---
if 'auth' not in st.session_state:
    st.session_state.auth = None

if st.session_state.auth is None:
    st.title("🔐 Inventory System Login")
    user = st.selectbox("Select User Role", ["Viewer", "Admin"])
    pwd = st.text_input("Enter Password", type="password")
    if st.button("Login"):
        if (user == "Admin" and pwd == "admin123") or (user == "Viewer" and pwd == "view123"):
            st.session_state.auth = user
            st.rerun()
        else:
            st.error("Incorrect Password.")
    st.stop()

# --- 4. SIDEBAR LOGOUT & UPLOAD ---
st.sidebar.title(f"👤 {st.session_state.auth} Mode")
if st.sidebar.button("Logout"):
    st.session_state.auth = None
    st.rerun()

if st.session_state.auth == "Admin":
    st.sidebar.divider()
    st.sidebar.header("📤 Upload Snapshot")
    u_date = st.sidebar.date_input("Select Date", datetime.now())
    u_chan = st.sidebar.selectbox("Select Channel", ["B2B", "B2C"])
    u_file = st.sidebar.file_uploader("Choose WMS CSV file", type="csv")
    
    if u_file and st.sidebar.button("Process & Save Snapshot"):
        try:
            df = pd.read_csv(u_file)
            # Clean shelf life percentage
            df['Shelf_Pct'] = pd.to_numeric(df['Shelf Life'].astype(str).str.replace('%',''), errors='coerce').fillna(0)
            
            def get_bucket(p):
                if p > 80: return ">80% shelf life"
                if p >= 60: return "60-80% shelf life"
                if p >= 40: return "40-60% shelf life"
                return "<40% shelf life"
            df['Bucket'] = df['Shelf_Pct'].apply(get_bucket)
            
            # Remove existing data for this date/channel to prevent duplicates
            c.execute("DELETE FROM inventory WHERE date=? AND channel=?", (u_date.strftime('%Y-%m-%d'), u_chan))
            conn.commit()  # Commit deletion first
            
            # Insert new data
            for _, row in df.iterrows():
                c.execute("INSERT INTO inventory VALUES (?,?,?,?,?,?,?,?)", 
                          (u_date.strftime('%Y-%m-%d'), u_chan, row['SKU'], row['Title'], 
                           row['Total Stock'], row['Mfg Date'], row['Shelf_Pct'], row['Bucket']))
            
            conn.commit()  # Commit all inserts
            st.sidebar.success(f"✅ Saved {u_chan} for {u_date}")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"❌ Error processing file: {e}")
            conn.rollback()  # Rollback on error

# --- 5. DATA LOADING ---
@st.cache_data(ttl=1)  # Cache for 1 second to allow updates
def load_inventory_data():
    """Load inventory data from database with caching"""
    return pd.read_sql("SELECT * FROM inventory", conn)

@st.cache_data(ttl=1)  # Cache for 1 second to allow updates
def load_price_data():
    """Load price data from database with caching"""
    return pd.read_sql("SELECT * FROM prices", conn)

inv_df = load_inventory_data()
price_df = load_price_data()
prices_dict = dict(zip(price_df.title, price_df.cost_price))

if inv_df.empty:
    st.info("👋 No data found. Please log in as Admin and upload a CSV file to begin.")
    st.stop()

# Data Cleaning for UI
inv_df['date'] = pd.to_datetime(inv_df['date']).dt.date
# Clean Mfg Date for sorting (Handling potential erratic strings)
inv_df['mfg_date_dt'] = pd.to_datetime(inv_df['mfg_date'], dayfirst=True, errors='coerce')
inv_df['Mfg Month-Year'] = inv_df['mfg_date_dt'].dt.strftime('%b-%Y')

# --- 6. TOP SUMMARY METRICS (LATEST UPLOAD) ---
latest_date = inv_df['date'].max()
latest_summary_df = inv_df[inv_df['date'] == latest_date].copy()
latest_summary_df['Valuation'] = latest_summary_df['stock'] * latest_summary_df['title'].map(prices_dict).fillna(0)

st.title("🚀 Inventory Executive Summary")
m1, m2, m3 = st.columns(3)
with m1:
    st.metric(label=f"Total Inventory Value (₹)", value=f"₹{latest_summary_df['Valuation'].sum():,.0f}")
with m2:
    st.metric(label="Total Stock Quantity", value=f"{int(latest_summary_df['stock'].sum()):,}")
with m3:
    st.metric(label="Data As On", value=latest_date.strftime('%d-%b-%Y'))

st.divider()

# --- 7. FILTERS ---
st.subheader("🔍 Deep Dive Filters")
f_col1, f_col2, f_col3 = st.columns(3)

with f_col1:
    view_date = st.selectbox("Snapshot Date", sorted(inv_df['date'].unique(), reverse=True))
    day_data = inv_df[inv_df['date'] == view_date].copy()

with f_col2:
    available_items = sorted(day_data['title'].unique())
    selected_items = st.multiselect("Filter Products", options=available_items)
    if selected_items:
        day_data = day_data[day_data['title'].isin(selected_items)]

with f_col3:
    # Sort Mfg periods chronologically
    available_mfg = day_data.dropna(subset=['mfg_date_dt']).sort_values('mfg_date_dt')['Mfg Month-Year'].unique()
    selected_mfg = st.multiselect("Filter Mfg Period", options=available_mfg)
    if selected_mfg:
        day_data = day_data[day_data['Mfg Month-Year'].isin(selected_mfg)]

day_data['Cost'] = day_data['title'].map(prices_dict).fillna(0)
day_data['Value'] = day_data['stock'] * day_data['Cost']

view_mode = st.radio("Display Metric:", ["Quantity (Units)", "Value (Rupees)"], horizontal=True)
metric = 'stock' if "Quantity" in view_mode else 'Value'

# --- 8. CHARTS ---

# GRAPH 1: COMPANY TOTAL VIEW (Trend)
st.subheader(f"Company {view_mode} History Trend")
history_data = inv_df.copy()
# Apply filters to history as well for consistency
if selected_items: history_data = history_data[history_data['title'].isin(selected_items)]
if selected_mfg: history_data = history_data[history_data['Mfg Month-Year'].isin(selected_mfg)]

history_data['Cost'] = history_data['title'].map(prices_dict).fillna(0)
history_data['Value'] = history_data['stock'] * history_data['Cost']
company_trend = history_data.groupby(['date', 'channel'])[metric].sum().reset_index().sort_values('date')

fig_trend = px.bar(company_trend, x='date', y=metric, color='channel', barmode='stack', 
                   color_discrete_map={'B2B': '#3498db', 'B2C': '#e67e22'})
st.plotly_chart(fig_trend, use_container_width=True)

# GRAPH 2: ITEM WISE VIEW (Horizontal)
st.subheader(f"Item-Wise Breakdown for {view_date}")
item_summary = day_data.groupby(['title', 'channel'])[metric].sum().reset_index()
fig_items = px.bar(item_summary, x=metric, y='title', color='channel', 
                   orientation='h', barmode='stack', height=max(400, len(item_summary)*25))
fig_items.update_layout(yaxis={'categoryorder':'total ascending'})
st.plotly_chart(fig_items, use_container_width=True)

c1, c2 = st.columns(2)
with c1:
    st.subheader("Ageing Status")
    fig_pie = px.pie(day_data, values=metric, names='ageing_bucket', hole=0.5,
                     color='ageing_bucket',
                     color_discrete_map={">80% shelf life":"#27ae60", "60-80% shelf life":"#2980b9", 
                                         "40-60% shelf life":"#f39c12", "<40% shelf life":"#e74c3c"})
    st.plotly_chart(fig_pie, use_container_width=True)

with c2:
    st.subheader(f"{view_mode} by Mfg Date (Chronological)")
    mfg_sum = day_data.groupby(['mfg_date', 'mfg_date_dt'])[metric].sum().reset_index().sort_values('mfg_date_dt')
    fig_mfg = px.bar(mfg_sum, x='mfg_date', y=metric, color_discrete_sequence=['#9b59b6'])
    fig_mfg.update_layout(xaxis={'categoryorder':'array', 'categoryarray': mfg_sum['mfg_date']})
    st.plotly_chart(fig_mfg, use_container_width=True)

# --- 9. DETAILED DATA VIEW ---
st.divider()
st.subheader("📋 Detailed Snapshot Data")
st.dataframe(day_data[['channel', 'title', 'mfg_date', 'stock', 'ageing_bucket', 'Value']].rename(columns={'stock': 'Qty'}), 
             use_container_width=True)

# --- 10. ADMIN PANEL ---
if st.session_state.auth == "Admin":
    st.divider()
    st.header("⚙️ Admin Controls")
    t_price, t_del = st.tabs(["💰 Manage Prices", "🗑️ Manage History"])
    
    with t_price:
        st.write("Update item cost prices below. Click 'Save Prices' to update the dashboard.")
        with st.form("p_form"):
            unique_titles = sorted(inv_df['title'].unique())
            new_ps = {}
            for t in unique_titles:
                current_p = prices_dict.get(t, 0.0)
                new_ps[t] = st.number_input(f"Cost Price: {t}", value=float(current_p))
            if st.form_submit_button("Save Prices"):
                try:
                    for title, price in new_ps.items():
                        c.execute("INSERT OR REPLACE INTO prices (title, cost_price) VALUES (?, ?)", (title, price))
                    conn.commit()  # Commit all price updates
                    st.success("✅ Prices successfully updated in database!")
                    # Clear cache to force reload
                    load_price_data.clear()
                    load_inventory_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error updating prices: {e}")
                    conn.rollback()

    with t_del:
        st.write("Delete specific snapshots from the database history.")
        snaps = inv_df[['date', 'channel']].drop_duplicates()
        for i, row in snaps.iterrows():
            if st.button(f"🗑️ Delete {row['channel']} - {row['date']}", key=f"del_{i}"):
                try:
                    c.execute("DELETE FROM inventory WHERE date=? AND channel=?", (str(row['date']), row['channel']))
                    conn.commit()  # Commit deletion
                    st.warning(f"⚠️ Deleted {row['channel']} snapshot for {row['date']}")
                    # Clear cache to force reload
                    load_inventory_data.clear()
                    load_price_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error deleting snapshot: {e}")
                    conn.rollback()

# Display database location for reference
if st.session_state.auth == "Admin":
    with st.expander("ℹ️ Database Information"):
        st.info(f"**Database Location:** `{DB_PATH}`")
        st.info(f"**Database exists:** {os.path.exists(DB_PATH)}")
        if os.path.exists(DB_PATH):
            st.info(f"**Database size:** {os.path.getsize(DB_PATH):,} bytes")
