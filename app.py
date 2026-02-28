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

# --- 2. FILTRO ANTI-RAFFICA CLIENT-SIDE ---
now = time.time()
if "last_valid_execution" not in st.session_state:
    st.session_state.last_valid_execution = 0.0

# Se il refresh arriva prima di 25 secondi, è una raffica: la ignoriamo e fermiamo tutto
if (now - st.session_state.last_valid_execution) < 25:
    # Mostriamo solo un messaggio minimo e fermiamo l'esecuzione pesante
    st.sidebar.warning("⚡ Raffica intercettata: attesa prossimo ciclo...")
    # Eseguiamo comunque il timer per non rompere il ciclo
    st_autorefresh(interval=30000, key="timer_granitico_30s")
    st.stop() 

# Se arriviamo qui, il refresh è valido
st.session_state.last_valid_execution = now

# --- 3. REFRESH STABILIZZATO ---
st_autorefresh(interval=30000, key="timer_granitico_30s")
ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]

# --- 4. CARICAMENTO DATI ---
conn = st.connection("postgresql", type="sql")

@st.cache_data(ttl=10)
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = []
        if not df_r.empty:
            val = df_r.iloc['coords']
            coords = json.loads(val) if isinstance(val, str) else val
        return df_m, coords
    except:
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 5. COSTRUZIONE MAPPA CON SATELLITE GOOGLE ---
c_lat, c_lon = 37.9747, 13.5753
if not df_mandria.empty and 'lat' in df_mandria.columns:
    df_v = df_mandria.dropna(subset=['lat', 'lon'])
    df_v = df_v[(df_v['lat'] != 0) & (df_v['lon'] != 0)]
    if not df_v.empty:
        c_lat, c_lon = df_v['lat'].mean(), df_v['lon'].mean()

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# --- BLOCCO SATELLITE GOOGLE RICHIESTO (ESATTO) ---
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
st.sidebar.metric("⏱️ Ora Esecuzione", ora_log)

if not df_mandria.empty:
    col_map, col_table = st.columns([3, 1])

    with col_map:
        st.caption(f"Refresh validato alle: **{ora_log}**")
        st_folium(m, width="100%", height=650, key="mappa_fissa")

    with col_table:
        st.subheader("⚠️ Stato")
        df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
        st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

    st.divider()
    st.subheader("📝 Storico Mandria")
    st.dataframe(df_mandria, use_container_width=True, hide_index=True)

# --- 7. RITARDO DI SICUREZZA FINALE ---
# Questo sleep di 5 secondi garantisce che lo script non finisca troppo in fretta
# impedendo al browser di sparare nuove richieste immediate.
time.sleep(5)
