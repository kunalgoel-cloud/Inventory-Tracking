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
    col_l, col_r = st.columns(2)
    with col_l:
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

# --- 5. DATA LOADING ---
inv_df = pd.read_sql("SELECT * FROM inventory", conn)
price_df = pd.read_sql("SELECT * FROM prices", conn)
prices_dict = dict(zip(price_df.title, price_df.cost_price))

if inv_df.empty:
    st.info("👋 Welcome! Please log in as Admin and upload your first WMS CSV file.")
    st.stop()

# --- 6. FILTERS & LOGIC ---
st.title("📊 Inventory Health & Valuation")

# Time Filter Row
st.subheader("🔍 Filters")
t1, t2, t3, t4 = st.columns(4)
today = datetime.now().date()
filtered_start_date = datetime(2000, 1, 1).date()

if t1.button("Last 7 Days", use_container_width=True): filtered_start_date = today - timedelta(days=7)
if t2.button("MTD", use_container_width=True): filtered_start_date = today.replace(day=1)
if t3.button("Last 30 Days", use_container_width=True): filtered_start_date = today - timedelta(days=30)
if t4.button("Show All History", use_container_width=True): filtered_start_date = datetime(2000, 1, 1).date()

# Apply Date Filtering
inv_df['date'] = pd.to_datetime(inv_df['date']).dt.date
data_filtered = inv_df[inv_df['date'] >= filtered_start_date].copy()

# ADDED: Item Name Filter
all_items = sorted(data_filtered['title'].unique())
selected_items = st.multiselect("Filter by Product Name:", options=all_items, default=[])

# Apply Item Filter if something is selected
if selected_items:
    data_filtered = data_filtered[data_filtered['title'].isin(selected_items)]

data_filtered['Cost'] = data_filtered['title'].map(prices_dict).fillna(0)
data_filtered['Value'] = data_filtered['stock'] * data_filtered['Cost']

# View Toggle
view_mode = st.radio("Display Data By:", ["Quantity (Units)", "Value (Rupees)"], horizontal=True)
metric = 'stock' if "Quantity" in view_mode else 'Value'

# --- 7. CHARTS ---
st.subheader(f"Inventory {view_mode} Trend")
date_summary = data_filtered.groupby(['date', 'channel'])[metric].sum().reset_index()
fig_trend = px.bar(date_summary, x='date', y=metric, color='channel', barmode='group')
st.plotly_chart(fig_trend, use_container_width=True)

c1, c2 = st.columns(2)
with c1:
    st.subheader(f"Top Items by {view_mode}")
    item_summary = data_filtered.groupby('title')[metric].sum().sort_values(ascending=False).head(10).reset_index()
    fig_items = px.bar(item_summary, x=metric, y='title', orientation='h', color_discrete_sequence=['#2ecc71'])
    st.plotly_chart(fig_items, use_container_width=True)

with c2:
    latest_upload = data_filtered['date'].max()
    st.subheader(f"Shelf Life Status (As on {latest_upload})")
    latest_data = data_filtered[data_filtered['date'] == latest_upload]
    fig_pie = px.pie(latest_data, values=metric, names='ageing_bucket', hole=0.5,
                     color='ageing_bucket',
                     color_discrete_map={">80% shelf life":"#27ae60", "60-80% shelf life":"#2980b9", 
                                         "40-60% shelf life":"#f39c12", "<40% shelf life":"#e74c3c"})
    st.plotly_chart(fig_pie, use_container_width=True)

# --- 8. DATA TABLE ---
st.divider()
st.subheader("📋 Detailed Data View")
st.dataframe(data_filtered[['date', 'channel', 'title', 'stock', 'ageing_bucket', 'Cost', 'Value']], use_container_width=True)

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
                new_prices[t] = st.number_input(f"Cost Price: {t}", value=float(current_p), step=0.1)
            if st.form_submit_button("Save All Prices"):
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
