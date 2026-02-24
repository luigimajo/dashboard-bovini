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

# --- 2. REFRESH FISSO (SOLUZIONE AL LOOP INFINITO) ---
# Usiamo una KEY STATICA. Solo così il browser non resetta il timer a ogni secondo.
if "ultimo_rerun" not in st.session_state:
    st.session_state.ultimo_rerun = time.time()

# Eseguiamo il refresh ogni 30 secondi. 
# La key "timer_fisso_30s" garantisce che Streamlit non crei duplicati.
st_autorefresh(interval=30000, key="timer_fisso_30s")

# Timestamp millesimale per il tuo monitoraggio
ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]

# --- 3. CONNESSIONE E CARICAMENTO DATI ---
conn = st.connection("postgresql", type="sql")

@st.cache_data(ttl=5) # Cache di 5s per stabilizzare le letture dal DB
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = []
        if not df_r.empty:
            # Recupero sicuro del valore JSON delle coordinate
            val = df_r.iloc[0]['coords']
            coords = json.loads(val) if isinstance(val, str) else val
        return df_m, coords
    except:
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 4. COSTRUZIONE MAPPA CON IL TUO SATELLITE GOOGLE ---
# Centriamo la mappa se ci sono dati validi
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

# --- 5. LAYOUT ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.sidebar.metric("⏱️ Ora Ultimo Refresh", ora_log)

if not df_mandria.empty:
    col_map, col_table = st.columns([3, 1])

    with col_map:
        st.caption(f"Visualizzazione aggiornata alle: **{ora_log}**")
        st_folium(m, width="100%", height=650, key="mappa_monitoraggio")

    with col_table:
        st.subheader("⚠️ Emergenze")
        df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
        st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

    st.divider()
    st.subheader("📝 Storico Mandria")
    st.dataframe(df_mandria, use_container_width=True, hide_index=True)
else:
    st.warning("Caricamento dati in corso...")

# --- 6. RITARDO DI SICUREZZA (DEBOUNCE) ---
# Fondamentale per impedire che le "triplettes" browser-side sovraccarichino il server
time.sleep(2)
