import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# Inizializzazione stato (Session State)
if "lock_refresh" not in st.session_state:
    st.session_state.lock_refresh = False

# Connessione Database
conn = st.connection("postgresql", type="sql")

# --- FUNZIONI CARICAMENTO DATI ---
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_g = conn.query("SELECT * FROM gateway ORDER BY ultima_attivita DESC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = json.loads(df_r.iloc[0]['coords']) if not df_r.empty else []
        return df_m, df_g, coords
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), []

df_mandria, df_gateways, saved_coords = load_data()

# --- COSTRUZIONE OGGETTO MAPPA (Sempre eseguita per evitare mappa bianca) ---
df_valid = df_mandria.dropna(subset=['lat', 'lon'])
df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]
c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)
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

# --- SIDEBAR E REFRESH ---
if not st.session_state.lock_refresh:
    st_autorefresh(interval=30000, key="datarefresh")
else:
    st.sidebar.warning("🔄 REFRESH BLOCCATO")

# --- GESTIONE SIDEBAR (EXPANDERS) ---
with st.sidebar.expander("➕ Configura Nuovo Gateway"):
    st.session_state.lock_refresh = True
    g_id = st.text_input("ID Gateway")
    g_nome = st.text_input("Nome Località")
    if st.button("Registra Gateway"):
        # Logica insert...
        st.session_state.lock_refresh = False
        st.rerun()

with st.sidebar.expander("➕ Aggiungi Bovino"):
    st.session_state.lock_refresh = True
    n_id = st.text_input("ID Tracker")
    n_nome = st.text_input("Nome Animale")
    if st.button("Salva Bovino"):
        # Logica insert...
        st.session_state.lock_refresh = False
        st.rerun()

if not df_mandria.empty:
    with st.sidebar.expander("🗑️ Rimuovi Bovino"):
        st.session_state.lock_refresh = True
        bov_del = st.selectbox("Elimina:", df_mandria['nome'].tolist())
        if st.button("Conferma Elimina"):
            # Logica delete...
            st.session_state.lock_refresh = False
            st.rerun()

# --- LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    # Gestione manuale del blocco per il disegno
    if not st.session_state.lock_refresh:
        if st.button("🏗️ INIZIA A DISEGNARE IL RECINTO"):
            st.session_state.lock_refresh = True
            st.rerun()
    else:
        if st.button("🔓 SBLOCCA REFRESH / ANNULLA"):
            st.session_state.lock_refresh = False
            st.rerun()

    # Visualizzazione Mappa
    out = st_folium(m, width="100%", height=650, key="main_map")
    
    # Salvataggio Recinto
    if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
        raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
        new_poly = [[p[1], p[0]] for p in raw_coords]
        
        if st.button("💾 SALVA NUOVO RECINTO"):
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(new_poly)})
                s.commit()
            st.session_state.lock_refresh = False
            st.success("Recinto salvato!")
            st.rerun()

# Pannello emergenze (Codice originale...)
with col_table:
    st.subheader("⚠️ Pannello Emergenze")
    # ... resto del tuo codice tabella ...
