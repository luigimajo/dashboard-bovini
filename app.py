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

# --- 2. LOGICA REFRESH CON FILTRO DISEGNO ---
# Controlliamo se nella sessione esiste già un disegno in corso sulla mappa "main_map"
is_disegnando = False
if "main_map" in st.session_state and st.session_state["main_map"] is not None:
    # Se ci sono disegni (all_drawings non vuoto), attiviamo il blocco
    if st.session_state["main_map"].get("all_drawings"):
        is_disegnando = True

if not is_disegnando:
    # Il refresh avviene solo se NON stiamo disegnando
    st_autorefresh(interval=30000, key="datarefresh_stabile")
else:
    st.sidebar.warning("⚠️ REFRESH SOSPESO: Disegno in corso...")

# Timestamp per monitoraggio
ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]

# Connessione a Supabase
conn = st.connection("postgresql", type="sql")

# --- 3. CARICAMENTO DATI ---
@st.cache_data(ttl=10)
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = json.loads(df_r.iloc[0]['coords']) if not df_r.empty else []
        return df_m, coords
    except Exception as e:
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 4. COSTRUZIONE MAPPA ---
df_valid = df_mandria.dropna(subset=['lat', 'lon'])
df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]
c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# SATELLITE GOOGLE FISSO
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

# --- 5. LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.sidebar.write(f"Ultimo Refresh: **{ora_log}**")

col_map, col_table = st.columns([3, 1])

with col_map:
    # Usiamo la key "main_map" per permettere al codice in alto di leggere i disegni
    out = st_folium(m, width="100%", height=650, key="main_map")
    
    if out and out.get('all_drawings'):
        raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
        new_poly = [[p[1], p[0]] for p in raw_coords]
        
        if st.button("💾 Conferma e Salva Nuovo Recinto"):
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(new_poly)})
                s.commit()
            st.success("Recinto salvato! Il refresh ripartirà tra poco.")
            time.sleep(1)
            st.rerun()

with col_table:
    st.subheader("⚠️ Emergenze")
    df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
    st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

st.write("---")
st.subheader("📝 Storico Aggiornamenti")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)

# 6. STABILIZZAZIONE FINALE
time.sleep(1)
