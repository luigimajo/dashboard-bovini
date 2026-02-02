import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import sqlite3
import json
import pandas as pd
import requests

# --- DATABASE ---
conn = sqlite3.connect('bovini.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS mandria (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, stato_recinto TEXT)')
c.execute('CREATE TABLE IF NOT EXISTS recinto (id INTEGER PRIMARY KEY, coords TEXT)')
conn.commit()

# --- FUNZIONI ---
def is_inside(lat, lon, polygon_coords):
    if not polygon_coords or len(polygon_coords) < 3: return True
    poly = Polygon(polygon_coords)
    return poly.contains(Point(lat, lon))

def invia_telegram(msg):
    try:
        # Prendi i dati dai Secrets di Streamlit
        token = st.secrets["TELEGRAM_TOKEN"].strip()
        chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
        # URL corretto e verificato
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
        return resp.json() # Ci serve per vedere l'errore se fallisce
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- LOGICA DATI ---
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
saved_coords = json.loads(res[0]) if res and res[0] else []
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

st.title("🛰️ Monitoraggio Bovini - Satellitare")

col1, col2 = st.columns([3, 1])

with col2:
    st.subheader("🧪 Test Telegram")
    if st.button("Invia Messaggio di Prova"):
        risultato = invia_telegram("👋 Test connessione dalla Dashboard!")
        if risultato.get("ok"):
            st.success("✅ Messaggio inviato con successo!")
        else:
            st.error(f"❌ Errore: {risultato.get('description', 'Token o Chat ID errato')}")

    st.write("---")
    st.subheader("📍 Test Movimento")
    if not df_mandria.empty:
        bov_sel = st.selectbox("Sposta:", df_mandria['nome'].tolist())
        n_lat = st.number_input("Lat", value=45.1743, format="%.6f")
        n_lon = st.number_input("Lon", value=9.2394, format="%.6f")
        
        if st.button("Aggiorna Posizione"):
            c.execute("SELECT stato_recinto FROM mandria WHERE nome=?", (bov_sel,))
            stato_vecchio = c.fetchone()[0]
            
            nuovo_in = is_inside(n_lat, n_lon, saved_coords)
            stato_nuovo = "DENTRO" if nuovo_in else "FUORI"
            
            if stato_vecchio == "DENTRO" and stato_nuovo == "FUORI":
                invia_telegram(f"🚨 ALLARME: {bov_sel} è USCITO!")
            
            c.execute("UPDATE mandria SET lat=?, lon=?, stato_recinto=? WHERE nome=?", (n_lat, n_lon, stato_nuovo, bov_sel))
            conn.commit()
            st.rerun()

with col1:
    # MAPPA SATELLITARE GOOGLE (Più affidabile di Esri)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google Satellite',
        name='Google Satellite',
        overlay=False,
        control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", weight=5, fill=True, fill_opacity=0.2).add_to(m)

    for i, row in df_mandria.iterrows():
        col = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], popup=row['nome'], icon=folium.Icon(color=col)).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    
    out = st_folium(m, width=800, height=550, key="main_map")

    if out and out.get('all_drawings'):
        new_poly = out['all_drawings'][-1]['geometry']['coordinates'][0]
        # Invertiamo le coordinate per il formato Folium [lat, lon]
        fixed_poly = [[p[1], p[0]] for p in new_poly]
        c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(fixed_poly),))
        conn.commit()
        st.button("Salva Recinto e Ricarica")
