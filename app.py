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

# Inizializzazione stato per modalità disegno
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False

# --- 2. LOGICA REFRESH (PULIZIA TOTALE IN EDIT) ---
# Se siamo in edit_mode, NON eseguiamo st_autorefresh. Il timer nel browser sparisce.
if not st.session_state.edit_mode:
    st_autorefresh(interval=30000, key="timer_stabile_30s")
else:
    st.sidebar.warning("🏗️ MODALITÀ DISEGNO: Refresh Disabilitato")
    if st.sidebar.button("🔓 Esci e annulla"):
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
        coords = []
        if not df_r.empty:
            # Accesso sicuro per nome colonna
            val = df_r.iloc[0]['coords']
            coords = json.loads(val) if isinstance(val, str) else val
        return df_m, coords
    except Exception:
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 4. COSTRUZIONE MAPPA (CON PROTEZIONE KEYERROR) ---
c_lat, c_lon = 37.9747, 13.5753

# Verifichiamo che le colonne esistano prima di pulire i dati
if not df_mandria.empty and 'lat' in df_mandria.columns and 'lon' in df_mandria.columns:
    df_v = df_mandria.dropna(subset=['lat', 'lon'])
    df_v = df_v[(df_v['lat'] != 0) & (df_v['lon'] != 0)]
    if not df_v.empty:
        c_lat, c_lon = df_v['lat'].mean(), df_v['lon'].mean()

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

# Marker animali (solo se colonne presenti)
if not df_mandria.empty and 'lat' in df_mandria.columns:
    for _, row in df_mandria.iterrows():
        if pd.notna(row['lat']) and row['lat'] != 0:
            color = 'green' if row.get('stato_recinto') == 'DENTRO' else 'red'
            folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color=color, icon='info-sign')).add_to(m)

Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)

# --- 5. LAYOUT ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    if not st.session_state.edit_mode:
        if st.button("🏗️ INIZIA DISEGNO NUOVO RECINTO"):
            st.session_state.edit_mode = True
            st.rerun()
    
    # Render Mappa - USARE KEY STATICA PER NON RESETTARE AL CLIC DEI VERTICI
    out = st_folium(m, width="100%", height=650, key="main_map")
    
    # MOSTRA TASTO SALVA (Solo in edit_mode)
    if st.session_state.edit_mode:
        st.info("📍 Disegna il recinto sulla mappa. Quando hai CHIUSO il poligono, clicca il tasto sotto.")
        if st.button("💾 SALVA NUOVO RECINTO"):
            if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
                raw = out['all_drawings'][-1]['geometry']['coordinates'][0]
                # Inversione coordinate Lon/Lat -> Lat/Lon
                new_poly = [[p[1], p[0]] for p in raw]
                
                with conn.session as s:
                    s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), 
                              {"coords": json.dumps(new_poly)})
                    s.commit()
                
                st.success("✅ Recinto salvato! Il monitoraggio ripartirà.")
                st.session_state.edit_mode = False
                time.sleep(1)
                st.rerun()
            else:
                st.error("⚠️ Nessun poligono chiuso rilevato sulla mappa.")

with col_table:
    st.subheader("⚠️ Stato")
    if not df_mandria.empty:
        df_em = df_mandria[df_mandria.get('stato_recinto') == 'FUORI']
        st.dataframe(df_em[['nome', 'batteria']] if not df_em.empty else pd.DataFrame(), hide_index=True)

st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
