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
        requests.get(f"https://api.telegram.org/bot{token}/sendMessage", params={"chat_id": chat_id, "text": msg}, timeout=10)
        return True
    except: return False

def is_inside(lat, lon, polygon_coords):
    if not polygon_coords or len(polygon_coords) < 3: return True
    try: return Polygon(polygon_coords).contains(Point(lat, lon))
    except: return True

# --- INTERFACCIA ---
st.set_page_config(page_title="Monitoraggio Bovini", layout="wide")
st.title("🚜 Gestione Mandria e Pascoli")

# Caricamento Dati
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
saved_coords = json.loads(res[0]) if res and res[0] else []
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

col1, col2 = st.columns([3, 1])

with col1:
    # MAPPA GOOGLE SATELLITE (Più stabile)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=15)
    folium.TileLayer(
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
        attr='Google Satellite',
        name='Google Satellite',
        overlay=False,
        control=True
    ).add_to(m)
    
    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.2).add_to(m)

    # Gestione Allarmi e Marker
    for i, row in df_mandria.iterrows():
        check_inside = is_inside(row['lat'], row['lon'], saved_coords)
        nuovo_stato = "DENTRO" if check_inside else "FUORI"
        
        # Allarme automatico al cambio stato
        if row['stato_recinto'] == "DENTRO" and nuovo_stato == "FUORI":
            invia_telegram(f"🚨 ALLARME: {row['nome']} è USCITO dal recinto!")
        
        c.execute("UPDATE mandria SET stato_recinto = ? WHERE id = ?", (nuovo_stato, row['id']))
        
        color = 'green' if nuovo_stato == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], popup=f"{row['nome']} ({row['batteria']}V)", 
                      icon=folium.Icon(color=color)).add_to(m)

    conn.commit()
    draw = Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'circlemarker':False,'polygon':True})
    draw.add_to(m)
    output = st_folium(m, width=900, height=550, key="v5")

with col2:
    st.subheader("⚙️ Azioni")
    if output and output.get('all_drawings'):
        last = output['all_drawings'][-1]
        if last['geometry']['type'] == 'Polygon':
            coords = [[p[1], p[0]] for p in last['geometry']['coordinates'][0]] # Inversione corretta
            if st.button("💾 Salva Recinto"):
                c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(coords),))
                conn.commit()
                st.rerun()

    if st.button("🗑️ Elimina Recinto"):
        c.execute("DELETE FROM recinto WHERE id = 1"); conn.commit(); st.rerun()

    st.write("---")
    st.subheader("❌ Rimuovi Bovino")
    if not df_mandria.empty:
        scelta = st.selectbox("Seleziona capo", df_mandria['nome'].tolist())
        if st.button("Elimina Capo"):
            c.execute("DELETE FROM mandria WHERE nome = ?", (scelta,))
            conn.commit(); st.rerun()

st.write("---")
st.subheader("📋 Tabella Mandria (Tempo Reale)")
if not df_mandria.empty:
    st.dataframe(df_mandria[['nome', 'id', 'batteria', 'stato_recinto', 'lat', 'lon']], use_container_width=True)
else:
    st.info("Nessun bovino in lista. Aggiungine uno dalla sidebar.")

with st.sidebar:
    st.header("➕ Registrazione")
    id_t = st.text_input("ID Tracker (DevEUI)")
    nome_t = st.text_input("Nome Animale")
    if st.button("Aggiungi"):
        c.execute("INSERT OR REPLACE INTO mandria VALUES (?, ?, ?, ?, ?, ?)", (id_t, nome_t, 45.1743, 9.2394, 4.2, "DENTRO"))
        conn.commit(); st.rerun()
