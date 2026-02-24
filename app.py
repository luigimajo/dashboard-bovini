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

# --- 2. ANTI-TRIPLETTE: KEY DINAMICA DI SESSIONE ---
if "run_count" not in st.session_state:
    st.session_state.run_count = 0
st.session_state.run_count += 1

# Il timer si resetta ad ogni esecuzione per evitare accumuli nel browser
st_autorefresh(interval=30000, key=f"timer_anti_scarica_{st.session_state.run_count}")

# Timestamp per monitoraggio
ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]

# --- 3. CARICAMENTO DATI ---
conn = st.connection("postgresql", type="sql")

@st.cache_data(ttl=2)
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = []
        if not df_r.empty:
            # Accesso sicuro per colonna
            val = df_r.iloc[0]['coords']
            coords = json.loads(val) if isinstance(val, str) else val
        return df_m, coords
    except:
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 4. COSTRUZIONE MAPPA CON TUO SATELLITE GOOGLE ---
# Verifichiamo che il dataframe non sia vuoto e contenga le colonne necessarie
if not df_mandria.empty and 'lat' in df_mandria.columns and 'lon' in df_mandria.columns:
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

# --- 5. LAYOUT ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.sidebar.metric("⏱️ Refresh n.", st.session_state.run_count)
st.sidebar.write(f"Ora: {ora_log}")

if not df_mandria.empty and 'lat' in df_mandria.columns:
    col_map, col_table = st.columns([2, 1])

    with col_map:
        st.caption(f"Visualizzazione stabile alle: **{ora_log}**")
        st_folium(m, width="100%", height=650, key=f"map_instance_{st.session_state.run_count}")

    with col_table:
        st.subheader("⚠️ Emergenze")
        df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
        st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

    st.divider()
    st.subheader("📝 Storico Mandria")
    st.dataframe(df_mandria, use_container_width=True, hide_index=True)
else:
    st.warning("Dati non disponibili o caricamento in corso...")

# --- 6. RITARDO DI STABILIZZAZIONE FINALE ---
time.sleep(2)
