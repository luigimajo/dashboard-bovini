import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# Inizializzazione sicura dello stato
if "lock_refresh" not in st.session_state:
    st.session_state.lock_refresh = False

# --- 2. GESTIONE REFRESH (UNICO E STATICO) ---
# Usiamo una KEY FISSA ("constant_timer"). 
# Se la chiave è fissa, Streamlit NON PUÒ creare un secondo timer: sovrascrive sempre il precedente.
if not st.session_state.lock_refresh:
    st_autorefresh(interval=30000, key="constant_timer")
else:
    st.sidebar.warning("⚠️ REFRESH BLOCCATO")
    if st.sidebar.button("🔓 SBLOCCA ORA"):
        st.session_state.lock_refresh = False
        st.rerun()

# --- 3. CARICAMENTO DATI ---
conn = st.connection("postgresql", type="sql")

@st.cache_data(ttl=0) # Forza il ricaricamento dal DB senza cache
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

# --- 4. COSTRUZIONE MAPPA ---
# (Uso coordinate medie per centrare o default)
c_lat, c_lon = 37.9747, 13.5753
m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

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
        folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color=color)).add_to(m)

Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)

# --- 5. LAYOUT ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    # Interruttore per il disegno
    if not st.session_state.lock_refresh:
        if st.button("🏗️ INIZIA DISEGNO (Blocca Refresh)"):
            st.session_state.lock_refresh = True
            st.rerun()
    
    # Visualizzazione Mappa (KEY STATICA per evitare raddoppi)
    out = st_folium(m, width="100%", height=600, key="single_map_instance")
    
    if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
        if st.button("💾 SALVA NUOVO RECINTO"):
            raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
            new_poly = [[p[1], p[0]] for p in raw_coords]
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(new_poly)})
                s.commit()
            st.session_state.lock_refresh = False
            st.success("Salvato!")
            st.rerun()

with col_table:
    st.subheader("⚠️ Stato")
    st.dataframe(df_mandria[['nome', 'stato_recinto']], hide_index=True)
