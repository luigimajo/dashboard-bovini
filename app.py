import streamlit as st
from streamlit_autorefresh import st_autorefresh
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text
from datetime import datetime
import time

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# --- 2. GLOBAL LOCK (L'UNICO MODO PER FERMARE LE TRIPLETTES) ---
# st.cache_resource crea un oggetto condiviso tra TUTTI i processi dell'app
@st.cache_resource
def get_global_lock():
    return {"last_run": 0.0}

global_lock = get_global_lock()
ora_attuale = time.time()

# Se l'ultimo refresh globale è avvenuto meno di 15 secondi fa, questa è una scarica
is_scarica = (ora_attuale - global_lock["last_run"]) < 15

if not is_scarica:
    global_lock["last_run"] = ora_attuale

# --- 3. REFRESH STABILIZZATO ---
st_autorefresh(interval=30000, key="timer_unico_stabile_30s")
ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]

# --- 4. CARICAMENTO DATI (Solo se NON è una scarica) ---
conn = st.connection("postgresql", type="sql")

@st.cache_data(ttl=10) # Cache di 10s per servire i dati alle scariche senza interrogare il DB
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = []
        if not df_r.empty:
            val = df_r.iloc[0]['coords']
            coords = json.loads(val) if isinstance(val, str) else val
        return df_m, coords
    except:
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 5. COSTRUZIONE MAPPA ---
df_valid = df_mandria.dropna(subset=['lat', 'lon'])
df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]
c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# --- IL TUO SATELLITE GOOGLE (FISSO) ---
folium.TileLayer(
    tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
    attr='Google Satellite',
    name='Google Satellite',
    overlay=False,
    control=False
).add_to(m)

if saved_coords:
    folium.Polygon(locations=saved_coords, color="yellow", weight=3, fill=True, fill_opacity=0.2).add_to(m)

for _, row in df_mandria.iterrows():
    if pd.notna(row['lat']) and row['lat'] != 0:
        color = 'green' if row['stato_recinto'] == 'DENTRO' else 'red'
        folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color=color, icon='info-sign')).add_to(m)

Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)

# --- 6. LAYOUT ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.sidebar.info(f"Esecuzione: {ora_log}")

if is_scarica:
    st.sidebar.warning("⚡ Scarica bloccata dal Global Lock")

col_map, col_table = st.columns([3, 1])

with col_map:
    # Mostriamo i dati dell'ultima esecuzione valida
    st.caption(f"Ultimo aggiornamento valido alle: **{datetime.fromtimestamp(global_lock['last_run']).strftime('%H:%M:%S')}**")
    st_folium(m, width="100%", height=650, key="mappa_fissa")

with col_table:
    st.subheader("⚠️ Emergenze")
    df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
    st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

st.divider()
st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)

# Breve pausa finale per scaricare il server
time.sleep(2)
