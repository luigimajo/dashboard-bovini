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
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()

# --- 2. LOGICA REFRESH (ANTI-TRIPLETTE + BLOCCO DISEGNO) ---
# Se siamo in modalità disegno, NON carichiamo il componente autorefresh
if not st.session_state.edit_mode:
    # Usiamo una key statica per evitare refresh multipli/fantasma
    st_autorefresh(interval=30000, key="timer_unico_30s")
else:
    st.sidebar.warning("🏗️ MODALITÀ DISEGNO ATTIVA: Refresh disabilitato")
    if st.sidebar.button("🔓 Annulla e riattiva refresh"):
        st.session_state.edit_mode = False
        st.rerun()

# Timestamp millesimale per monitoraggio
ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]

# Connessione Database
conn = st.connection("postgresql", type="sql")

# --- 3. CARICAMENTO DATI ---
@st.cache_data(ttl=2)
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = []
        if not df_r.empty:
            val = df_r.iloc[0]['coords']
            coords = json.loads(val) if isinstance(val, str) else val
        return df_m, coords
    except Exception as e:
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 4. COSTRUZIONE MAPPA ---
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

# Disegno recinto esistente
if saved_coords:
    folium.Polygon(locations=saved_coords, color="yellow", weight=3, fill=True, fill_opacity=0.2).add_to(m)

# Marker animali
for _, row in df_mandria.iterrows():
    if pd.notna(row['lat']) and row['lat'] != 0:
        color = 'green' if row['stato_recinto'] == 'DENTRO' else 'red'
        folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color=color, icon='info-sign')).add_to(m)

# Strumento disegno
Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)

# --- 5. LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.sidebar.metric("⏱️ Ultimo Refresh", ora_log)

col_map, col_table = st.columns([3, 1])

with col_map:
    # PULSANTE PER INIZIARE
    if not st.session_state.edit_mode:
        if st.button("🏗️ CLICCA QUI PER DISEGNARE NUOVO RECINTO"):
            st.session_state.edit_mode = True
            st.rerun()
    
    # Visualizzazione Mappa
    out = st_folium(m, width="100%", height=650, key="mappa_monitoraggio")
    
    # PULSANTE SALVA (Appare solo in modalità disegno)
    if st.session_state.edit_mode:
        st.info("📍 Disegna il poligono sulla mappa. Quando hai finito, clicca il tasto qui sotto.")
        
        if st.button("💾 SALVA NUOVO RECINTO E RIATTIVA REFRESH"):
            if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
                # Estrazione coordinate GeoJSON [Lon, Lat]
                raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
                # Conversione in [Lat, Lon]
                new_poly = [[p[1], p[0]] for p in raw_coords]
                
                with conn.session as s:
                    s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(new_poly)})
                    s.commit()
                
                st.success("✅ Recinto salvato con successo!")
                st.session_state.edit_mode = False
                time.sleep(2)
                st.rerun()
            else:
                st.error("⚠️ Nessun disegno rilevato. Chiudi il poligono sulla mappa prima di salvare.")

with col_table:
    st.subheader("⚠️ Emergenze")
    df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
    st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True, use_container_width=True)

st.divider()
st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)

# --- 6. RITARDO STABILIZZAZIONE ---
time.sleep(1)
