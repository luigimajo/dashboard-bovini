import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh
import time

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# --- 1. LOGICA DI REFRESH (PULIZIA AUTOMATICA) ---
if "lock_refresh" not in st.session_state:
    st.session_state.lock_refresh = False

# Se il refresh NON è bloccato, attiviamo il timer stabile
if not st.session_state.lock_refresh:
    # La chiave cambia ogni 30 secondi per resettare i timer fantasma del browser
    st_autorefresh(interval=30000, key=f"timer_{int(time.time() // 30)}")
else:
    # Mostriamo un pulsante chiaro per sbloccare se rimanesse "incastrato"
    if st.sidebar.button("🔄 RIPRISTINA REFRESH AUTOMATICO"):
        st.session_state.lock_refresh = False
        st.rerun()
    st.sidebar.warning("⚠️ REFRESH SOSPESO (Modifica in corso)")

# Connessione Database
conn = st.connection("postgresql", type="sql")

# --- 2. CARICAMENTO DATI ---
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_g = conn.query("SELECT * FROM gateway ORDER BY ultima_attivita DESC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        
        # Estrazione sicura coordinate
        coords = []
        if not df_r.empty:
            val = df_r.iloc[0]['coords']
            coords = json.loads(val) if isinstance(val, str) else val
        return df_m, df_g, coords
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), []

df_mandria, df_gateways, saved_coords = load_data()

# --- 3. COSTRUZIONE MAPPA (Con il tuo Layer Satellite Originale) ---
df_valid = df_mandria.dropna(subset=['lat', 'lon'])
df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]
c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# TUO LAYER ORIGINALE RIPRISTINATO
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

# --- 4. LAYOUT E GESTIONE BLOCCO ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    # GESTIONE PULSANTI DISEGNO
    if not st.session_state.lock_refresh:
        if st.button("🏗️ INIZIA DISEGNO NUOVO RECINTO (Blocca Refresh)"):
            st.session_state.lock_refresh = True
            st.rerun()
    else:
        if st.button("🔓 ANNULLA MODIFICHE E SBLOCCA REFRESH"):
            st.session_state.lock_refresh = False
            st.rerun()

    # Visualizzazione Mappa
    out = st_folium(m, width="100%", height=650, key="main_map")
    
    # Salvataggio Recinto
    if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
        raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
        new_poly = [[p[1], p[0]] for p in raw_coords] # Corretto: Lon/Lat -> Lat/Lon
        
        if st.button("💾 CONFERMA E SALVA NUOVO RECINTO"):
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(new_poly)})
                s.commit()
            st.success("Recinto salvato!")
            st.session_state.lock_refresh = False # Sblocca subito dopo il salvataggio
            time.sleep(1) # Piccolo delay per mostrare il messaggio di successo
            st.rerun()

with col_table:
    st.subheader("⚠️ Emergenze")
    df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
    st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

st.subheader("📝 Storico Aggiornamenti")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
