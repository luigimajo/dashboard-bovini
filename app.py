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

# --- 2. FILTRO ANTI-SCARICA ---
ora_attuale_unix = time.time()
if "ultimo_refresh_effettivo" not in st.session_state:
    st.session_state.ultimo_refresh_effettivo = 0.0
if "df_cache" not in st.session_state:
    st.session_state.df_cache = pd.DataFrame()
if "coords_cache" not in st.session_state:
    st.session_state.coords_cache = []

# Determiniamo se è una scarica (meno di 15 secondi)
is_scarica = (ora_attuale_unix - st.session_state.ultimo_refresh_effettivo) < 15

# Timer sempre attivo con KEY fissa per evitare duplicati
# st_autorefresh(interval=30000, key="timer_unico_stabile")

ora_esecuzione = datetime.now().strftime("%H:%M:%S.%f")[:-3]

# --- 3. CARICAMENTO DATI (Solo se NON è una scarica o se la cache è vuota) ---
if not is_scarica or st.session_state.df_cache.empty:
    
    st.session_state.ultimo_refresh_effettivo = ora_attuale_unix
    conn = st.connection("postgresql", type="sql")
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        
        st.session_state.df_cache = df_m
        if not df_r.empty:
            val = df_r.iloc[0]['coords']
            st.session_state.coords_cache = json.loads(val) if isinstance(val, str) else val
    except Exception as e:
        st.error(f"Errore DB: {e}")

# Usiamo i dati dalla sessione (così l'app non fallisce mai se una scarica salta il DB)
df_mandria = st.session_state.df_cache
saved_coords = st.session_state.coords_cache

# --- 4. COSTRUZIONE MAPPA ---
# Verifichiamo che i dati esistano prima di procedere
if not df_mandria.empty:
    df_valid = df_mandria.dropna(subset=['lat', 'lon'])
    df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]
    c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

    m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

    # IL TUO SATELLITE GOOGLE (Richiesto)
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
st.sidebar.metric("⏱️ Ultimo Refresh", ora_esecuzione)

if is_scarica:
    st.sidebar.info("⚡ Scarica ignorata: uso dati in memoria.")

if not df_mandria.empty:
    col_map, col_table = st.columns([3, 1])
    with col_map:
        st.caption(f"Dati aggiornati alle: **{ora_esecuzione}**")
        st_folium(m, width="100%", height=650, key="mappa_fissa")

    with col_table:
        st.subheader("⚠️ Emergenze")
        df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
        st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

    st.divider()
    st.subheader("📝 Storico Mandria")
    st.dataframe(df_mandria, use_container_width=True, hide_index=True)
else:
    st.warning("Caricamento dati in corso...")
if not is_scarica:
    st_autorefresh(interval=30000, key="timer_unico_stabile")
# Breve sleep per stabilizzare
time.sleep(2)
