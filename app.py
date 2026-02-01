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
try:
    c.execute('ALTER TABLE mandria ADD COLUMN stato_recinto TEXT')
except: pass 
conn.commit()

# --- FUNZIONI ---
def invia_telegram(msg):
    try:
        token = st.secrets["TELEGRAM_TOKEN"].strip()
        chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
        requests.get(f"https://api.telegram.org{token}/sendMessage", params={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

def is_inside(lat, lon, polygon_coords):
    if not polygon_coords or len(polygon_coords) < 3: return True
    try: return Polygon(polygon_coords).contains(Point(lat, lon))
    except: return True

# --- INTERFACCIA ---
st.set_page_config(page_title="Monitoraggio Bovini", layout="wide")
st.title("🚜 Gestione Pascoli e Mandria")

# Carica dati
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
saved_coords = json.loads(res[0]) if res else []
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

col1, col2 = st.columns([3, 1])

with col1:
    # Selezione Mappa
    map_type = st.radio("Tipo Mappa", ["Satellite", "Stradale"], horizontal=True)
    tiles = 'https://server.arcgisonline.com{z}/{y}/{x}' if map_type == "Satellite" else 'OpenStreetMap'
    attr = 'Esri' if map_type == "Satellite" else 'OpenStreetMap'

    m = folium.Map(location=[45.1743, 9.2394], zoom_start=15, tiles=tiles, attr=attr)
    
    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.1).add_to(m)

    for _, row in df_mandria.iterrows():
        stato = "DENTRO" if is_inside(row['lat'], row['lon'], saved_coords) else "FUORI"
        if row['stato_recinto'] == "DENTRO" and stato == "FUORI":
            invia_telegram(f"🚨 {row['nome']} è USCITO dal recinto!")
        c.execute("UPDATE mandria SET stato_recinto = ? WHERE id = ?", (stato, row['id']))
        conn.commit()
        
        folium.Marker([row['lat'], row['lon']], popup=row['nome'], icon=folium.Icon(color='green' if stato=="DENTRO" else 'red')).add_to(m)

    draw = Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'circlemarker':False,'polygon':True})
    draw.add_to(m)
    output = st_folium(m, width=900, height=550, key="v4")

with col2:
    st.subheader("⚙️ Azioni")
    if output and output.get('all_drawings'):
        last = output['all_drawings'][-1]
        if last['geometry']['type'] == 'Polygon':
            coords = [[p[1], p[0]] for p in last['geometry']['coordinates'][0]]
            if st.button("💾 Salva Recinto"):
                c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(coords),))
                conn.commit()
                st.rerun()

    if st.button("🗑️ Elimina Recinto"):
        c.execute("DELETE FROM recinto WHERE id = 1"); conn.commit(); st.rerun()

    st.write("---")
    st.subheader("❌ Rimuovi Bovino")
    if not df_mandria.empty:
        selezionato = st.selectbox("Seleziona capo da eliminare", df_mandria['nome'].tolist())
        if st.button("Conferma eliminazione"):
            c.execute("DELETE FROM mandria WHERE nome = ?", (selezionato,))
            conn.commit()
            st.rerun()

st.write("---")
st.subheader("📋 Stato Mandria")
st.dataframe(df_mandria[['nome', 'batteria', 'stato_recinto']], use_container_width=True)

with st.sidebar:
    st.header("➕ Nuovo Bovino")
    id_t = st.text_input("ID Tracker")
    nome_t = st.text_input("Nome")
    if st.button("Aggiungi"):
        c.execute("INSERT OR REPLACE INTO mandria VALUES (?, ?, ?, ?, ?, ?)", (id_t, nome_t, 45.1743, 9.2394, 4.2, "DENTRO"))
        conn.commit(); st.rerun()
