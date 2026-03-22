import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import execute_values
import os

# --- 1. POSTGRESQL CONNECTION ---
# Free PostgreSQL Options:
# 1. Neon (https://neon.tech) - 3GB storage, serverless
# 2. ElephantSQL (https://www.elephantsql.com) - 20MB free tier
# 3. Supabase (https://supabase.com) - 500MB database
# 4. Railway (https://railway.app) - $5 free credit monthly
# 5. Render (https://render.com) - Free PostgreSQL for 90 days

# Add your PostgreSQL connection string to Streamlit secrets:
# In .streamlit/secrets.toml:
# DATABASE_URL = "postgresql://user:password@host:port/database"

@st.cache_resource
def get_db_connection():
    """Create a cached PostgreSQL connection"""
    try:
        # Try to get from Streamlit secrets first, then environment variable
        db_url = st.secrets.get("DATABASE_URL", os.getenv("DATABASE_URL"))
        
        if not db_url:
            st.error("⚠️ Database credentials not found! Please add DATABASE_URL to secrets.")
            st.info("""
            **How to add credentials:**
            
            1. Create a free PostgreSQL database at:
               - Neon: https://neon.tech (Recommended - 3GB free)
               - ElephantSQL: https://www.elephantsql.com (20MB free)
               - Supabase: https://supabase.com (500MB free)
            
            2. Copy your connection string (looks like):
               `postgresql://username:password@host:5432/dbname`
            
            3. Add to Streamlit:
               - Local: Create `.streamlit/secrets.toml` with:
                 ```
                 DATABASE_URL = "your_connection_string"
                 ```
               - Cloud: Settings > Secrets > Add:
                 ```
                 DATABASE_URL = "your_connection_string"
                 ```
            """)
            st.stop()
        
        conn = psycopg2.connect(db_url)
        return conn
    except Exception as e:
        st.error(f"❌ Failed to connect to PostgreSQL: {e}")
        st.info("Please check your DATABASE_URL connection string")
        st.stop()

conn = get_db_connection()

