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

# --- DATABASE LOCALE ---
conn = sqlite3.connect('bovini.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS mandria (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, stato_recinto TEXT)')
c.execute('CREATE TABLE IF NOT EXISTS recinto (id INTEGER PRIMARY KEY, coords TEXT)')
conn.commit()

# --- FUNZIONE GEOFENCING ---
def is_inside(lat, lon, polygon_coords):
    if not polygon_coords or len(polygon_coords) < 3: 
        return True
    poly = Polygon(polygon_coords)
    point = Point(lat, lon)
    return poly.contains(point)

# --- FUNZIONE TELEGRAM (Corretta) ---
def invia_telegram(msg):
    try:
        token = st.secrets["TELEGRAM_TOKEN"].strip()
        chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
        # La URL corretta richiede "bot" prima del token
        url = f"https://api.telegram.org{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
    except Exception as e:
        st.error(f"Errore Telegram: {e}")

# --- CARICAMENTO DATI ---
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
saved_coords = json.loads(res[0]) if res and res[0] else []
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

st.title("🛰️ Dashboard Monitoraggio Pascolo")

col1, col2 = st.columns([3, 1])

with col2:
    st.subheader("🛠️ Gestione Mandria")
    
    # Form aggiunta bovino
    with st.expander("➕ Aggiungi Nuovo Bovino"):
        id_n = st.text_input("ID Tracker (es. Heltec_01)")
        nome_n = st.text_input("Nome Bovino")
        if st.button("Salva Bovino"):
            c.execute("INSERT OR REPLACE INTO mandria VALUES (?, ?, ?, ?, ?)", (id_n, nome_n, 45.1743, 9.2394, "DENTRO"))
            conn.commit()
            st.rerun()

    st.write("---")
    
    # Test Movimento e Allarme
    if not df_mandria.empty:
        st.subheader("🧪 Test Allarme")
        bov_sel = st.selectbox("Seleziona Bovino:", df_mandria['nome'].tolist())
        nuova_lat = st.number_input("Latitudine", value=45.1743, format="%.6f")
        nuova_lon = st.number_input("Longitudine", value=9.2394, format="%.6f")
        
        if st.button("Simula Spostamento"):
            # Recupera stato precedente
            c.execute("SELECT stato_recinto FROM mandria WHERE nome=?", (bov_sel,))
            stato_precedente = c.fetchone()[0]
            
            # Calcola nuovo stato
            check_in = is_inside(nuova_lat, nuova_lon, saved_coords)
            nuovo_stato = "DENTRO" if check_in else "FUORI"
            
            # LOGICA ALLARME: Scatta solo se passa da DENTRO a FUORI
            if stato_precedente == "DENTRO" and nuovo_stato == "FUORI":
                invia_telegram(f"🚨 ALLARME: {bov_sel} è USCITO dal recinto!")
                st.warning(f"Messaggio inviato per {bov_sel}!")
            
            c.execute("UPDATE mandria SET lat=?, lon=?, stato_recinto=? WHERE nome=?", 
                      (nuova_lat, nuova_lon, nuovo_stato, bov_sel))
            conn.commit()
            st.rerun()
    
    if st.button("🗑️ Elimina Recinto"):
        c.execute("DELETE FROM recinto WHERE id = 1")
        conn.commit()
        st.rerun()

with col1:
    # MAPPA SATELLITARE (ESRI)
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    
    folium.TileLayer(
        tiles='https://server.arcgisonline.com{z}/{y}/{x}',
        attr='Esri World Imagery',
        name='Satellite'
    ).add_to(m)

    # Disegna Recinto Esistente
    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", weight=3, fill=True, fill_opacity=0.2).add_to(m)

    # Posiziona Bovini
    for i, row in df_mandria.iterrows():
        color = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker(
            [row['lat'], row['lon']], 
            popup=f"{row['nome']} ({row['stato_recinto']})",
            icon=folium.Icon(color=color, icon='info-sign')
        ).add_to(m)

    # Strumenti di disegno
    Draw(draw_options={
        'polyline': False, 'rectangle': False, 'circle': False, 'marker': False, 'circlemarker': False,
        'polygon': True
    }).add_to(m)
    
    # Render Mappa
    output = st_folium(m, width=800, height=600, key="map")

    # Salva nuovo recinto se disegnato
    if output and output.get('all_drawings'):
        last = output['all_drawings'][-1]
        if last['geometry']['type'] == 'Polygon':
            # Converte coordinate per Shapely (lon, lat) -> (lat, lon) per Folium
            raw_coords = last['geometry']['coordinates'][0]
            # Invertiamo le coppie per Folium/Shapely
            corrected_coords = [[p[1], p[0]] for p in raw_coords]
            c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(corrected_coords),))
            conn.commit()
            st.success("Recinto salvato! Ricarica la pagina.")
            if st.button("Aggiorna Mappa"):
                st.rerun()
