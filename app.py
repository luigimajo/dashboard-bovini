import streamlit as st
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

# Inizializzazione stati
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False

# --- 2. REFRESH NON DISTRUTTIVO (FRAGMENT) ---
@st.fragment(run_every=30)
def sync_data():
    if not st.session_state.edit_mode:
        st.rerun()

sync_data()

ora_log = datetime.now().strftime("%H:%M:%S")
conn = st.connection("postgresql", type="sql")

# --- 3. CARICAMENTO DATI ---
@st.cache_data(ttl=2)
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_g = conn.query("SELECT * FROM gateway ORDER BY ultima_attivita DESC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = json.loads(df_r.iloc[0]['coords']) if not df_r.empty else []
        return df_m, df_g, coords
    except:
        return pd.DataFrame(), pd.DataFrame(), []

df_mandria, df_gateways, saved_coords = load_data()

# --- 4. SIDEBAR RIPRISTINATA ---
with st.sidebar:
    st.header("📡 STATO RETE LORA")
    st.write(f"Ultimo Sync: **{ora_log}**")
    
    if st.session_state.edit_mode:
        st.warning("🏗️ MODALITÀ DISEGNO ATTIVA")
        if st.button("🔓 Esci e annulla"):
            st.session_state.edit_mode = False
            st.rerun()

    # Logica originale Sidebar
    with st.expander("➕ Gestione Mandria/Gateway"):
        # Qui rimangono i tuoi input originali
        pass

# --- 5. COSTRUZIONE MAPPA ---
c_lat, c_lon = 37.9747, 13.5753
if not df_mandria.empty and 'lat' in df_mandria.columns:
    df_v = df_mandria.dropna(subset=['lat', 'lon']).query("lat!=0")
    if not df_v.empty: c_lat, c_lon = df_v['lat'].mean(), df_v['lon'].mean()

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# --- SATELLITE GOOGLE (IL TUO BLOCCO FISSO) ---
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

# --- 6. LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    if not st.session_state.edit_mode:
        if st.button("🏗️ INIZIA DISEGNO NUOVO RECINTO"):
            st.session_state.edit_mode = True
            st.rerun()
    
    # Mappa con key fissa
    out = st_folium(m, width="100%", height=650, key="main_map")
    
    # TASTO SALVA: Sempre visibile in Edit Mode
    if st.session_state.edit_mode:
        st.info("📍 Disegna il recinto. Ricorda di chiudere il poligono cliccando sul primo punto.")
        if st.button("💾 SALVA NUOVO RECINTO"):
            if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
                raw = out['all_drawings'][-1]['geometry']['coordinates'][0]
                # Inversione Lon/Lat -> Lat/Lon
                new_poly = [[p[1], p[0]] for p in raw]
                
                with conn.session as s:
                    s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), 
                              {"coords": json.dumps(new_poly)})
                    s.commit()
                
                st.success("✅ Recinto salvato!")
                st.session_state.edit_mode = False
                st.rerun()
            else:
                st.error("⚠️ Nessun poligono completo rilevato. Chiudi il disegno prima di salvare.")

with col_table:
    st.subheader("⚠️ Emergenze")
    df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria.get('batteria', 100) <= 20)]
    st.dataframe(df_emergenza[['nome', 'stato_recinto']], hide_index=True)

st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
