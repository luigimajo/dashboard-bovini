import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
import requests

# 1. Configurazione Pagina
st.set_page_config(layout="wide")
st.title("🛰️ Monitoraggio Bovini - Satellitare")

# 2. Funzioni
def invia_telegram(msg):
    try:
        token = str(st.secrets["TELEGRAM_TOKEN"]).strip()
        chat_id = str(st.secrets["TELEGRAM_CHAT_ID"]).strip()
        url = f"https://api.telegram.org{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# 3. Inizializzazione variabili (Senza database all'avvio)
saved_coords = []
df_mandria = pd.DataFrame(columns=['id', 'nome', 'lat', 'lon', 'stato_recinto', 'batteria'])

# Proviamo la connessione in modo "silenzioso"
if "db_connected" not in st.session_state:
    st.session_state.db_connected = False

try:
    conn = st.connection("postgresql", type="sql")
    # Solo una query veloce per testare
    res_rec = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=3600)
    if not res_rec.empty:
        saved_coords = json.loads(res_rec.iloc[0]['coords'])
    st.session_state.db_connected = True
except Exception:
    st.sidebar.warning("⚠️ Database in attesa di segnale...")

# 4. Layout
col1, col2 = st.columns([3, 1])

with col1:
    # FORZIAMO LA MAPPA
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    folium.TileLayer(
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
        attr='Google Satellite', name='Google Satellite', overlay=False, control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", weight=5, fill=True, fill_opacity=0.2).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    
    # Render della mappa (con chiave statica per evitare il refresh ciclico)
    st_folium(m, width=800, height=550, key="map_stable")

with col2:
    st.subheader("🧪 Test Telegram")
    if st.button("Invia Messaggio"):
        ris = invia_telegram("👋 Test dal sistema stabile!")
        if ris.get("ok"): st.success("✅ Inviato!")
        else: st.error(f"❌ Errore: {ris}")
    
    if st.sidebar.button("🔄 Forza Ricarica Dati"):
        st.cache_data.clear()
        st.rerun()
