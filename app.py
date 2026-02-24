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

# --- 2. FILTRO ANTI-SCARICA (IL GUARDIANO) ---
ora_attuale_unix = time.time()

if "ultimo_refresh_effettivo" not in st.session_state:
    st.session_state.ultimo_refresh_effettivo = 0.0

# Calcoliamo quanto tempo è passato dall'ultima esecuzione reale
tempo_trascorso = ora_attuale_unix - st.session_state.ultimo_refresh_effettivo

# Se l'esecuzione avviene troppo presto (meno di 20s), ignoriamo la scarica
if tempo_trascorso < 20:
    st.stop() # Interrompe immediatamente l'esecuzione del codice superfluo

# Se arriviamo qui, l'esecuzione è valida. Aggiorniamo il timestamp.
st.session_state.ultimo_refresh_effettivo = ora_attuale_unix

# --- 3. REFRESH STABILIZZATO ---
refresh_area = st.empty()
with refresh_area:
    # Key fissa per non creare nuovi timer
    st_autorefresh(interval=30000, key="timer_unico_stabile")

# Timestamp con MILLESIMESIMI per il tuo debug
ora_esecuzione = datetime.now().strftime("%H:%M:%S.%f")[:-3]

# --- 4. CONNESSIONE E CARICAMENTO DATI ---
conn = st.connection("postgresql", type="sql")

@st.cache_data(ttl=5) # Cache di 5s per stabilizzare
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
st.sidebar.metric("⏱️ Ultimo Refresh Reale", ora_esecuzione)

col_map, col_table = st.columns([3, 1])

with col_map:
    st.caption(f"Script eseguito (validato) alle: **{ora_esecuzione}**")
    st_folium(m, width="100%", height=650, key="mappa_fissa")

with col_table:
    st.subheader("⚠️ Emergenze")
    df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
    st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

st.divider()
st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
