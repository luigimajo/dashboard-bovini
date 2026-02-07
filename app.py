import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import json
import pandas as pd
import requests

# --- CONNESSIONE DATABASE (Con protezione per non bloccare il satellite) ---
conn = st.connection("postgresql", type="sql")

# --- FUNZIONI ---
def is_inside(lat, lon, polygon_coords):
    if not polygon_coords or len(polygon_coords) < 3: return True
    poly = Polygon(polygon_coords)
    return poly.contains(Point(lat, lon))

def invia_telegram(msg):
    try:
        token = st.secrets["TELEGRAM_TOKEN"].strip()
        chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
        url = f"https://api.telegram.org{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- CARICAMENTO DATI (Isolato) ---
saved_coords = []
df_mandria = pd.DataFrame(columns=['id', 'nome', 'lat', 'lon', 'stato_recinto', 'batteria'])

try:
    # Carichiamo il recinto
    res_rec = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
    if not res_rec.empty:
        saved_coords = json.loads(res_rec.iloc[0]['coords'])
    # Carichiamo i bovini
    df_mandria = conn.query("SELECT * FROM mandria", ttl=0)
except Exception:
    st.sidebar.warning("⚠️ Database in fase di collegamento (IPv4 Pooler)...")

st.set_page_config(layout="wide")
st.title("🛰️ Monitoraggio Bovini - Satellitare")

# --- LAYOUT (Colonna 1: Mappa | Colonna 2: Test) ---
col1, col2 = st.columns([3, 1])

with col2:
    st.subheader("🧪 Test Telegram")
    if st.button("Invia Prova"):
        ris = invia_telegram("👋 Test connessione OK!")
        if ris.get("ok"): st.success("✅ Messaggio Inviato!")
        else: st.error(f"❌ Errore API: {ris}")

with col1:
    # MAPPA SATELLITARE (Blocco originale stabile)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    folium.TileLayer(
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
        attr='Google Satellite', name='Google Satellite', overlay=False, control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", weight=5, fill=True, fill_opacity=0.2).add_to(m)

    for i, row in df_mandria.iterrows():
        col_m = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], popup=row['nome'], icon=folium.Icon(color=col_m)).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    st_folium(m, width=800, height=550, key="main_map")

st.write("---")
st.subheader("📊 Lista Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
