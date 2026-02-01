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
        try:
            return json.loads(str(row[0]))
        except:
            return []
    return []

def is_inside(lat, lon, polygon_coords):
    if len(polygon_coords) < 3:
        return True
    try:
        poly = Polygon(polygon_coords)
        return poly.contains(Point(lat, lon))
    except:
        return True

st.set_page_config(page_title="Monitoraggio Bovini 2026", layout="wide")
st.title("🚜 Dashboard Mandria - Mappa e Lista")

# Carica dati
saved_coords = load_polygon()
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

col1, col2 = st.columns([3, 1])

with col1:
    # Centra la mappa
    map_center = [45.1743, 9.2394]
    if not df_mandria.empty:
        map_center = [df_mandria['lat'].mean(), df_mandria['lon'].mean()]
    
    m = folium.Map(location=map_center, zoom_start=15)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com{z}/{y}/{x}', 
        attr='Esri', 
        name='Satellite'
    ).add_to(m)

    # Disegna Recinto Salvato
    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.15).add_to(m)

    # Marker per ogni Bovino
    for index, row in df_mandria.iterrows():
        b_lat, b_lon = row['lat'], row['lon']
        marker_color = 'green' if row['batteria'] > 3.7 else 'orange'
        
        if saved_coords and not is_inside(b_lat, b_lon, saved_coords):
            marker_color = 'red' # Allarme fuori
        
        folium.Marker(
            location=[b_lat, b_lon],
            popup=f"Bovino: {row['nome']}<br>Batt: {row['batteria']}V",
            tooltip=row['nome'],
            icon=folium.Icon(color=marker_color, icon='info-sign')
        ).add_to(m)

    # Strumenti di disegno
    draw = Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'circlemarker':False,'polygon':True})
    draw.add_to(m)
    output = st_folium(m, width=900, height=550, key="map_main")

with col2:
    st.subheader("⚙️ Gestione")
    
    # Cattura disegno
    if output and output['all_drawings']:
        last_draw = output['all_drawings'][-1]
        if last_draw['geometry']['type'] == 'Polygon':
            raw_coords = last_draw['geometry']['coordinates'][0]
            new_coords = [[p[1], p[0]] for p in raw_coords] # Inverte lon,lat in lat,lon
            if st.button("💾 Salva Recinto"):
                save_polygon(new_coords)
                st.success("Salvato!")
                st.rerun()

    if st.button("🗑️ Elimina Recinto"):
        c.execute("DELETE FROM recinto WHERE id = 1")
        conn.commit()
        st.rerun()

# --- TABELLA RIASSUNTIVA ---
st.write("---")
st.subheader("📋 Elenco Capi")
if not df_mandria.empty:
    if saved_coords:
        df_mandria['Posizione'] = df_mandria.apply(lambda r: "✅ Dentro" if is_inside(r['lat'], r['lon'], saved_coords) else "🚨 FUORI", axis=1)
    else:
        df_mandria['Posizione'] = "Nessun Recinto"
    
    st.dataframe(df_mandria[['nome', 'batteria', 'lat', 'lon', 'Posizione', 'stato']], use_container_width=True)
else:
    st.info("Nessun bovino registrato.")

# Sidebar per aggiunta rapida
with st.sidebar:
    st.header("➕ Registrazione")
    id_t = st.text_input("ID Tracker")
    nome_t = st.text_input("Nome")
    if st.button("Aggiungi"):
        c.execute("INSERT OR REPLACE INTO mandria VALUES (?, ?, ?, ?, ?, ?)", (id_t, nome_t, 45.1743, 9.2394, 4.2, "Attivo"))
        conn.commit()
        st.rerun()
