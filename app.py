import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh
import time

# --- 1. CONFIGURAZIONE PAGINA (Deve essere la prima istruzione) ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# Inizializzazione stato del blocco
if "lock_refresh" not in st.session_state:
    st.session_state.lock_refresh = False

# --- 2. LOGICA REFRESH STABILE ---
# Se non è bloccato, esegue il refresh ogni 30s con chiave temporale per evitare "timer fantasma"
if not st.session_state.lock_refresh:
    st_autorefresh(interval=30000, key=f"timer_{int(time.time() // 30)}")
else:
    st.sidebar.warning("⚠️ REFRESH SOSPESO")
    if st.sidebar.button("🔓 RIPRISTINA REFRESH"):
        st.session_state.lock_refresh = False
        st.rerun()

# Connessione Database
conn = st.connection("postgresql", type="sql")

# --- 3. CARICAMENTO DATI ---
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_g = conn.query("SELECT * FROM gateway ORDER BY ultima_attivita DESC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = []
        if not df_r.empty:
            val = df_r.iloc[0]['coords']
            coords = json.loads(val) if isinstance(val, str) else val
        return df_m, df_g, coords
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), []

df_mandria, df_gateways, saved_coords = load_data()

# --- 4. COSTRUZIONE MAPPA ---
df_valid = df_mandria.dropna(subset=['lat', 'lon'])
df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]
c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

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
        folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color=color, icon='info-sign')).add_to(m)

Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)

# --- 5. SIDEBAR (Statica per evitare sovrapposizioni) ---
with st.sidebar:
    st.header("📡 RETE LORA")
    # Qui inserisci la tua logica visualizzazione gateway...
    st.divider()
    with st.expander("➕ Gestione"):
        st.session_state.lock_refresh = True
        # Qui inserisci i tuoi input...

# --- 6. LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")

# Definiamo le colonne con proporzioni fisse per impedire alla mappa di espandersi sulla sidebar
col_map, col_table = st.columns([3, 1])

with col_map:
    # Pulsante di controllo disegno
    if not st.session_state.lock_refresh:
        if st.button("🏗️ INIZIA DISEGNO (Blocca Refresh)"):
            st.session_state.lock_refresh = True
            st.rerun()
    else:
        if st.button("🔓 ANNULLA E SBLOCCA"):
            st.session_state.lock_refresh = False
            st.rerun()

    # Visualizzazione Mappa con KEY statica per stabilità layout
    out = st_folium(m, width=1000, height=650, key="main_map_stable")
    
    if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
        raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
        new_poly = [[p[1], p[0]] for p in raw_coords] # Conversione Lon/Lat -> Lat/Lon
        
        if st.button("💾 SALVA NUOVO RECINTO"):
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(new_poly)})
                s.commit()
            st.session_state.lock_refresh = False
            st.success("Salvato! Riavvio refresh...")
            time.sleep(1)
            st.rerun()

with col_table:
    st.subheader("⚠️ Emergenze")
    st.dataframe(df_mandria[df_mandria['stato_recinto'] == 'FUORI'], hide_index=True)

st.divider()
st.subheader("📝 Storico Completo")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
