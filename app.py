import streamlit as st
from streamlit_autorefresh import st_autorefresh
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# --- 2. REFRESH PRIORITARIO (Placeholder) ---
# Creiamo un contenitore vuoto in cima per far partire il timer SUBITO
refresh_area = st.empty()
with refresh_area:
    # Usiamo una key statica per evitare duplicazioni e refresh random
    st_autorefresh(interval=30000, key="timer_primario_30s")

# --- 3. CONNESSIONE E CARICAMENTO DATI ---
conn = st.connection("postgresql", type="sql")

# Usiamo una cache brevissima (2 secondi) per velocizzare i rerun
@st.cache_data(ttl=2)
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        
        coords = []
        if not df_r.empty:
            # Estrazione sicura del JSON delle coordinate
            val = df_r.iloc[0]['coords']
            coords = json.loads(val) if isinstance(val, str) else val
            
        return df_m, coords
    except Exception as e:
        st.error(f"Errore caricamento: {e}")
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 4. COSTRUZIONE MAPPA (Con Google Satellite Fisso) ---
df_valid = df_mandria.dropna(subset=['lat', 'lon'])
df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]
c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

# Creazione mappa base
m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# INSERIMENTO GOOGLE SATELLITE (Sempre attivo)
folium.TileLayer(
    tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
    attr='Google Satellite',
    name='Google Satellite',
    overlay=False,
    control=False
).add_to(m)

# Disegno Recinto Salvato
if saved_coords:
    folium.Polygon(
        locations=saved_coords, 
        color="yellow", 
        weight=3, 
        fill=True, 
        fill_opacity=0.2
    ).add_to(m)

# Marker Bovini
for _, row in df_mandria.iterrows():
    if pd.notna(row['lat']) and row['lat'] != 0:
        color = 'green' if row['stato_recinto'] == 'DENTRO' else 'red'
        folium.Marker(
            [row['lat'], row['lon']], 
            icon=folium.Icon(color=color, icon='info-sign'),
            popup=f"{row['nome']} - Bat: {row['batteria']}%"
        ).add_to(m)

# Strumento Disegno (Solo visualizzazione per ora)
Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)

# --- 5. LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")

col_map, col_table = st.columns([3, 1])

with col_map:
    # Visualizzazione Mappa (Key fissa per stabilità)
    st_folium(m, width="100%", height=650, key="mappa_fissa")

with col_table:
    st.subheader("⚠️ Emergenze")
    df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
    if not df_emergenza.empty:
        st.error(f"Problemi rilevati: {len(df_emergenza)}")
        st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)
    else:
        st.success("✅ Tutto regolare")

st.divider()
st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
