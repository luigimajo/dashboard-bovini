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
    token = st.secrets["TELEGRAM_TOKEN"].strip()
    chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
    url = f"https://api.telegram.org{token}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

def is_inside(lat, lon, poly_coords):
    if not poly_coords or len(poly_coords) < 3: return True
    try:
        poly = Polygon(poly_coords)
        return poly.contains(Point(lat, lon))
    except: return True

st.set_page_config(page_title="Test Tracker", layout="wide")
st.title("🚜 Centro Test Pascoli")

# Caricamento Dati
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
saved_coords = json.loads(res[0]) if res and res[0] else []
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

col1, col2 = st.columns([3, 1])

with col2:
    st.subheader("🛠️ Test Movimento")
    if not df_mandria.empty:
        # Selettore per spostare il bovino e testare l'allarme
        bov_sel = st.selectbox("Muovi bovino:", df_mandria['nome'].tolist())
        nuova_lat = st.slider("Sposta Latitudine", 45.1700, 45.1800, 45.1743, format="%.4f")
        nuova_lon = st.slider("Sposta Longitudine", 9.2300, 9.2450, 9.2394, format="%.4f")
        
        if st.button("Applica Spostamento"):
            c.execute("UPDATE mandria SET lat=?, lon=? WHERE nome=?", (nuova_lat, nuova_lon, bov_sel))
            conn.commit()
            st.rerun()
    
    st.write("---")
    if st.button("🗑️ Elimina Recinto"):
        c.execute("DELETE FROM recinto WHERE id = 1"); conn.commit(); st.rerun()

with col1:
    # MAPPA CON LAYER SATELLITARE ESRI (Il più compatibile con Streamlit Cloud)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=15)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com{z}/{y}/{x}',
        attr='Esri',
        name='Satellite',
        overlay=False,
        control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.2).add_to(m)

    for i, row in df_mandria.iterrows():
        check_in = is_inside(row['lat'], row['lon'], saved_coords)
        nuovo_stato = "DENTRO" if check_in else "FUORI"
        
        # LOGICA ALLARME
        if row['stato_recinto'] == "DENTRO" and nuovo_stato == "FUORI":
            invia_telegram(f"🚨 ALLARME: {row['nome']} è USCITO dal recinto!")
        
        c.execute("UPDATE mandria SET stato_recinto = ? WHERE id = ?", (nuovo_stato, row['id']))
        conn.commit()
        
        folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color='green' if check_in else 'red')).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'circlemarker':False,'polygon':True}).add_to(m)
    output = st_folium(m, width=900, height=550, key="map_test")

    if output and output.get('all_drawings'):
        last = output['all_drawings'][-1]
        if last['geometry']['type'] == 'Polygon':
            raw = last['geometry']['coordinates'][0]
            new_poly = [[p[1], p[0]] for p in raw]
            if st.button("💾 Salva questo recinto"):
                c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(new_poly),))
                conn.commit()
                st.rerun()

st.subheader("📋 Stato Mandria")
st.dataframe(df_mandria[['nome', 'batteria', 'stato_recinto', 'lat', 'lon']], use_container_width=True)

with st.sidebar:
    st.header("➕ Nuovo Bovino")
    id_n = st.text_input("ID")
    nome_n = st.text_input("Nome")
    if st.button("Aggiungi"):
        c.execute("INSERT OR REPLACE INTO mandria VALUES (?, ?, ?, ?, ?, ?)", (id_n, nome_n, 45.1743, 9.2394, 4.2, "DENTRO"))
        conn.commit(); st.rerun()
