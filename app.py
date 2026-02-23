import streamlit as st
from streamlit_autorefresh import st_autorefresh
import time

# --- 1. CONFIGURAZIONE PAGINA (Deve essere la prima istruzione) ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# Inizializzazione dello stato di blocco
if "lock_refresh" not in st.session_state:
    st.session_state.lock_refresh = False

# --- 2. GESTIONE REFRESH STABILE (CHIAVE STATICA) ---
# Usare una key fissa ("timer_unico") impedisce al browser di accumulare più timer.
# Se il refresh è bloccato, il componente non viene renderizzato affatto.
if not st.session_state.lock_refresh:
    st_autorefresh(interval=30000, key="timer_unico_stabile")
else:
    st.sidebar.warning("⚠️ REFRESH SOSPESO")
    if st.sidebar.button("🔓 RIPRISTINA REFRESH"):
        st.session_state.lock_refresh = False
        st.rerun()

# --- 3. IMPORT LIBRERIE E CONNESSIONE (Dopo il timer per velocità) ---
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text

conn = st.connection("postgresql", type="sql")

# --- 4. CARICAMENTO DATI CON CACHE (Evita i salti a 60s) ---
# Usiamo una cache brevissima (5 secondi) per rendere il ricaricamento istantaneo
@st.cache_data(ttl=5)
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

# --- 5. COSTRUZIONE MAPPA ---
df_valid = df_mandria.dropna(subset=['lat', 'lon'])
df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]
c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# Layer Satellite Google Originale
folium.TileLayer(
    tiles='https://mt1.google.com{x}&y={y}&z={z}',
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

# --- 6. LAYOUT E LOGICA DI DISEGNO ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    # Pulsante per attivare il blocco manuale PRIMA di iniziare a disegnare
    if not st.session_state.lock_refresh:
        if st.button("🏗️ INIZIA DISEGNO RECINTO (Blocca Refresh)"):
            st.session_state.lock_refresh = True
            st.rerun()
    else:
        if st.button("🚫 ANNULLA E SBLOCCA"):
            st.session_state.lock_refresh = False
            st.rerun()

    # Visualizzazione Mappa con key fissa per stabilità
    out = st_folium(m, width=1000, height=650, key="mappa_monitoraggio")
    
    # Salvataggio Recinto
    if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
        if st.button("💾 CONFERMA E SALVA NUOVO RECINTO"):
            # Conversione coordinate: st_folium restituisce [Lon, Lat], noi salviamo [Lat, Lon]
            raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
            new_poly = [[p[1], p[0]] for p in raw_coords]
            
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(new_poly)})
                s.commit()
            
            st.success("Recinto salvato con successo!")
            st.session_state.lock_refresh = False
            time.sleep(1)
            st.rerun()

with col_table:
    st.subheader("⚠️ Emergenze")
    df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
    st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

st.divider()
st.subheader("📝 Storico Aggiornamenti")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
