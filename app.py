import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3
from datetime import datetime, timedelta

# --- 1. DATABASE ENGINE ---
conn = sqlite3.connect('inventory_master.db', check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS inventory 
             (date TEXT, channel TEXT, sku TEXT, title TEXT, stock REAL, mfg_date TEXT, shelf_life_pct REAL, ageing_bucket TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS prices 
             (title TEXT PRIMARY KEY, cost_price REAL)''')
conn.commit()

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
            df['Shelf_Pct'] = pd.to_numeric(df['Shelf Life'].str.replace('%',''), errors='coerce').fillna(0)
            def get_bucket(p):
                if p > 80: return ">80% shelf life"
                if p >= 60: return "60-80% shelf life"
                if p >= 40: return "40-60% shelf life"
                return "<40% shelf life"
            df['Bucket'] = df['Shelf_Pct'].apply(get_bucket)
            
            c.execute("DELETE FROM inventory WHERE date=? AND channel=?", (u_date.strftime('%Y-%m-%d'), u_chan))
            for _, row in df.iterrows():
                c.execute("INSERT INTO inventory VALUES (?,?,?,?,?,?,?,?)", 
                          (u_date.strftime('%Y-%m-%d'), u_chan, row['SKU'], row['Title'], row['Total Stock'], row['Mfg Date'], row['Shelf_Pct'], row['Bucket']))
            conn.commit()
            st.sidebar.success(f"Saved {u_chan} for {u_date}")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Error: {e}")

# --- 5. DATA LOADING & CLEANING ---
inv_df = pd.read_sql("SELECT * FROM inventory", conn)
price_df = pd.read_sql("SELECT * FROM prices", conn)
prices_dict = dict(zip(price_df.title, price_df.cost_price))

if inv_df.empty:
    st.info("👋 Welcome! Admin needs to upload a CSV file to begin.")
    st.stop()

# Convert to proper date objects
inv_df['date'] = pd.to_datetime(inv_df['date']).dt.date
inv_df['mfg_date_dt'] = pd.to_datetime(inv_df['mfg_date'], dayfirst=True, errors='coerce')
inv_df['Mfg Month-Year'] = inv_df['mfg_date_dt'].dt.strftime('%b-%Y')

# IMPORTANT: Find the absolute latest date of inventory uploaded
latest_overall_date = inv_df['date'].max()

# --- 6. FILTERS ---
st.title("📊 Inventory Health & Valuation")
st.subheader(f"🔍 Filters (Showing data based on last upload: {latest_overall_date})")

f_col1, f_col2, f_col3 = st.columns(3)

with f_col1:
    # Filter the primary data based on the chosen snapshot date
    # Defaults to the latest available day in the DB
    view_date = st.selectbox("Select Inventory Snapshot Date", sorted(inv_df['date'].unique(), reverse=True))
    data_filtered = inv_df[inv_df['date'] == view_date].copy()

with f_col2:
    # Item Name Filter (Only shows items present in that day's data)
    available_items = sorted(data_filtered['title'].unique())
    selected_items = st.multiselect("Filter by Product Name:", options=available_items)
    if selected_items:
        data_filtered = data_filtered[data_filtered['title'].isin(selected_items)]

with f_col3:
    # Mfg Month-Year Filter (Only picks dates present in THIS specific snapshot)
    available_mfg = sorted(data_filtered['Mfg Month-Year'].dropna().unique())
    selected_mfg = st.multiselect("Filter by Mfg Month-Year (of current stock):", options=available_mfg)
    if selected_mfg:
        data_filtered = data_filtered[data_filtered['Mfg Month-Year'].isin(selected_mfg)]

# Logic for Valuation
data_filtered['Cost'] = data_filtered['title'].map(prices_dict).fillna(0)
data_filtered['Value'] = data_filtered['stock'] * data_filtered['Cost']

view_mode = st.radio("Display Data By:", ["Quantity (Units)", "Value (Rupees)"], horizontal=True)
metric = 'stock' if "Quantity" in view_mode else 'Value'

# --- 7. CHARTS ---
# A. Stacked Bar Chart: Channel Split
st.subheader(f"Inventory {view_mode} - B2B vs B2C")
fig_trend = px.bar(data_filtered, x='title', y=metric, color='channel', 
                   barmode='stack', title=f"Stock Breakdown for {view_date}")
st.plotly_chart(fig_trend, use_container_width=True)

c1, c2 = st.columns(2)
with c1:
    # B. Mfg Date Detail Chart
    st.subheader(f"{view_mode} by Manufacturing Date")
    mfg_summary = data_filtered.groupby('mfg_date')[metric].sum().reset_index()
    fig_mfg = px.bar(mfg_summary, x='mfg_date', y=metric, color_discrete_sequence=['#9b59b6'])
    st.plotly_chart(fig_mfg, use_container_width=True)

with c2:
    # C. Pie Chart
    st.subheader(f"Shelf Life Status")
    fig_pie = px.pie(data_filtered, values=metric, names='ageing_bucket', hole=0.5,
                     color='ageing_bucket',
                     color_discrete_map={">80% shelf life":"#27ae60", "60-80% shelf life":"#2980b9", 
                                         "40-60% shelf life":"#f39c12", "<40% shelf life":"#e74c3c"})
    st.plotly_chart(fig_pie, use_container_width=True)

# --- 8. DETAILED DATA VIEW ---
st.divider()
st.subheader("📋 Batch-wise Quantity Details")
display_cols = ['channel', 'title', 'mfg_date', 'stock', 'ageing_bucket', 'Cost', 'Value']
st.dataframe(data_filtered[display_cols].rename(columns={'stock': 'Quantity in Batch'}), use_container_width=True)

# --- 9. ADMIN SETTINGS ---
if st.session_state.auth == "Admin":
    st.divider()
    st.header("⚙️ Admin Configuration")
    t_price, t_del = st.tabs(["💰 Update Cost Prices", "🗑️ Manage Snapshots"])
    
    with t_price:
        all_titles_admin = sorted(inv_df['title'].unique())
        with st.form("master_price_form"):
            new_prices = {}
            for t in all_titles_admin:
                current_p = prices_dict.get(t, 0.0)
                new_prices[t] = st.number_input(f"Price: {t}", value=float(current_p))
            if st.form_submit_button("Save Prices"):
                for title, price in new_prices.items():
                    c.execute("INSERT OR REPLACE INTO prices (title, cost_price) VALUES (?, ?)", (title, price))
                conn.commit()
                st.success("Prices saved!")
                st.rerun()

    with t_del:
        snaps = inv_df[['date', 'channel']].drop_duplicates()
        for i, row in snaps.iterrows():
            if st.button(f"Delete {row['channel']} - {row['date']}", key=f"del_{i}"):
                c.execute("DELETE FROM inventory WHERE date=? AND channel=?", (str(row['date']), row['channel']))
                conn.commit()
                st.rerun()
