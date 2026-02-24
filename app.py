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

# --- 2. SEMAFORO ATOMICO (SOLUZIONE FINALE ALLE TRIPLETTE) ---
@st.cache_resource
def get_global_state():
    # Questo oggetto è unico per TUTTI i processi dell'app
    return {"last_execution_time": 0.0}

global_state = get_global_state()
tempo_attuale = time.time()

# Se un altro refresh (della tripletta) prova a partire meno di 10 secondi dopo, lo uccidiamo
#if (tempo_attuale - global_state["last_execution_time"]) < 10:
#    st.stop()

# Se arriviamo qui, l'esecuzione è valida. Aggiorniamo il timestamp globale.
global_state["last_execution_time"] = tempo_attuale

# --- 3. REFRESH STABILIZZATO ---
# Key statica per non resettare mai il timer del browser
st_autorefresh(interval=30000, key="timer_primario_30s")
ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]

# --- 4. CONNESSIONE E CARICAMENTO DATI ---
conn = st.connection("postgresql", type="sql")

@st.cache_data(ttl=2)
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = []
        if not df_r.empty:
            # Recupero sicuro del valore JSON delle coordinate
            val = df_r.iloc['coords']
            coords = json.loads(val) if isinstance(val, str) else val
        return df_m, coords
    except:
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 5. COSTRUZIONE MAPPA CON IL TUO SATELLITE GOOGLE ---
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

# Pausa finale per stabilizzare il server (2 secondi)
time.sleep(2)
# Se un altro refresh (della tripletta) prova a partire meno di 10 secondi dopo, lo uccidiamo
if (tempo_attuale - global_state["last_execution_time"]) < 10:
    st.stop()
