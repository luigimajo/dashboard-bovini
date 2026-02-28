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

# Inizializzazione stato blocco refresh
if "lock_manuale" not in st.session_state:
    st.session_state.lock_manuale = False

# --- 2. LOGICA REFRESH STABILIZZATA ---
# Il refresh avviene SOLO se il blocco manuale è False
if not st.session_state.lock_manuale:
    st_autorefresh(interval=30000, key="datarefresh_stabile")
else:
    st.sidebar.warning("⚠️ REFRESH BLOCCATO: Modifica recinto in corso")
    if st.sidebar.button("🔓 SBLOCCA E ANNULLA"):
        st.session_state.lock_manuale = False
        st.rerun()

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

# --- 5. LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.sidebar.write(f"Ultimo Refresh: **{ora_log}**")

col_map, col_table = st.columns([3, 1])

with col_map:
    # PULSANTE DI SICUREZZA: Clicca questo prima di iniziare a disegnare
    if not st.session_state.lock_manuale:
        if st.button("🏗️ CLICCA QUI PER INIZIARE A DISEGNARE (Blocca Refresh)"):
            st.session_state.lock_manuale = True
            st.rerun()
    
    # Visualizzazione Mappa
    out = st_folium(m, width="100%", height=650, key="main_map")
    
    # Salvataggio Recinto
    if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
        # Prendi l'ultimo disegno
        raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
        new_poly = [[p[1], p[0]] for p in raw_coords] # Inversione Lon/Lat -> Lat/Lon
        
        if st.button("💾 CONFERMA E SALVA NUOVO RECINTO"):
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(new_poly)})
                s.commit()
            st.success("Recinto salvato! Refresh riattivato.")
            st.session_state.lock_manuale = False
            time.sleep(1)
            st.rerun()

with col_table:
    st.subheader("⚠️ Emergenze")
    df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
    st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

st.write("---")
st.subheader("📝 Storico Aggiornamenti")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)

# 6. STABILIZZAZIONE FINALE FINALE
time.sleep(1)
