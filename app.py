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
c.execute('CREATE TABLE IF NOT EXISTS mandria (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, batteria REAL, stato_recinto TEXT)')
c.execute('CREATE TABLE IF NOT EXISTS recinto (id INTEGER PRIMARY KEY, coords TEXT)')
conn.commit()

# --- FUNZIONE TELEGRAM ---
def invia_telegram(msg):
    try:
        token = st.secrets["TELEGRAM_TOKEN"].strip()
        chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
        url = f"https://api.telegram.org{token}/sendMessage"
        r = requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        st.error(f"Errore invio: {e}")
        return False

def is_inside(lat, lon, poly_coords):
    if not poly_coords or len(poly_coords) < 3: return True
    try:
        poly = Polygon(poly_coords)
        return poly.contains(Point(lat, lon))
    except: return True

st.set_page_config(page_title="Monitoraggio Bovini", layout="wide")
st.title("🚜 Dashboard Pascoli - Diagnostica")

# Caricamento Dati
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
saved_coords = json.loads(res[0]) if res and res[0] else []
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

col1, col2 = st.columns([3, 1])

with col2:
    st.subheader("🚨 Test Allarmi")
    if st.button("🔔 Invia Messaggio Test"):
        if invia_telegram("🔔 Test Manuale: Il sistema Telegram è collegato correttamente!"):
            st.success("Messaggio inviato!")
        else:
            st.error("Invio fallito. Controlla i Secrets.")
            
    st.write("---")
    st.subheader("🛠️ Muovi Bovino")
    if not df_mandria.empty:
        b_sel = st.selectbox("Seleziona:", df_mandria['nome'].tolist())
        n_lat = st.slider("Latitudine", 45.1700, 45.1800, 45.1743, format="%.4f")
        n_lon = st.slider("Longitudine", 9.2300, 9.2450, 9.2394, format="%.4f")
        if st.button("Aggiorna Posizione"):
            c.execute("UPDATE mandria SET lat=?, lon=? WHERE nome=?", (n_lat, n_lon, b_sel))
            conn.commit()
            st.rerun()

with col1:
    # SATELLITE FORZATO (Layer Esri con controllo manuale)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=15, tiles=None)
    
    # Questo layer DEVE apparire come satellite
    folium.TileLayer(
        tiles='https://server.arcgisonline.com{z}/{y}/{x}',
        attr='Esri World Imagery',
        name='Satellite ESRI',
        overlay=False,
        control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.2).add_to(m)

    for i, row in df_mandria.iterrows():
        check_in = is_inside(row['lat'], row['lon'], saved_coords)
        nuovo_stato = "DENTRO" if check_in else "FUORI"
        
        # LOGICA AUTOMATICA (Confronto stato database)
        if row['stato_recinto'] == "DENTRO" and nuovo_stato == "FUORI":
            invia_telegram(f"🚨 ALLARME AUTOMATICO: {row['nome']} è uscito dal recinto!")
        
        c.execute("UPDATE mandria SET stato_recinto = ? WHERE id = ?", (nuovo_stato, row['id']))
        conn.commit()
        
        folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color='green' if check_in else 'red')).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'circlemarker':False,'polygon':True}).add_to(m)
    output = st_folium(m, width=900, height=550, key="map_diag")

    if output and output.get('all_drawings'):
        last = output['all_drawings'][-1]
        if last['geometry']['type'] == 'Polygon':
            raw = last['geometry']['coordinates'][0]
            new_poly = [[p[1], p[0]] for p in raw] # Correzione inversione coordinate
            if st.button("💾 Salva Recinto"):
                c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(new_poly),))
                conn.commit()
                st.rerun()

st.subheader("📋 Tabella Stato")
st.dataframe(df_mandria[['nome', 'batteria', 'stato_recinto', 'lat', 'lon']], use_container_width=True)
