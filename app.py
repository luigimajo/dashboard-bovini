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

# --- LOGICA DI BLOCCO E RESET REFRESH ---
if "lock_refresh" not in st.session_state:
    st.session_state.lock_refresh = False

# CREIAMO UN TIMER UNIVOCO PER QUESTA SESSIONE (Evita i refresh a 13s o random)
if not st.session_state.lock_refresh:
    # Usiamo un placeholder per assicurarci che il timer sia la prima cosa inviata al browser
    refresh_area = st.empty()
    with refresh_area:
        # La key include il timestamp dell'ultimo refresh per resettare i timer fantasma
        st_autorefresh(interval=30000, key=f"timer_{int(time.time() // 30)}")
else:
    st.sidebar.warning("⚠️ REFRESH SOSPESO (Modifica in corso)")
    if st.sidebar.button("Sblocca Refresh"):
        st.session_state.lock_refresh = False
        st.rerun()

# --- CONNESSIONE E DATI ---
conn = st.connection("postgresql", type="sql")

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

# --- SIDEBAR CON BLOCCO AUTOMATICO ---
st.sidebar.header("📡 STATO RETE LORA")
# ... (Visualizzazione stato gateway come nel tuo originale)

with st.sidebar.expander("➕ Configura Nuovo Gateway"):
    st.session_state.lock_refresh = True # Blocca se apri l'expander
    g_id = st.text_input("ID Gateway")
    if st.button("Registra"):
        # ... (Logica insert)
        st.session_state.lock_refresh = False
        st.rerun()

with st.sidebar.expander("➕ Aggiungi Bovino"):
    st.session_state.lock_refresh = True
    n_id = st.text_input("ID Tracker")
    if st.button("Salva"):
        # ... (Logica insert)
        st.session_state.lock_refresh = False
        st.rerun()

# --- MAPPA E DISEGNO ---
# ... (Logica creazione oggetto 'm' come nel tuo originale)

col_map, col_table = st.columns([3, 1])

with col_map:
    # PULSANTE ESSENZIALE PER DISEGNARE SENZA REFRESH
    if not st.session_state.lock_refresh:
        if st.button("🏗️ CLICCA QUI PER DISEGNARE IL RECINTO"):
            st.session_state.lock_refresh = True
            st.rerun()
    
    out = st_folium(m, width="100%", height=650, key="main_map")
    
    if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
        raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
        new_poly = [[p[1], p[0]] for p in raw_coords]
        
        if st.button("💾 Conferma e Salva Nuovo Recinto"):
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(new_poly)})
                s.commit()
            st.session_state.lock_refresh = False
            st.success("Recinto aggiornato!")
            st.rerun()

# ... (Resto del codice tabella emergenze)
