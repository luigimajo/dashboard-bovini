import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import json
import pandas as pd
import requests

# Configurazione Pagina Immediata
st.set_page_config(layout="wide")
st.title("🛰️ Monitoraggio Bovini - Satellitare")

# --- FUNZIONI ---
def invia_telegram(msg):
    try:
        # Forziamo la pulizia dei segreti
        token = str(st.secrets["TELEGRAM_TOKEN"]).strip()
        chat_id = str(st.secrets["TELEGRAM_CHAT_ID"]).strip()
        # URL costruito pezzo per pezzo per evitare l'errore di parsing
        url = "https://api.telegram.org" + token + "/sendMessage"
        resp = requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- LAYOUT ---
col1, col2 = st.columns([3, 1])

with col1:
    # MAPPA POSIZIONATA IN ALTO PER FORZARE LA VISUALIZZAZIONE
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    folium.TileLayer(
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
        attr='Google Satellite', name='Google Satellite', overlay=False, control=False
    ).add_to(m)
    
    # Placeholder per il recinto (se il DB fallisce, resta vuoto)
    saved_coords = []
    
    # TENTATIVO DI CONNESSIONE DB (Isolato)
    df_mandria = pd.DataFrame()
    try:
        conn = st.connection("postgresql", type="sql")
        res_rec = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        if not res_rec.empty:
            saved_coords = json.loads(res_rec.iloc[0,0])
            folium.Polygon(locations=saved_coords, color="yellow", weight=5, fill=True, fill_opacity=0.2).add_to(m)
        df_mandria = conn.query("SELECT * FROM mandria", ttl=0)
    except Exception as e:
        st.error(f"Connessione Database non riuscita: {e}")

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    st_folium(m, width=800, height=550, key="main_map")

with col2:
    st.subheader("🧪 Test Telegram")
    if st.button("Invia Prova"):
        ris = invia_telegram("👋 Test dalla Dashboard")
        if ris.get("ok"): st.success("Inviato!")
        else: st.error(f"Errore: {ris}")
