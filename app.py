import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import sqlite3
import json
import pandas as pd
import requests

# --- INIZIALIZZAZIONE DATABASE ---
def init_db():
    conn = sqlite3.connect('bovini.db', check_same_thread=False)
    c = conn.cursor()
    # Creazione tabelle pulite
    c.execute('''CREATE TABLE IF NOT EXISTS mandria 
                 (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, batteria REAL, stato_recinto TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS recinto (id INTEGER PRIMARY KEY, coords TEXT)')
    conn.commit()
    return conn

conn = init_db()
c = conn.cursor()

# --- FUNZIONI CORE ---
def invia_telegram(msg):
    try:
        token = st.secrets["TELEGRAM_TOKEN"].strip()
        chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
        requests.get(f"https://api.telegram.org{token}/sendMessage", 
                     params={"chat_id": chat_id, "text": msg}, timeout=10)
    except: pass

def is_inside(lat, lon, poly_coords):
    if not poly_coords or len(poly_coords) < 3: return True
    try: return Polygon(poly_coords).contains(Point(lat, lon))
    except: return True

# --- INTERFACCIA ---
st.set_page_config(page_title="Monitoraggio Bovini", layout="wide")
st.title("🚜 Centro Comando Mandria")

# Caricamento Recinto
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
saved_coords = json.loads(res[0]) if res and res[0] else []

# Caricamento Mandria
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

col1, col2 = st.columns([3, 1])

with col1:
    st.subheader("Mappa Satellitare")
    # MAPPA SATELLITE (Sorgente alternativa ultra-stabile)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=15)
    folium.TileLayer(
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
        attr='Google', name='Google Hybrid', overlay=False, control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.15).add_to(m)

    # Logica Marker e Allarmi
    for _, row in df_mandria.iterrows():
        check_in = is_inside(row['lat'], row['lon'], saved_coords)
        nuovo_stato = "DENTRO" if check_in else "FUORI"
        
        # Allarme automatico
        if row['stato_recinto'] == "DENTRO" and nuovo_stato == "FUORI":
            invia_telegram(f"🚨 {row['nome']} è USCITO dal recinto!")
        
        c.execute("UPDATE mandria SET stato_recinto = ? WHERE id = ?", (nuovo_stato, row['id']))
        conn.commit()
        
        folium.Marker([row['lat'], row['lon']], 
                      popup=f"{row['nome']} ({row['batteria']}V)", 
                      icon=folium.Icon(color='green' if check_in else 'red')).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'circlemarker':False,'polygon':True}).add_to(m)
    output = st_folium(m, width=900, height=550, key="v_final_map")

with col2:
    st.subheader("⚙️ Gestione")
    
    # Salvataggio Recinto
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
    # Aggiunta e Rimozione Bovini
    with st.expander("➕ Aggiungi/Modifica"):
        id_n = st.text_input("ID Tracker")
        nome_n = st.text_input("Nome")
        if st.button("Salva Capo"):
            c.execute("INSERT OR REPLACE INTO mandria VALUES (?, ?, ?, ?, ?, ?)", (id_n, nome_n, 45.1743, 9.2394, 4.2, "DENTRO"))
            conn.commit(); st.rerun()

    if not df_mandria.empty:
        with st.expander("❌ Rimuovi Capo"):
            scelta = st.selectbox("Seleziona", df_mandria['nome'].tolist())
            if st.button("Elimina"):
                c.execute("DELETE FROM mandria WHERE nome = ?", (scelta,))
                conn.commit(); st.rerun()

st.write("---")
st.subheader("📋 Lista Mandria")
if not df_mandria.empty:
    st.dataframe(df_mandria[['nome', 'id', 'batteria', 'stato_recinto']], use_container_width=True)
else:
    st.info("Nessun bovino registrato.")

# Reset Database (Solo in caso di emergenza)
if st.sidebar.button("⚠️ Reset Totale Database"):
    c.execute("DROP TABLE IF EXISTS mandria")
    c.execute("DROP TABLE IF EXISTS recinto")
    conn.commit(); st.rerun()
