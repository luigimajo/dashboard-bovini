import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import sqlite3
import json
import pandas as pd
import requests

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="Monitoraggio Bovini")

# --- DATABASE (Corretto ordine colonne) ---
conn = sqlite3.connect('bovini.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS mandria 
             (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, stato_recinto TEXT, batteria INTEGER)''')
c.execute('CREATE TABLE IF NOT EXISTS recinto (id INTEGER PRIMARY KEY, coords TEXT)')
conn.commit()

# --- FUNZIONI ---
def is_inside(lat, lon, polygon_coords):
    if not polygon_coords or len(polygon_coords) < 3: return True
    poly = Polygon(polygon_coords)
    return poly.contains(Point(lat, lon))

def invia_telegram(msg):
    try:
        token = st.secrets["TELEGRAM_TOKEN"].strip()
        chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
        url = f"https://api.telegram.org{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
    except Exception: pass

# --- CARICAMENTO DATI ---
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
saved_coords = json.loads(res[0]) if res and res[0] else []
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

st.title("🛰️ Sistema Satellitare Bovini")

# --- SIDEBAR ---
st.sidebar.header("➕ Nuovo Bovino")
with st.sidebar.form("add_form"):
    new_id = st.text_input("ID Tracker")
    new_nome = st.text_input("Nome Bovino")
    if st.form_submit_button("Aggiungi"):
        # ORDINE CORRETTO: id, nome, lat, lon, stato_recinto, batteria
        c.execute("INSERT OR REPLACE INTO mandria VALUES (?, ?, ?, ?, ?, ?)", 
                  (new_id, new_nome, 45.1743, 9.2394, "DENTRO", 100))
        conn.commit()
        st.rerun()

st.sidebar.write("---")
if st.sidebar.button("🗑️ ELIMINA RECINTO"):
    c.execute("DELETE FROM recinto WHERE id = 1")
    conn.commit()
    st.rerun()

# --- MAPPA E TABELLA ---
col1, col2 = st.columns([2, 1])

with col1:
    # MAPPA SATELLITARE FORZATA (tiles=None + Google)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16, tiles=None)
    folium.TileLayer(
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
        attr='Google Satellite',
        name='Google Satellite',
        overlay=False,
        control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.1).add_to(m)

    for _, row in df_mandria.iterrows():
        icon_c = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], 
                      popup=f"{row['nome']} - {row['batteria']}%", 
                      icon=folium.Icon(color=icon_c)).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    
    out = st_folium(m, width=800, height=550, key="main_map")

    # Logica Salvataggio Recinto
    if out and out.get('all_drawings'):
        raw_poly = out['all_drawings'][-1]['geometry']['coordinates'][0]
        # Converte in [lat, lon]
        fixed_poly = [[p[1], p[0]] for p in raw_poly]
        if st.button("✅ Conferma Nuovo Recinto"):
            c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(fixed_poly),))
            conn.commit()
            st.rerun()

with col2:
    st.subheader("📊 Stato Mandria")
    if not df_mandria.empty:
        # Formattazione tabella
        st.dataframe(df_mandria[['nome', 'stato_recinto', 'batteria']], hide_index=True)
        
        st.write("---")
        st.subheader("🗑️ Rimuovi")
        to_del = st.selectbox("Seleziona:", df_mandria['nome'].tolist())
        if st.button("Elimina Bovino"):
            c.execute("DELETE FROM mandria WHERE nome=?", (to_del,))
            conn.commit()
            st.rerun()

        st.write("---")
        st.subheader("🧪 Simulatore")
        target = st.selectbox("Muovi:", df_mandria['nome'].tolist(), key="sim_sel")
        slat = st.number_input("Lat", value=45.1743, format="%.6f")
        slon = st.number_input("Lon", value=9.2394, format="%.6f")
        if st.button("Aggiorna Posizione"):
            c.execute("SELECT stato_recinto FROM mandria WHERE nome=?", (target,))
            vecchio = c.fetchone()[0]
            nuovo_in = is_inside(slat, slon, saved_coords)
            nuovo_stato = "DENTRO" if nuovo_in else "FUORI"
            
            if vecchio == "DENTRO" and nuovo_stato == "FUORI":
                invia_telegram(f"🚨 ALLARME: {target} è USCITO!")
            
            c.execute("UPDATE mandria SET lat=?, lon=?, stato_recinto=? WHERE nome=?", (slat, slon, nuovo_stato, target))
            conn.commit()
            st.rerun()
