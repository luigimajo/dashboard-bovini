import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import sqlite3
import json
import pandas as pd
import requests

# --- DATABASE (CONFIGURAZIONE FORZATA) ---
conn = sqlite3.connect('bovini.db', check_same_thread=False)
c = conn.cursor()

# Verifichiamo l'ordine esatto delle colonne per evitare l'inversione
c.execute('CREATE TABLE IF NOT EXISTS mandria (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, stato_recinto TEXT, batteria INTEGER)')

# CONTROLLO COLONNE: Se i dati sono invertiti, resettiamo la tabella per sicurezza
try:
    c.execute("SELECT batteria FROM mandria LIMIT 1")
except sqlite3.OperationalError:
    # Se la colonna batteria non esiste o è in posizione errata, resettiamo
    c.execute("DROP TABLE IF EXISTS mandria")
    c.execute('CREATE TABLE mandria (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, stato_recinto TEXT, batteria INTEGER)')

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

st.set_page_config(layout="wide")
st.title("🛰️ Monitoraggio Bovini - Satellitare")

# --- SIDEBAR: AGGIUNGI E RIMUOVI ---
st.sidebar.header("📋 Gestione Mandria")

with st.sidebar.expander("➕ Aggiungi Bovino"):
    n_id = st.text_input("ID Tracker")
    n_nome = st.text_input("Nome/Marca")
    if st.button("Salva"):
        if n_id and n_nome:
            # Specifichiamo le colonne per evitare inversioni
            c.execute("INSERT OR REPLACE INTO mandria (id, nome, lat, lon, stato_recinto, batteria) VALUES (?, ?, ?, ?, ?, ?)", 
                      (n_id, n_nome, 45.1743, 9.2394, "DENTRO", 100))
            conn.commit()
            st.rerun()

if not df_mandria.empty:
    with st.sidebar.expander("🗑️ Rimuovi Bovino"):
        bov_da_eliminar = st.selectbox("Seleziona:", df_mandria['nome'].tolist())
        if st.button("Elimina"):
            c.execute("DELETE FROM mandria WHERE nome=?", (bov_da_eliminar,))
            conn.commit()
            st.rerun()

# --- LAYOUT PRINCIPALE ---
col1, col2 = st.columns([3, 1])

with col2:
    st.subheader("📍 Test Movimento")
    if not df_mandria.empty:
        bov_sel = st.selectbox("Sposta:", df_mandria['nome'].tolist())
        n_lat = st.number_input("Lat", value=45.1743, format="%.6f")
        n_lon = st.number_input("Lon", value=9.2394, format="%.6f")
        
        if st.button("Aggiorna Posizione"):
            c.execute("SELECT stato_recinto FROM mandria WHERE nome=?", (bov_sel,))
            r = c.fetchone()
            stato_vecchio = r[0] if r else "DENTRO"
            
            nuovo_in = is_inside(n_lat, n_lon, saved_coords)
            stato_nuovo = "DENTRO" if nuovo_in else "FUORI"
            
            if stato_vecchio == "DENTRO" and stato_nuovo == "FUORI":
                invia_telegram(f"🚨 ALLARME: {bov_sel} è USCITO!")
            
            c.execute("UPDATE mandria SET lat=?, lon=?, stato_recinto=? WHERE nome=?", (n_lat, n_lon, stato_nuovo, bov_sel))
            conn.commit()
            st.rerun()

with col1:
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    folium.TileLayer(
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
        attr='Google Satellite', name='Google Satellite', overlay=False, control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", weight=5, fill=True, fill_opacity=0.2).add_to(m)

    for i, row in df_mandria.iterrows():
        col = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], popup=row['nome'], icon=folium.Icon(color=col)).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    
    out = st_folium(m, width=800, height=550, key="main_map")

    if out and out.get('all_drawings'):
        new_poly = out['all_drawings'][-1]['geometry']['coordinates'][0]
        fixed_poly = [[p[1], p[0]] for p in new_poly]
        if st.button("Salva Recinto"):
            c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(fixed_poly),))
            conn.commit()
            st.rerun()

# --- LISTA BOVINI (SOTTO) ---
st.write("---")
st.subheader(f"📊 Lista Mandria ({len(df_mandria)} capi)")
if not df_mandria.empty:
    # Esplicitiamo l'ordine delle colonne nella visualizzazione
    st.dataframe(df_mandria[['id', 'nome', 'lat', 'lon', 'stato_recinto', 'batteria']], use_container_width=True, hide_index=True)
