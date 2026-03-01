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

# Inizializzazione stati di sessione
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False

# --- 2. LOGICA REFRESH (PULIZIA TOTALE IN EDIT) ---
# Usiamo un segnaposto: se siamo in edit_mode, st_autorefresh sparisce dal codice
refresh_placeholder = st.empty()
with refresh_placeholder:
    if not st.session_state.edit_mode:
        # Key statica per non creare duplicati
        st_autorefresh(interval=30000, key="timer_stabile_30s")
    else:
        st.sidebar.warning("🏗️ REFRESH DISABILITATO (Modalità Disegno)")
        if st.sidebar.button("🔓 Sblocca e Annulla"):
            st.session_state.edit_mode = False
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

if saved_coords:
    folium.Polygon(locations=saved_coords, color="yellow", weight=3, fill=True, fill_opacity=0.2).add_to(m)

# Marker animali
for _, row in df_mandria.iterrows():
    if pd.notna(row['lat']) and row['lat'] != 0:
        color = 'green' if row['stato_recinto'] == 'DENTRO' else 'red'
        folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color=color, icon='info-sign')).add_to(m)

Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)

# --- 5. LAYOUT ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns()

with col_map:
    # Tasto per entrare in modalità disegno
    if not st.session_state.edit_mode:
        if st.button("🏗️ INIZIA DISEGNO NUOVO RECINTO"):
            st.session_state.edit_mode = True
            st.rerun()
    
    # Render Mappa - KEY FISSA PER NON RESETTARE AL CLIC DEI VERTICI
    out = st_folium(m, width="100%", height=650, key="mappa_fissa")
    
    # Logica di salvataggio (Sempre visibile in Edit Mode)
    if st.session_state.edit_mode:
        st.info("📍 Disegna il poligono. Quando hai chiuso la forma, clicca il tasto sotto.")
        if st.button("💾 SALVA NUOVO RECINTO"):
            if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
                raw = out['all_drawings'][-1]['geometry']['coordinates']
                # Inversione coordinate Lon/Lat -> Lat/Lon
                new_poly = [[p, p] for p in raw]
                
                with conn.session as s:
                    s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), 
                              {"coords": json.dumps(new_poly)})
                    s.commit()
                
                st.success("✅ Salvato! Riattivazione monitoraggio...")
                st.session_state.edit_mode = False
                time.sleep(1)
                st.rerun()
            else:
                st.error("⚠️ Nessun poligono chiuso rilevato. Finisci il disegno prima di salvare.")

with col_table:
    st.subheader("⚠️ Stato")
    df_em = df_mandria[df_mandria['stato_recinto'] == 'FUORI'] if not df_mandria.empty else pd.DataFrame()
    st.dataframe(df_em[['nome', 'batteria']], hide_index=True)

st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