# --- 2. DATABASE INITIALIZATION ---
def init_database():
    """Create tables if they don't exist"""
    try:
        cur = conn.cursor()
        
        # Create inventory table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                id SERIAL PRIMARY KEY,
                date TEXT NOT NULL,
                channel TEXT NOT NULL,
                sku TEXT,
                title TEXT,
                stock REAL,
                mfg_date TEXT,
                shelf_life_pct REAL,
                ageing_bucket TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create prices table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS prices (
                title TEXT PRIMARY KEY,
                cost_price REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create index for faster queries
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_inventory_date_channel 
            ON inventory(date, channel)
        ''')
        
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        st.error(f"Error initializing database: {e}")
        return False

init_database()

# --- 3. DATA FUNCTIONS ---
@st.cache_data(ttl=5)  # Cache for 5 seconds
def load_inventory_data():
    """Load all inventory data from PostgreSQL"""
    try:
        query = "SELECT date, channel, sku, title, stock, mfg_date, shelf_life_pct, ageing_bucket FROM inventory ORDER BY date DESC"
        df = pd.read_sql(query, conn)
        return df
    except Exception as e:
        st.error(f"Error loading inventory: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=5)  # Cache for 5 seconds
def load_price_data():
    """Load all price data from PostgreSQL"""
    try:
        query = "SELECT title, cost_price FROM prices"
        df = pd.read_sql(query, conn)
        return df
    except Exception as e:
        st.error(f"Error loading prices: {e}")
        return pd.DataFrame()

def insert_inventory_snapshot(date_str, channel, records):
    """Insert inventory snapshot into PostgreSQL"""
    try:
        cur = conn.cursor()
        
        # Delete existing records for this date/channel
        cur.execute("DELETE FROM inventory WHERE date = %s AND channel = %s", (date_str, channel))
        
        # Insert new records
        insert_query = """
            INSERT INTO inventory (date, channel, sku, title, stock, mfg_date, shelf_life_pct, ageing_bucket)
            VALUES %s
        """
        execute_values(cur, insert_query, records)
        
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"Error inserting inventory: {e}")
        return False

def upsert_prices(price_records):
    """Update or insert prices in PostgreSQL"""
    try:
        cur = conn.cursor()
        
        for title, price in price_records:
            cur.execute("""
                INSERT INTO prices (title, cost_price, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (title) 
                DO UPDATE SET cost_price = EXCLUDED.cost_price, updated_at = CURRENT_TIMESTAMP
            """, (title, price))
        
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"Error updating prices: {e}")
        return False

def delete_snapshot(date_str, channel):
    """Delete a specific snapshot from PostgreSQL"""
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM inventory WHERE date = %s AND channel = %s", (date_str, channel))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"Error deleting snapshot: {e}")
        return False

# --- 4. APP SETTINGS ---
st.set_page_config(page_title="Inventory Master Dashboard", layout="wide")

# --- 5. LOGIN SYSTEM ---
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

# --- 6. SIDEBAR LOGOUT & UPLOAD ---
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
        with st.spinner("Processing and uploading to cloud database..."):
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
                
                # Prepare records for PostgreSQL
                date_str = u_date.strftime('%Y-%m-%d')
                records = []
                for _, row in df.iterrows():
                    records.append((
                        date_str,
                        u_chan,
                        str(row['SKU']),
                        str(row['Title']),
                        float(row['Total Stock']),
                        str(row['Mfg Date']),
                        float(row['Shelf_Pct']),
                        row['Bucket']
                    ))
                
                # Insert to PostgreSQL
                if insert_inventory_snapshot(date_str, u_chan, records):
                    st.sidebar.success(f"✅ Saved {u_chan} for {u_date} to cloud database!")
                    # Clear cache to reload data
                    load_inventory_data.clear()
                    st.rerun()
                else:
                    st.sidebar.error("Failed to save to database")
                    
            except Exception as e:
                st.sidebar.error(f"❌ Error processing file: {e}")

# --- 7. DATA LOADING ---
inv_df = load_inventory_data()
price_df = load_price_data()

if not price_df.empty:
    prices_dict = dict(zip(price_df['title'], price_df['cost_price']))
else:
    prices_dict = {}

if inv_df.empty:
    st.info("👋 No data found. Please log in as Admin and upload a CSV file to begin.")
    st.info("☁️ All data is stored securely in cloud PostgreSQL database.")
    st.stop()

# Data Cleaning for UI
inv_df['date'] = pd.to_datetime(inv_df['date']).dt.date
# Clean Mfg Date for sorting
inv_df['mfg_date_dt'] = pd.to_datetime(inv_df['mfg_date'], dayfirst=True, errors='coerce')
inv_df['Mfg Month-Year'] = inv_df['mfg_date_dt'].dt.strftime('%b-%Y')

# --- 8. TOP SUMMARY METRICS (LATEST UPLOAD) ---
latest_date = inv_df['date'].max()
latest_summary_df = inv_df[inv_df['date'] == latest_date].copy()
latest_summary_df['Valuation'] = latest_summary_df['stock'] * latest_summary_df['title'].map(prices_dict).fillna(0)

st.title("🚀 Inventory Executive Summary")
st.caption("☁️ Data stored securely in PostgreSQL Cloud Database")

m1, m2, m3 = st.columns(3)
with m1:
    st.metric(label=f"Total Inventory Value (₹)", value=f"₹{latest_summary_df['Valuation'].sum():,.0f}")
with m2:
    st.metric(label="Total Stock Quantity", value=f"{int(latest_summary_df['stock'].sum()):,}")
with m3:
    st.metric(label="Data As On", value=latest_date.strftime('%d-%b-%Y'))

st.divider()

# --- 9. FILTERS ---
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

# --- 10. CHARTS ---

# GRAPH 1: COMPANY TOTAL VIEW (Trend)
st.subheader(f"Company {view_mode} History Trend")
history_data = inv_df.copy()
# Apply filters to history as well
if selected_items: 
    history_data = history_data[history_data['title'].isin(selected_items)]
if selected_mfg: 
    history_data = history_data[history_data['Mfg Month-Year'].isin(selected_mfg)]

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

# --- 11. DETAILED DATA VIEW ---
st.divider()
st.subheader("📋 Detailed Snapshot Data")
st.dataframe(day_data[['channel', 'title', 'mfg_date', 'stock', 'ageing_bucket', 'Value']].rename(columns={'stock': 'Qty'}), 
             use_container_width=True)

# --- 12. ADMIN PANEL ---
if st.session_state.auth == "Admin":
    st.divider()
    st.header("⚙️ Admin Controls")
    t_price, t_del, t_info = st.tabs(["💰 Manage Prices", "🗑️ Manage History", "ℹ️ Database Info"])
    
    with t_price:
        st.write("Update item cost prices below. Click 'Save Prices' to update the dashboard.")
        with st.form("p_form"):
            unique_titles = sorted(inv_df['title'].unique())
            new_ps = {}
            for t in unique_titles:
                current_p = prices_dict.get(t, 0.0)
                new_ps[t] = st.number_input(f"Cost Price: {t}", value=float(current_p), key=f"price_{t}")
            
            if st.form_submit_button("💾 Save Prices"):
                try:
                    price_records = [(title, price) for title, price in new_ps.items()]
                    if upsert_prices(price_records):
                        st.success("✅ Prices successfully updated in cloud database!")
                        # Clear cache to reload data
                        load_price_data.clear()
                        load_inventory_data.clear()
                        st.rerun()
                except Exception as e:
                    st.error(f"❌ Error updating prices: {e}")

    with t_del:
        st.write("Delete specific snapshots from the cloud database.")
        snaps = inv_df[['date', 'channel']].drop_duplicates().sort_values('date', ascending=False)
        
        for i, row in snaps.iterrows():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.text(f"{row['channel']} - {row['date']}")
            with col2:
                if st.button("🗑️ Delete", key=f"del_{i}"):
                    if delete_snapshot(str(row['date']), row['channel']):
                        st.success(f"⚠️ Deleted {row['channel']} snapshot for {row['date']}")
                        # Clear cache to reload data
                        load_inventory_data.clear()
                        st.rerun()
    
    with t_info:
        st.subheader("📊 Database Statistics")
        try:
            cur = conn.cursor()
            
            # Count records
            cur.execute("SELECT COUNT(*) FROM inventory")
            inv_count = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM prices")
            price_count = cur.fetchone()[0]
            
            # Database size (if supported)
            try:
                cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
                db_size = cur.fetchone()[0]
            except:
                db_size = "N/A"
            
            cur.close()
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Inventory Records", f"{inv_count:,}")
            with col2:
                st.metric("Price Records", f"{price_count:,}")
            with col3:
                st.metric("Database Size", db_size)
            
            st.info("✅ Connected to PostgreSQL Cloud Database")
            
        except Exception as e:
            st.error(f"Error fetching database stats: {e}")
