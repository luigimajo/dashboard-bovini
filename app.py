import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import sqlite3
import json
import pandas as pd
import requests

# --- DATABASE: PULIZIA E AGGIORNAMENTO ---
conn = sqlite3.connect('bovini.db', check_same_thread=False)
c = conn.cursor()

# Se ci sono errori, forziamo la creazione delle colonne corrette
c.execute('CREATE TABLE IF NOT EXISTS mandria (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, batteria REAL, stato_recinto TEXT)')
c.execute('CREATE TABLE IF NOT EXISTS recinto (id INTEGER PRIMARY KEY, coords TEXT)')

# Forza l'aggiunta della colonna se il database è vecchio
try:
    c.execute('ALTER TABLE mandria ADD COLUMN stato_recinto TEXT')
except:
    pass
conn.commit()

# --- FUNZIONI ---
def invia_telegram(msg):
    try:
        token = st.secrets["TELEGRAM_TOKEN"].strip()
        chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
        requests.get(f"https://api.telegram.org{token}/sendMessage", params={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

def is_inside(lat, lon, poly_coords):
    if not poly_coords or len(poly_coords) < 3: return True
    try: return Polygon(poly_coords).contains(Point(lat, lon))
    except: return True

# --- INTERFACCIA ---
st.set_page_config(page_title="Monitoraggio Bovini", layout="wide")
st.title("🚜 Gestione Mandria")

# Caricamento Dati
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
saved_coords = json.loads(res[0]) if res and res[0] else []
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

col1, col2 = st.columns([3, 1])

with col1:
    # MAPPA SATELLITARE (Sorgente alternativa ultra-compatibile)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=15)
    
    # Layer Satellite ESRI (Fallback su Mapbox se fallisce)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com{z}/{y}/{x}',
        attr='Esri World Imagery',
        name='Satellite',
        overlay=False,
        control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.2).add_to(m)

    for i, row in df_mandria.iterrows():
        check_in = is_inside(row['lat'], row['lon'], saved_coords)
        nuovo_stato = "DENTRO" if check_in else "FUORI"
        
        # Allarme
        if row['stato_recinto'] == "DENTRO" and nuovo_stato == "FUORI":
            invia_telegram(f"🚨 {row['nome']} è USCITO dal recinto!")
        
        c.execute("UPDATE mandria SET stato_recinto = ? WHERE id = ?", (nuovo_stato, row['id']))
        folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color='green' if check_in else 'red')).add_to(m)

    conn.commit()
    Draw(draw_options={'polygon':True, 'polyline':False, 'rectangle':False, 'circle':False, 'marker':False}).add_to(m)
    output = st_folium(m, width=900, height=550, key="v_final")

with col2:
    st.subheader("⚙️ Azioni")
    if output and output.get('all_drawings'):
        last = output['all_drawings'][-1]
        coords = [[p[1], p[0]] for p in last['geometry']['coordinates'][0]]
        if st.button("💾 Salva Recinto"):
            c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(coords),))
            conn.commit()
            st.rerun()

    if st.button("🗑️ Rimuovi Recinto"):
        c.execute("DELETE FROM recinto WHERE id = 1"); conn.commit(); st.rerun()
    
    st.write("---")
    st.subheader("➕ Aggiungi Capo")
    id_n = st.text_input("ID Tracker")
    nome_n = st.text_input("Nome")
    if st.button("Registra"):
        # USIAMO INSERT OR REPLACE per evitare blocchi
        c.execute("INSERT OR REPLACE INTO mandria (id, nome, lat, lon, batteria, stato_recinto) VALUES (?, ?, ?, ?, ?, ?)", 
                  (id_n, nome_n, 45.1743, 9.2394, 4.2, "DENTRO"))
        conn.commit()
        st.rerun()

st.write("---")
st.subheader("📋 Tabella Mandria")
st.dataframe(df_mandria, use_container_width=True)
