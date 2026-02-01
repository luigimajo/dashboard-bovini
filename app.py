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

# Creazione tabelle e aggiornamento colonne
c.execute('CREATE TABLE IF NOT EXISTS mandria (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, batteria REAL, stato_recinto TEXT)')
c.execute('CREATE TABLE IF NOT EXISTS recinto (id INTEGER PRIMARY KEY, coords TEXT)')
try:
    c.execute('ALTER TABLE mandria ADD COLUMN stato_recinto TEXT')
except:
    pass 
conn.commit()

# --- FUNZIONI CORE ---
def invia_telegram(msg):
    try:
        token = st.secrets["TELEGRAM_TOKEN"].strip()
        chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
        url = f"https://api.telegram.org{token}/sendMessage"
        requests.get(url, params={"chat_id": chat_id, "text": msg}, timeout=10)
    except:
        pass

def save_polygon(coords):
    c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(coords),))
    conn.commit()

def load_polygon():
    c.execute("SELECT coords FROM recinto WHERE id = 1")
    row = c.fetchone()
    if row:
        try:
            return json.loads(row[0])
        except: return []
    return []

def is_inside(lat, lon, polygon_coords):
    if not polygon_coords or len(polygon_coords) < 3: return True
    try:
        poly = Polygon(polygon_coords)
        return poly.contains(Point(lat, lon))
    except: return True

# --- INTERFACCIA ---
st.set_page_config(page_title="Monitoraggio Bovini 2026", layout="wide")
st.title("🚜 Dashboard Pascoli - Satellite & Allarmi")

saved_coords = load_polygon()
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

col1, col2 = st.columns([3, 1])

with col1:
    map_center = [45.1743, 9.2394]
    if not df_mandria.empty:
        map_center = [df_mandria['lat'].mean(), df_mandria['lon'].mean()]
    
    m = folium.Map(location=map_center, zoom_start=15, tiles=None)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com{z}/{y}/{x}', 
        attr='Esri World Imagery', name='Satellite', overlay=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.15).add_to(m)

    for index, row in df_mandria.iterrows():
        b_lat, b_lon = row['lat'], row['lon']
        nuovo_stato = "DENTRO" if is_inside(b_lat, b_lon, saved_coords) else "FUORI"
        stato_prec = row['stato_recinto'] if row['stato_recinto'] else "DENTRO"
        
        if stato_prec == "DENTRO" and nuovo_stato == "FUORI":
            invia_telegram(f"🚨 ALLARME: {row['nome']} è USCITO dal recinto!")
        
        if stato_prec != nuovo_stato:
            c.execute("UPDATE mandria SET stato_recinto = ? WHERE id = ?", (nuovo_stato, row['id']))
            conn.commit()

        color = 'green' if nuovo_stato == "DENTRO" else 'red'
        folium.Marker(
            location=[b_lat, b_lon],
            popup=f"{row['nome']} ({row['batteria']}V)",
            icon=folium.Icon(color=color, icon='info-sign')
        ).add_to(m)

    draw = Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'circlemarker':False,'polygon':True})
    draw.add_to(m)
    output = st_folium(m, width=900, height=550, key="map_v3")

with col2:
    st.subheader("⚙️ Gestione")
    
    if output and output['all_drawings']:
        last_draw = output['all_drawings'][-1]
        if last_draw['geometry']['type'] == 'Polygon':
            raw_coords = last_draw['geometry']['coordinates'][0]
            # Inversione [lon, lat] -> [lat, lon] per Folium
            new_coords = [[p[1], p[0]] for p in raw_coords]
            if st.button("💾 Salva Recinto"):
                save_polygon(new_coords)
                st.success("Recinto Salvato!")
                st.rerun()

    if st.button("🗑️ Elimina Recinto"):
        c.execute("DELETE FROM recinto WHERE id = 1")
        conn.commit()
        st.success("Recinto eliminato")
        st.rerun()
    
    st.write("---")
    if not df_mandria.empty:
        st.dataframe(df_mandria[['nome', 'batteria', 'stato_recinto']], use_container_width=True)

with st.sidebar:
    st.header("➕ Nuovo Bovino")
    id_t = st.text_input("ID Tracker")
    nome_t = st.text_input("Nome")
    if st.button("Aggiungi"):
        c.execute("INSERT OR REPLACE INTO mandria VALUES (?, ?, ?, ?, ?, ?)", (id_t, nome_t, 45.1743, 9.2394, 4.2, "DENTRO"))
        conn.commit()
        st.rerun()
