import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3
from datetime import datetime, timedelta

# --- DATABASE SETUP ---
conn = sqlite3.connect('inventory_data.db', check_same_thread=False)
c = conn.cursor()

# Create tables if they don't exist
c.execute('''CREATE TABLE IF NOT EXISTS inventory 
             (date TEXT, channel TEXT, sku TEXT, title TEXT, stock REAL, mfg_date TEXT, shelf_life_pct REAL, ageing_bucket TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS prices 
             (title TEXT PRIMARY KEY, cost_price REAL)''')
conn.commit()

# --- APP CONFIG ---
st.set_page_config(page_title="Inventory Master", layout="wide")

# --- LOGIN SYSTEM ---
if 'auth' not in st.session_state:
    st.session_state.auth = None

if st.session_state.auth is None:
    st.title("🔐 Inventory System Login")
    user = st.selectbox("Select User", ["Viewer", "Admin"])
    pwd = st.text_input("Enter Password", type="password")
    if st.button("Login"):
        if (user == "Admin" and pwd == "admin123") or (user == "Viewer" and pwd == "view123"):
            st.session_state.auth = user
            st.rerun()
        else:
            st.error("Incorrect Password")
    st.stop()

# --- LOGOUT BUTTON ---
if st.sidebar.button("Logout"):
    st.session_state.auth = None
    st.rerun()

# --- ADMIN FUNCTIONS ---
if st.session_state.auth == "Admin":
    with st.sidebar.expander("📤 Upload New WMS Report"):
        u_date = st.date_input("Snapshot Date", datetime.now())
        u_chan = st.selectbox("Channel", ["B2B", "B2C"])
        u_file = st.file_uploader("Upload CSV", type="csv")
        
        if u_file and st.button("Save to Database"):
            df = pd.read_csv(u_file)
            # Logic to calculate ageing
            df['Shelf_Pct'] = pd.to_numeric(df['Shelf Life'].str.replace('%',''), errors='coerce').fillna(0)
            def get_bucket(p):
                if p > 80: return ">80% shelf life"
                if p >= 60: return "60-80% shelf life"
                if p >= 40: return "40-60% shelf life"
                return "<40% shelf life"
            df['Bucket'] = df['Shelf_Pct'].apply(get_bucket)
            
            # Save to SQL
            for _, row in df.iterrows():
                c.execute("INSERT INTO inventory VALUES (?,?,?,?,?,?,?,?)", 
                          (u_date.strftime('%Y-%m-%d'), u_chan, row['SKU'], row['Title'], row['Total Stock'], row['Mfg Date'], row['Shelf_Pct'], row['Bucket']))
            conn.commit()
            st.success("Data Saved!")

# --- DATA RETRIEVAL ---
inv_df = pd.read_sql("SELECT * FROM inventory", conn)
price_df = pd.read_sql("SELECT * FROM prices", conn)
prices_dict = dict(zip(price_df.title, price_df.cost_price))

if inv_df.empty:
    st.info("No data in database. Admin needs to upload reports.")
    st.stop()

# --- DASHBOARD LOGIC ---
st.title(f"📊 Dashboard - Welcome {st.session_state.auth}")

# Time Filters
st.subheader("📅 Time Filters")
t_col1, t_col2, t_col3, t_col4 = st.columns(4)
today = datetime.now()
start_date = datetime(2000, 1, 1).date()

if t_col1.button("Last 7 Days"): start_date = (today - timedelta(days=7)).date()
if t_col2.button("MTD (Month to Date)"): start_date = today.replace(day=1).date()
if t_col3.button("Last 30 Days"): start_date = (today - timedelta(days=30)).date()
if t_col4.button("Show All Time"): start_date = datetime(2000, 1, 1).date()

# Apply logic filters
inv_df['date'] = pd.to_datetime(inv_df['date']).dt.date
filtered_df = inv_df[inv_df['date'] >= start_date]
filtered_df['Cost'] = filtered_df['title'].map(prices_dict).fillna(0)
filtered_df['Value'] = filtered_df['stock'] * filtered_df['Cost']

# --- VIEW TOGGLE ---
view_mode = st.radio("Show Analysis By:", ["Quantity", "Value"], horizontal=True)
metric_col = 'stock' if view_mode == "Quantity" else 'Value'

# --- GRAPHS ---
# 1. Bar Chart: Date vs Metric
st.subheader(f"Inventory {view_mode} Trend by Date")
date_summary = filtered_df.groupby('date')[metric_col].sum().reset_index()
fig1 = px.bar(date_summary, x='date', y=metric_col, color_discrete_sequence=['#3366cc'])
st.plotly_chart(fig1, use_container_width=True)

col_a, col_b = st.columns(2)

with col_a:
    # 2. Bar Chart: Item vs Metric
    st.subheader(f"Top 10 Items by {view_mode}")
    item_summary = filtered_df.groupby('title')[metric_col].sum().sort_values(ascending=False).head(10).reset_index()
    fig2 = px.bar(item_summary, x=metric_col, y='title', orientation='h', color_discrete_sequence=['#109618'])
    st.plotly_chart(fig2, use_container_width=True)

with col_b:
    # 3. Pie Chart: Shelf Life
    latest_date = inv_df['date'].max()
    st.subheader(f"Shelf Life Status (as on {latest_date})")
    latest_data = filtered_df[filtered_df['date'] == latest_date]
    fig3 = px.pie(latest_data, values=metric_col, names='ageing_bucket', hole=0.4,
                 color='ageing_bucket', color_discrete_map={">80% shelf life":"green","60-80% shelf life":"blue","40-60% shelf life":"orange","<40% shelf life":"red"})
    st.plotly_chart(fig3, use_container_width=True)

# --- DATA DOWNLOAD & PRICE EDIT ---
st.divider()
if st.session_state.auth == "Admin":
    st.subheader("💰 Edit Cost Prices")
    all_titles = inv_df['title'].unique()
    for t in all_titles:
        new_p = st.number_input(f"Price for {t}", value=prices_dict.get(t, 0.0), key=t)
        if st.button(f"Update Price for {t[:20]}..."):
            c.execute("INSERT OR REPLACE INTO prices (title, cost_price) VALUES (?, ?)", (t, new_p))
            conn.commit()
            st.success("Price Updated!")

st.subheader("📥 Download Snapshot Data")
csv = filtered_df.to_csv(index=False).encode('utf-8')
st.download_button("Download Current View as CSV", csv, "inventory_report.csv", "text/csv")
