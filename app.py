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

# --- 5. DATA LOADING ---
inv_df = pd.read_sql("SELECT * FROM inventory", conn)
price_df = pd.read_sql("SELECT * FROM prices", conn)
prices_dict = dict(zip(price_df.title, price_df.cost_price))

if inv_df.empty:
    st.info("👋 Welcome! Admin needs to upload a CSV file to begin.")
    st.stop()

inv_df['date'] = pd.to_datetime(inv_df['date']).dt.date
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
    st.metric(label="Latest Upload Date", value=latest_date.strftime('%d-%b-%Y'))

st.divider()

# --- 7. FILTERS ---
st.subheader("🔍 Deep Dive Filters")
f_col1, f_col2, f_col3 = st.columns(3)

with f_col1:
    view_date = st.selectbox("View Historical Snapshot", sorted(inv_df['date'].unique(), reverse=True))
    day_data = inv_df[inv_df['date'] == view_date].copy()

with f_col2:
    available_items = sorted(day_data['title'].unique())
    selected_items = st.multiselect("Filter Products", options=available_items)
    if selected_items:
        day_data = day_data[day_data['title'].isin(selected_items)]

with f_col3:
    available_mfg = day_data.dropna(subset=['mfg_date_dt']).sort_values('mfg_date_dt')['Mfg Month-Year'].unique()
    selected_mfg = st.multiselect("Filter Mfg Period", options=available_mfg)
    if selected_mfg:
        day_data = day_data[day_data['Mfg Month-Year'].isin(selected_mfg)]

day_data['Cost'] = day_data['title'].map(prices_dict).fillna(0)
day_data['Value'] = day_data['stock'] * day_data['Cost']

view_mode = st.radio("Metric:", ["Quantity (Units)", "Value (Rupees)"], horizontal=True)
metric = 'stock' if "Quantity" in view_mode else 'Value'

# --- 8. CHARTS ---

# GRAPH 1: COMPANY TOTAL VIEW
st.subheader(f"Company {view_mode} History")
history_data = inv_df.copy()
if selected_items: history_data = history_data[history_data['title'].isin(selected_items)]
if selected_mfg: history_data = history_data[history_data['Mfg Month-Year'].isin(selected_mfg)]
history_data['Cost'] = history_data['title'].map(prices_dict).fillna(0)
history_data['Value'] = history_data['stock'] * history_data['Cost']
company_trend = history_data.groupby(['date', 'channel'])[metric].sum().reset_index().sort_values('date')
fig_trend = px.bar(company_trend, x='date', y=metric, color='channel', barmode='stack')
st.plotly_chart(fig_trend, use_container_width=True)

# GRAPH 2: ITEM WISE VIEW
st.subheader(f"Item-Wise Breakdown (Snapshot: {view_date})")
item_summary = day_data.groupby(['title', 'channel'])[metric].sum().reset_index()
fig_items = px.bar(item_summary, x=metric, y='title', color='channel', 
                   orientation='h', barmode='stack', height=max(400, len(item_summary)*20))
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
st.subheader("📋 Detailed Batch View")
st.dataframe(day_data[['channel', 'title', 'mfg_date', 'stock', 'ageing_bucket', 'Value']].rename(columns={'stock': 'Qty'}), use_container_width=True)

# --- 10. ADMIN PANEL ---
if st.session_state.auth == "Admin":
    st.divider()
    st.header("⚙️ Admin Panel")
    t_price, t_del = st.tabs(["💰 Prices", "🗑️ Snapshots"])
    with t_price:
        with st.form("p_form"):
            new_ps = {t: st.number_input(f"Price: {t}", value=float(prices_dict.get(t,0.0))) for t in sorted(inv_df['title'].unique())}
            if st.form_submit_button("Save Prices"):
                for title, price in new_ps.items():
                    c.execute("INSERT OR REPLACE INTO prices (title, cost_price) VALUES (?, ?)", (title, price))
                conn.commit()
                st.success("Prices Updated!")
                st.rerun()
    with t_del:
        snaps = inv_df[['date', 'channel']].drop_duplicates()
        for i, row in snaps.iterrows():
            if st.button(f"Delete {row['channel']} - {row['date']}", key=f"del_{i}"):
                c.execute("DELETE FROM inventory WHERE date=? AND channel=?", (str(row['date']), row['channel']))
                conn.commit()
                st.rerun()
