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

# --- 1. CONFIGURAZIONE PAGINA (Deve essere la prima istruzione) ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# --- 2. GLOBAL LOCK (IL CUORE DELLA VITTORIA SUI 30 SECONDI) ---
@st.cache_resource
def get_global_lock():
    # Oggetto condiviso tra tutti i processi per coordinare il tempo
    return {"last_run_time": 0.0, "df_cache": pd.DataFrame(), "coords_cache": []}

lock = get_global_lock()
tempo_attuale = time.time()

# Verifichiamo se è una raffica (meno di 20 secondi dall'ultimo aggiornamento reale)
is_raffica = (tempo_attuale - lock["last_run_time"]) < 20

# Eseguiamo il refresh ogni 30s con KEY FISSA
st_autorefresh(interval=30000, key="timer_granitico_30s")

# Timestamp millesimale per il tuo monitoraggio
ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]

# --- 3. CARICAMENTO DATI (Solo se NON è una raffica) ---
if not is_raffica:
    lock["last_run_time"] = tempo_attuale
    conn = st.connection("postgresql", type="sql")
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        
        lock["df_cache"] = df_m
        if not df_r.empty:
            val = df_r.iloc[0]['coords'] # Accesso sicuro alla riga 0
            lock["coords_cache"] = json.loads(val) if isinstance(val, str) else val
    except Exception as e:
        st.sidebar.error(f"Errore DB: {e}")

# Recuperiamo i dati dall'oggetto globale (così la visualizzazione non sparisce mai)
df_mandria = lock["df_cache"]
saved_coords = lock["coords_cache"]

# --- 4. COSTRUZIONE MAPPA ---
m = None
if not df_mandria.empty:
    df_valid = df_mandria.dropna(subset=['lat', 'lon'])
    df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]
    c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

    m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

    # --- IL TUO SATELLITE GOOGLE (BLOCCATO) ---
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

# --- 5. LAYOUT (RIPRISTINO TOTALE VISUALIZZAZIONE) ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.sidebar.metric("⏱️ Ora Esecuzione", ora_log)

if is_raffica:
    st.sidebar.warning("⚡ Raffica bloccata: visualizzo dati persistenti")

if not df_mandria.empty and m:
    col_map, col_table = st.columns([3, 1]) # Ripristino proporzioni originali

    with col_map:
        st.caption(f"Ultimo aggiornamento valido: **{datetime.fromtimestamp(lock['last_run_time']).strftime('%H:%M:%S')}**")
        st_folium(m, width="100%", height=650, key="mappa_fissa")

    with col_table:
        st.subheader("⚠️ Emergenze")
        df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
        st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("📝 Storico Mandria")
    st.dataframe(df_mandria, use_container_width=True, hide_index=True)
else:
    st.info("In attesa del primo caricamento dati...")

# Breve pausa per stabilizzare (2 secondi)
time.sleep(2)
