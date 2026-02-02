import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import sqlite3
import json
import pandas as pd
import requests

# Configurazione Pagina
st.set_page_config(layout="wide", page_title="Monitoraggio Bovini Satellite")

# --- DATABASE (CON RESET AUTOMATICO PER ERRORI COLONNE) ---
conn = sqlite3.connect('bovini.db', check_same_thread=False)
c = conn.cursor()
try:
    c.execute('CREATE TABLE IF NOT EXISTS mandria (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, stato_recinto TEXT)')
except:
    # Se la tabella vecchia rompe il codice, la cancelliamo e rifacciamo
    c.execute('DROP TABLE mandria')
    c.execute('CREATE TABLE mandria (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, stato_recinto TEXT)')

c.execute('CREATE TABLE IF NOT EXISTS recinto (id INTEGER PRIMARY KEY, coords TEXT)')
conn.commit()

# --- FUNZIONE GEOFENCING ---
def is_inside(lat, lon, polygon_coords):
    if not polygon_coords or len(polygon_coords) < 3: 
        return True
    # Shapely vuole (lon, lat)
    poly = Polygon([(p[1], p[0]) for p in polygon_coords])
    point = Point(lon, lat)
    return poly.contains(point)

# --- FUNZIONE TELEGRAM ---
def invia_telegram(msg):
    try:
        token = st.secrets["TELEGRAM_TOKEN"].strip()
        chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
        url = f"https://api.telegram.org{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
    except Exception as e:
        st.error(f"Errore Telegram: {e}")

# --- CARICAMENTO DATI ---
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
saved_coords = json.loads(res[0]) if res and res[0] else []
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

st.title("🛰️ Dashboard Monitoraggio Satellite")

col1, col2 = st.columns([3, 1])

with col2:
    st.subheader("🛠️ Gestione")
    
    # Form aggiunta bovino
    with st.expander("➕ Aggiungi Nuovo Bovino"):
        id_n = st.text_input("ID Tracker")
        nome_n = st.text_input("Nome Bovino")
        if st.button("Salva Bovino"):
            # Usiamo esattamente 5 valori come nella tabella
            c.execute("INSERT OR REPLACE INTO mandria (id, nome, lat, lon, stato_recinto) VALUES (?, ?, ?, ?, ?)", 
                      (id_n, nome_n, 45.1743, 9.2394, "DENTRO"))
            conn.commit()
            st.rerun()

    if not df_mandria.empty:
        st.write("---")
        st.subheader("🧪 Test Allarme")
        bov_sel = st.selectbox("Sposta Bovino:", df_mandria['nome'].tolist())
        nuova_lat = st.number_input("Lat", value=45.1743, format="%.6f")
        nuova_lon = st.number_input("Lon", value=9.2394, format="%.6f")
        
        if st.button("Applica Movimento"):
            c.execute("SELECT stato_recinto FROM mandria WHERE nome=?", (bov_sel,))
            stato_vecchio = c.fetchone()[0]
            
            check_in = is_inside(nuova_lat, nuova_lon, saved_coords)
            nuovo_stato = "DENTRO" if check_in else "FUORI"
            
            if stato_vecchio == "DENTRO" and nuovo_stato == "FUORI":
                invia_telegram(f"🚨 ALLARME: {bov_sel} è USCITO dal recinto!")
            
            c.execute("UPDATE mandria SET lat=?, lon=?, stato_recinto=? WHERE nome=?", 
                      (nuova_lat, nuova_lon, nuovo_stato, bov_sel))
            conn.commit()
            st.rerun()

with col1:
    # MAPPA SATELLITARE ESRI (Link Diretto Funzionante)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16, tiles=None)
    
    folium.TileLayer(
        tiles='https://server.arcgisonline.com{z}/{y}/{x}',
        attr='Esri World Imagery',
        name='Satellite',
        overlay=False,
        control=True
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.3).add_to(m)

    for i, row in df_mandria.iterrows():
        icon_color = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], popup=row['nome'], icon=folium.Icon(color=icon_color)).add_to(m)

    Draw(draw_options={'polyline': False, 'circle': False, 'marker': False, 'polygon': True}).add_to(m)
    
    output = st_folium(m, width=900, height=600, key="main_map")

    if output and output.get('all_drawings'):
        last = output['all_drawings'][-1]
        if last['geometry']['type'] == 'Polygon':
            # Coordinate dal disegno: [[lon, lat], [lon, lat]...]
            raw_coords = last['geometry']['coordinates'][0]
            # Salviamo come [lat, lon] per Folium
            final_coords = [[p[1], p[0]] for p in raw_coords]
            c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(final_coords),))
            conn.commit()
            st.info("Recinto creato. Clicca 'Aggiorna' per vedere le modifiche.")
            if st.button("Aggiorna"):
                st.rerun()
