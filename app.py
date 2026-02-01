import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import sqlite3
import json
import pandas as pd

# --- DATABASE ---
conn = sqlite3.connect('bovini.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS mandria (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, batteria REAL, stato TEXT)')
c.execute('CREATE TABLE IF NOT EXISTS recinto (id INTEGER PRIMARY KEY, coords TEXT)')
conn.commit()

# --- FUNZIONI ---
def save_polygon(coords):
    c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(coords),))
    conn.commit()

def load_polygon():
    c.execute("SELECT coords FROM recinto WHERE id = 1")
    row = c.fetchone()
    if row:
        # row[0] contiene la stringa JSON, ci assicuriamo che sia trattata come tale
        try:
            return json.loads(str(row[0]))
        except:
            return []
    return []
    
def is_inside(lat, lon, polygon_coords):
    if len(polygon_coords) < 3: return True
    # Shapely vuole (lon, lat) o (lat, lon) coerenti; usiamo (lat, lon)
    poly = Polygon(polygon_coords)
    return poly.contains(Point(lat, lon))

st.set_page_config(page_title="Monitoraggio Bovini 2026", layout="wide")
st.title("🚜 Dashboard Mandria - Mappa e Lista")

# Carica dati
saved_coords = load_polygon()
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

col1, col2 = st.columns([3, 1])

with col1:
    # Centra la mappa sulla media delle posizioni o su Pavia
    map_center = [45.1743, 9.2394]
    if not df_mandria.empty:
        map_center = [df_mandria['lat'].mean(), df_mandria['lon'].mean()]
    
    m = folium.Map(location=map_center, zoom_start=15)
    folium.TileLayer(tiles='https://server.arcgisonline.com{z}/{y}/{x}', attr='Esri', name='Satellite').add_to(m)

    # Disegna Recinto
    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.1, popup="Recinto Pascolo").add_to(m)

    # Marker per ogni Bovino nella lista
   for index, row in df_mandria.iterrows():
    # Determina colore in base a batteria e recinto
    current_lat = row['lat']
    current_lon = row['lon']
    
    marker_color = 'green' if row['batteria'] > 3.7 else 'orange'
    
    if saved_coords and len(saved_coords) >= 3:
        if not is_inside(current_lat, current_lon, saved_coords):
            marker_color = 'red' # Allarme fuori recinto
    
    folium.Marker(
        location=[current_lat, current_lon],
        popup=f"Bovino: {row['nome']}<br>Batt: {row['batteria']}V",
        tooltip=row['nome'],
        icon=folium.Icon(color=marker_color, icon='info-sign') 
    ).add_to(m)

    # Strumenti di disegno
    draw = Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'circlemarker':False,'polygon':True})
    draw.add_to(m)
    output = st_folium(m, width=900, height=550)

with col2:
    st.subheader("⚙️ Gestione")
    # Logica cattura nuovo recinto
    if output and output['all_drawings']:
        last_draw = output['all_drawings'][-1]
        if last_draw['geometry']['type'] == 'Polygon':
            raw_coords = last_draw['geometry']['coordinates'][0]
            new_coords = [[p[1], p[0]] for p in raw_coords] # Inverte (lon,lat) in (lat,lon)
            if st.button("💾 Salva Nuovi Confini"):
                save_polygon(new_coords)
                st.success("Salvato!")
                st.rerun()

    if st.button("🗑️ Elimina Recinto"):
        c.execute("DELETE FROM recinto WHERE id = 1")
        conn.commit()
        st.rerun()

# --- TABELLA RIASSUNTIVA ---
st.write("---")
st.subheader("📋 Elenco Capi in Tempo Reale")
if not df_mandria.empty:
    # Aggiunge colonna stato posizione basata sul recinto
    if saved_coords:
        df_mandria['Posizione'] = df_mandria.apply(lambda r: "✅ Dentro" if is_inside(r['lat'], r['lon'], saved_coords) else "🚨 FUORI", axis=1)
    else:
        df_mandria['Posizione'] = "Nessun Recinto"
    
    # Visualizza tabella
    st.dataframe(df_mandria[['nome', 'batteria', 'lat', 'lon', 'Posizione', 'stato']], use_container_width=True)
else:
    st.info("Nessun bovino registrato nel database.")

# Sidebar per aggiungere nuovi bovini (necessaria se non ne hai ancora inseriti)
with st.sidebar:
    st.header("➕ Registrazione")
    id_t = st.text_input("ID Tracker")
    nome_t = st.text_input("Nome")
    if st.button("Aggiungi"):
        c.execute("INSERT OR REPLACE INTO mandria VALUES (?, ?, ?, ?, ?, ?)", (id_t, nome_t, 45.1743, 9.2394, 4.2, "Attivo"))
        conn.commit()
        st.rerun()
