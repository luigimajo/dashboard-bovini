import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import json
import pandas as pd
import requests

# --- CONNESSIONE DATABASE (Con protezione totale) ---
try:
    conn = st.connection("postgresql", type="sql")
except Exception:
    conn = None

# --- FUNZIONI ---
def is_inside(lat, lon, polygon_coords):
    if not polygon_coords or len(polygon_coords) < 3: return True
    poly = Polygon(polygon_coords)
    return poly.contains(Point(lat, lon))

def invia_telegram(msg):
    try:
        # Recupero forzato dei segreti per evitare errori di parsing
        t_token = str(st.secrets.get("TELEGRAM_TOKEN", "")).strip()
        t_chat = str(st.secrets.get("TELEGRAM_CHAT_ID", "")).strip()
        
        # Costruzione URL manuale ultra-stabile
        url = "https://api.telegram.org" + t_token + "/sendMessage"
        payload = {"chat_id": t_chat, "text": msg}
        
        resp = requests.post(url, data=payload, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- LOGICA DATI (Isolata per non bloccare la mappa) ---
saved_coords = []
df_mandria = pd.DataFrame(columns=['id', 'nome', 'lat', 'lon', 'stato_recinto', 'batteria'])

if conn is not None:
    try:
        res_rec = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        if not res_rec.empty:
            saved_coords = json.loads(res_rec.iloc[0]['coords'])
        
        res_man = conn.query("SELECT * FROM mandria", ttl=0)
        if not res_man.empty:
            df_mandria = res_man
    except Exception:
        pass # Silenzioso per non rompere la UI

st.set_page_config(layout="wide")
st.title("🛰️ Monitoraggio Bovini - Satellitare")

# --- SIDEBAR ---
st.sidebar.header("📋 Gestione Mandria")
if conn is None:
    st.sidebar.warning("⚠️ Database non connesso. Verifica i Secrets.")

# --- LAYOUT PRINCIPALE (Basato sulla tua versione stabile) ---
col1, col2 = st.columns([3, 1])

with col2:
    st.subheader("⚙️ Controllo")
    allarmi_attivi = st.toggle("Verifica Posizioni Attiva", value=True)
    
    st.write("---")
    st.subheader("🧪 Test Telegram")
    if st.button("Invia Messaggio di Prova"):
        risultato = invia_telegram("👋 Test connessione dalla Dashboard!")
        if risultato.get("ok"): st.success("✅ Inviato!")
        else: st.error(f"❌ Errore: {risultato}")

with col1:
    # LA MAPPA SATELLITARE (Forzata all'esterno di ogni blocco logico)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    
    # Layer Satellitare originale
    folium.TileLayer(
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
        attr='Google Satellite', 
        name='Google Satellite', 
        overlay=False, 
        control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", weight=5, fill=True, fill_opacity=0.2).add_to(m)

    for i, row in df_mandria.iterrows():
        col_m = 'green' if row.get('stato_recinto') == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], popup=row['nome'], icon=folium.Icon(color=col_m)).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    
    # Visualizzazione Mappa
    st_folium(m, width=800, height=550, key="main_map")

st.write("---")
st.subheader("📊 Lista Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
