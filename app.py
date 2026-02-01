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

# --- FUNZIONE TELEGRAM (Migliorata con log) ---
def invia_telegram(msg):
    try:
        token = st.secrets["TELEGRAM_TOKEN"].strip()
        chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
        url = f"https://api.telegram.org{token}/sendMessage"
        r = requests.get(url, params={"chat_id": chat_id, "text": msg}, timeout=10)
        return r.status_code == 200
    except: return False

def is_inside(lat, lon, poly_coords):
    if not poly_coords or len(poly_coords) < 3: return True
    try: return Polygon(poly_coords).contains(Point(lat, lon))
    except: return True

st.set_page_config(page_title="Monitoraggio Bovini", layout="wide")
st.title("🚜 Dashboard Pascoli 2026")

# Carica Recinto e Mandria
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
saved_coords = json.loads(res[0]) if res else []
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

col1, col2 = st.columns([3, 1])

with col1:
    # SATELLITE ALTERNATIVO (Mapbox Community - Molto più stabile)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=15)
    
    # Layer Satellitare (Sorgente ultra-compatibile)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com{z}/{y}/{x}',
        attr='Esri World Imagery',
        name='Satellite',
        overlay=False,
        control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.2).add_to(m)

    # Gestione Marker e Allarme Automatico
    for i, row in df_mandria.iterrows():
        check_in = is_inside(row['lat'], row['lon'], saved_coords)
        nuovo_stato = "DENTRO" if check_in else "FUORI"
        
        # LOGICA ALLARME: Se lo stato salvato è diverso dal nuovo
        if row['stato_recinto'] == "DENTRO" and nuovo_stato == "FUORI":
            invia_telegram(f"🚨 ALLARME: {row['nome']} è USCITO dal recinto!")
        
        # Aggiorna database solo se lo stato è cambiato
        if row['stato_recinto'] != nuovo_stato:
            c.execute("UPDATE mandria SET stato_recinto = ? WHERE id = ?", (nuovo_stato, row['id']))
            conn.commit()

        color = 'green' if check_in else 'red'
        folium.Marker([row['lat'], row['lon']], popup=row['nome'], icon=folium.Icon(color=color)).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'circlemarker':False,'polygon':True}).add_to(m)
    output = st_folium(m, width=900, height=550, key="v_final_map")

with col2:
    st.subheader("⚙️ Azioni")
    if output and output.get('all_drawings'):
        last = output['all_drawings'][-1]
        if last['geometry']['type'] == 'Polygon':
            # Inversione coordinate [lon, lat] -> [lat, lon]
            raw_coords = last['geometry']['coordinates'][0]
            new_coords = [[p[1], p[0]] for p in raw_coords]
            if st.button("💾 Salva Recinto"):
                c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(new_coords),))
                conn.commit()
                st.rerun()

    if st.button("🗑️ Elimina Recinto"):
        c.execute("DELETE FROM recinto WHERE id = 1"); conn.commit(); st.rerun()

st.write("---")
st.subheader("📋 Lista Mandria")
st.dataframe(df_mandria[['nome', 'batteria', 'stato_recinto', 'id']], use_container_width=True)

with st.sidebar:
    st.header("➕ Gestione Capi")
    id_n = st.text_input("ID Tracker")
    nome_n = st.text_input("Nome")
    if st.button("Aggiungi/Aggiorna"):
        c.execute("INSERT OR REPLACE INTO mandria (id, nome, lat, lon, batteria, stato_recinto) VALUES (?, ?, ?, ?, ?, ?)", 
                  (id_n, nome_n, 45.1743, 9.2394, 4.2, "DENTRO"))
        conn.commit(); st.rerun()
    
    if not df_mandria.empty:
        scelta = st.selectbox("Rimuovi", df_mandria['nome'].tolist())
        if st.button("Elimina"):
            c.execute("DELETE FROM mandria WHERE nome = ?", (scelta,))
            conn.commit(); st.rerun()
