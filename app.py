import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import time

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# Inizializzazione stati persistenti
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False
if "punti_temporanei" not in st.session_state:
    st.session_state.punti_temporanei = []

# --- 2. LOGICA REFRESH (PULIZIA TOTALE IN EDIT) ---
if not st.session_state.edit_mode:
    st_autorefresh(interval=30000, key="timer_stabile_30s")
else:
    st.sidebar.warning("🏗️ MODALITÀ DISEGNO: Refresh Automatico Disabilitato")
    if st.sidebar.button("🔓 Esci e annulla"):
        st.session_state.edit_mode = False
        st.session_state.punti_temporanei = []
        st.rerun()

ora_log = datetime.now().strftime("%H:%M:%S")
conn = st.connection("postgresql", type="sql")

# --- 3. CARICAMENTO DATI ---
@st.cache_data(ttl=2)
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = json.loads(df_r.iloc['coords']) if not df_r.empty else []
        return df_m, coords
    except:
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 4. COSTRUZIONE MAPPA ---
df_valid = df_mandria.dropna(subset=['lat', 'lon']).query("lat!=0")
c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# --- BLOCCO SATELLITE GOOGLE RICHIESTO (ESATTO) ---
folium.TileLayer(
    tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
    attr='Google Satellite',
    name='Google Satellite',
    overlay=False,
    control=False
).add_to(m)

# Mostra il vecchio recinto (Giallo)
if saved_coords:
    folium.Polygon(locations=saved_coords, color="yellow", weight=3, fill=True, fill_opacity=0.2).add_to(m)

# --- MEMORIA DEL DISEGNO IN CORSO ---
# Se stiamo disegnando, visualizziamo i punti e la linea che stai creando
if st.session_state.edit_mode and st.session_state.punti_temporanei:
    # Disegniamo i vertici cliccati finora (Rossi)
    for p in st.session_state.punti_temporanei:
        folium.CircleMarker(location=p, radius=3, color='red', fill=True).add_to(m)
    # Disegniamo la linea di collegamento (Rossa)
    if len(st.session_state.punti_temporanei) > 1:
        folium.PolyLine(locations=st.session_state.punti_temporanei, color="red", weight=2, dash_array='5').add_to(m)

# Mostra bovini
for _, row in df_mandria.iterrows():
    if pd.notna(row['lat']) and row['lat'] != 0:
        color = 'green' if row['stato_recinto'] == 'DENTRO' else 'red'
        folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color=color, icon='info-sign')).add_to(m)

# Abilitiamo lo strumento di disegno
Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)

# --- 5. LAYOUT ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    if not st.session_state.edit_mode:
        if st.button("🏗️ INIZIA DISEGNO NUOVO RECINTO"):
            st.session_state.edit_mode = True
            st.rerun()
    
    # Render Mappa - KEY STATICA
    out = st_folium(m, width="100%", height=650, key="main_map")
    
    # --- CATTURA DATI IN TEMPO REALE ---
    if out and out.get('all_drawings'):
        raw = out['all_drawings'][-1]['geometry']['coordinates']
        # Il GeoJSON è [[Lon, Lat], [Lon, Lat]], noi convertiamo in [[Lat, Lon]]
        st.session_state.punti_temporanei = [[p[1], p[0]] for p in raw]

    # MOSTRA TASTO SALVA
    if st.session_state.edit_mode:
        if st.session_state.punti_temporanei and len(st.session_state.punti_temporanei) > 2:
            st.success(f"📍 Poligono rilevato ({len(st.session_state.punti_temporanei)} punti)")
            if st.button("💾 CONFERMA E SALVA DEFINITIVAMENTE"):
                with conn.session as s:
                    s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), 
                              {"coords": json.dumps(st.session_state.punti_temporanei)})
                    s.commit()
                st.session_state.edit_mode = False
                st.session_state.punti_temporanei = []
                st.success("Recinto salvato!")
                st.rerun()
        else:
            st.info("Disegna il poligono sulla mappa. Chiudilo cliccando sul primo punto.")

with col_table:
    st.subheader("⚠️ Emergenze")
    df_em = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria.get('batteria', 100) <= 20)]
    st.dataframe(df_em[['nome', 'batteria']], hide_index=True)

st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
