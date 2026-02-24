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

# --- 2. FILTRO ANTI-SCARICA (EVITA SCHERMO BIANCO) ---
ora_attuale_unix = time.time()
if "ultimo_refresh_effettivo" not in st.session_state:
    st.session_state.ultimo_refresh_effettivo = 0.0

# Calcoliamo se questo refresh è una "scarica" (meno di 15 secondi dal precedente)
is_scarica = (ora_attuale_unix - st.session_state.ultimo_refresh_effettivo) < 15

# --- 3. REFRESH STABILIZZATO ---
# Il timer deve essere SEMPRE presente per evitare che l'app muoia
st_autorefresh(interval=30000, key="timer_unico_stabile")

# Se NON è una scarica, aggiorniamo il timestamp di esecuzione reale
if not is_scarica:
    st.session_state.ultimo_refresh_effettivo = ora_attuale_unix

# Timestamp con MILLESIMESIMI per il tuo debug
ora_esecuzione = datetime.now().strftime("%H:%M:%S.%f")[:-3]

# --- 4. CARICAMENTO DATI E MAPPA (SOLO SE NON È UNA SCARICA) ---
if not is_scarica:
    conn = st.connection("postgresql", type="sql")
    
    @st.cache_data(ttl=2)
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

    # --- COSTRUZIONE MAPPA ---
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

# --- 5. LAYOUT (SEMPRE VISIBILE) ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.sidebar.metric("⏱️ Ultimo Refresh Valido", ora_esecuzione)

if is_scarica:
    st.warning("⚡ Scarica di refresh rilevata: attesa stabilizzazione...")
    st.info("L'app caricherà i dati al prossimo intervallo di 30s.")
else:
    col_map, col_table = st.columns([3, 1])
    with col_map:
        st.caption(f"Script eseguito alle: **{ora_esecuzione}**")
        st_folium(m, width="100%", height=650, key="mappa_fissa")

    with col_table:
        st.subheader("⚠️ Emergenze")
        df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
        st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

    st.divider()
    st.subheader("📝 Storico Mandria")
    st.dataframe(df_mandria, use_container_width=True, hide_index=True)
