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
import os

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# Inizializzazione Cache di Sessione per evitare schermi bianchi
if "df_memory" not in st.session_state:
    st.session_state.df_memory = pd.DataFrame()
if "coords_memory" not in st.session_state:
    st.session_state.coords_memory = []

# --- 2. SEMAFORO ANTI-SCARICA (LIVELLO SISTEMA) ---
SEMAFORO_FILE = "/tmp/app_last_run.txt"
ora_attuale = time.time()

def check_semaphore():
    if os.path.exists(SEMAFORO_FILE):
        try:
            with open(SEMAFORO_FILE, "r") as f:
                last_run = float(f.read())
            if (ora_attuale - last_run) < 10:
                return False
        except: pass
    
    try:
        with open(SEMAFORO_FILE, "w") as f:
            f.write(str(ora_attuale))
    except: pass
    return True

is_esecuzione_valida = check_semaphore()

# --- 3. REFRESH STABILIZZATO ---
st_autorefresh(interval=30000, key="timer_unico_stabile_30s")
ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]

# --- 4. CARICAMENTO DATI (Solo se validato dal semaforo) ---
if is_esecuzione_valida:
    conn = st.connection("postgresql", type="sql")
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        
        st.session_state.df_memory = df_m
        if not df_r.empty:
            # Accesso sicuro alla colonna 'coords'
            val = df_r.iloc[0]['coords']
            st.session_state.coords_memory = json.loads(val) if isinstance(val, str) else val
    except: pass

# Usiamo sempre i dati in memoria (persistenza visiva)
df_mandria = st.session_state.df_memory
saved_coords = st.session_state.coords_memory

# --- 5. COSTRUZIONE MAPPA ---
m = None
if not df_mandria.empty:
    df_valid = df_mandria.dropna(subset=['lat', 'lon'])
    df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]
    c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

    m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

    # --- IL TUO SATELLITE GOOGLE (FISSO) ---
    folium.TileLayer(
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
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
st.sidebar.info(f"Ultimo segnale: {ora_log}")

if not is_esecuzione_valida:
    st.sidebar.warning("⚡ Scarica ignorata (Dati persistenti)")

if not df_mandria.empty and m:
    # FIX: st.columns richiede il numero di colonne
    col_map, col_table = st.columns([3, 1])
    with col_map:
        st.caption(f"Dati visualizzati alle: **{ora_log}**")
        st_folium(m, width="100%", height=650, key="mappa_fissa")

    with col_table:
        st.subheader("⚠️ Emergenze")
        df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
        st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

    st.divider()
    st.subheader("📝 Storico Mandria")
    st.dataframe(df_mandria, use_container_width=True, hide_index=True)
else:
    st.info("Caricamento dati iniziale in corso...")

# Pausa finale per stabilizzare
time.sleep(2)
