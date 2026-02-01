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

# --- FUNZIONE TELEGRAM (Ripristinata logica funzionante) ---
def invia_telegram(msg):
    token = st.secrets["TELEGRAM_TOKEN"].strip()
    chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
    url = f"https://api.telegram.org{token}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
    except:
        pass

def is_inside(lat, lon, poly_coords):
    if not poly_coords or len(poly_coords) < 3: return True
    try:
        # Assicuriamoci che poly_coords sia una lista di liste/tuple
        poly = Polygon(poly_coords)
        return poly.contains(Point(lat, lon))
    except: return True

st.set_page_config(page_title="Monitoraggio Bovini", layout="wide")
st.title("🚜 Dashboard Pascoli - Satellite & Allarmi")

# Caricamento Dati
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
# Correzione caricamento recinto per evitare errori di tipo
saved_coords = json.loads(res[0]) if res and res[0] else []
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

col1, col2 = st.columns([3, 1])

with col1:
    # SATELLITE GOOGLE HYBRID (Forzato con protocollo HTTP per evitare blocchi)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=15)
    
    folium.TileLayer(
        tiles='http://www.google.cn{x}&y={y}&z={z}',
        attr='Google',
        name='Google Satellite',
        overlay=False,
        control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.2).add_to(m)

    # LOGICA ALLARME (Ripristinata e semplificata)
    for i, row in df_mandria.iterrows():
        check_in = is_inside(row['lat'], row['lon'], saved_coords)
        nuovo_stato = "DENTRO" if check_in else "FUORI"
        
        # Se lo stato cambia da DENTRO a FUORI, spara l'allarme
        if row['stato_recinto'] == "DENTRO" and nuovo_stato == "FUORI":
            invia_telegram(f"🚨 ALLARME: {row['nome']} è uscito dal recinto!")
        
        # Aggiorna sempre il database per riflettere lo stato attuale
        c.execute("UPDATE mandria SET stato_recinto = ? WHERE id = ?", (nuovo_stato, row['id']))
        
        color = 'green' if check_in else 'red'
        folium.Marker([row['lat'], row['lon']], popup=row['nome'], icon=folium.Icon(color=color)).add_to(m)

    conn.commit()
    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'circlemarker':False,'polygon':True}).add_to(m)
    output = st_folium(m, width=900, height=550, key="v_final_2200")

with col2:
    st.subheader("⚙️ Azioni")
    if output and output.get('all_drawings'):
        last = output['all_drawings'][-1]
        if last['geometry']['type'] == 'Polygon':
            raw_coords = last['geometry']['coordinates'][0]
            # Inversione [lon, lat] -> [lat, lon]
            new_coords = [[p[1], p[0]] for p in raw_coords]
            if st.button("💾 Salva Recinto"):
                c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(new_coords),))
                conn.commit()
                st.rerun()

    if st.button("🗑️ Elimina Recinto"):
        c.execute("DELETE FROM recinto WHERE id = 1"); conn.commit(); st.rerun()
    
    st.write("---")
    st.subheader("➕ Gestione Capi")
    id_n = st.text_input("ID Tracker")
    nome_n = st.text_input("Nome")
    if st.button("Aggiungi/Aggiorna"):
        c.execute("INSERT OR REPLACE INTO mandria (id, nome, lat, lon, batteria, stato_recinto) VALUES (?, ?, ?, ?, ?, ?)", 
                  (id_n, nome_n, 45.1743, 9.2394, 4.2, "DENTRO"))
        conn.commit(); st.rerun()

st.write("---")
st.subheader("📋 Tabella Mandria")
st.dataframe(df_mandria[['nome', 'batteria', 'stato_recinto', 'lat', 'lon']], use_container_width=True)
