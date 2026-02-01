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
# Tabella mandria
c.execute('CREATE TABLE IF NOT EXISTS mandria (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, batteria REAL, stato TEXT)')
# Tabella per il recinto (salviamo il poligono come stringa JSON)
c.execute('CREATE TABLE IF NOT EXISTS recinto (id INTEGER PRIMARY KEY, coords TEXT)')
conn.commit()

# --- FUNZIONI ---
def save_polygon(coords):
    c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(coords),))
    conn.commit()

def load_polygon():
    c.execute("SELECT coords FROM recinto WHERE id = 1")
    row = c.fetchone()
    return json.loads(row[0]) if row else []

def is_inside(lat, lon, polygon_coords):
    if len(polygon_coords) < 3: return True
    poly = Polygon(polygon_coords)
    return poly.contains(Point(lat, lon))

# --- INTERFACCIA ---
st.title("🚜 Dashboard Pascoli - Geofencing Permanente")

# Carica recinto salvato
saved_coords = load_polygon()

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=15)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com{z}/{y}/{x}',
        attr='Esri', name='Satellite'
    ).add_to(m)

    # Disegna il recinto salvato se esiste
    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.1).add_to(m)

    # Strumenti di disegno
    draw = Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'circlemarker':False,'polygon':True})
    draw.add_to(m)
    
    output = st_folium(m, width=900, height=600)

with col2:
    st.subheader("⚙️ Configurazione")
    
    # Logica per catturare il nuovo disegno
    new_coords = []
    if output and output['all_drawings']:
        last_draw = output['all_drawings'][-1]
        if last_draw['geometry']['type'] == 'Polygon':
            # Converte formato GeoJSON [lon, lat] in Folium [lat, lon]
            raw_coords = last_draw['geometry']['coordinates'][0]
            new_coords = [[p[1], p[0]] for p in raw_coords]
            
            if st.button("💾 Salva Questi Confini"):
                save_polygon(new_coords)
                st.success("Recinto salvato nel Database!")
                st.rerun()

    if st.button("🗑️ Rimuovi Recinto"):
        c.execute("DELETE FROM recinto WHERE id = 1")
        conn.commit()
        st.rerun()

# --- MONITORAGGIO ---
st.write("---")
# Simulazione (Sostituire con dati dal DB quando pronti i tracker)
bov_lat, bov_lon = 45.1760, 9.2410 

current_fence = new_coords if new_coords else saved_coords

if current_fence:
    if not is_inside(bov_lat, bov_lon, current_fence):
        st.error(f"🚨 ALLARME: Bovino FUORI dai confini salvati!")
    else:
        st.success("✅ Bovino all'interno del pascolo.")
else:
    st.warning("Nessun recinto definito. Disegnalo sulla mappa e clicca 'Salva'.")

# Configurazione Recinto
st.sidebar.subheader("📍 Recinto Virtuale")
raggio_allarme = st.sidebar.slider("Raggio Recinto (metri)", 50, 1000, 250)
centro_lat = 45.1743  # Pavia (Test)
centro_lon = 9.2394
centro_coords = (centro_lat, centro_lon)

# --- CORPO PRINCIPALE ---
st.title("🚜 Dashboard Monitoraggio Bovini")

# Recupera dati bovini
df_bovini = pd.read_sql_query("SELECT * FROM mandria", conn)

if not df_bovini.empty:
    # Mostriamo solo il primo per il test di allarme
    bovino_test = df_bovini.iloc[0]
    bov_coords = (bovino_test['lat'] + 0.003, bovino_test['lon'] + 0.003) # Forza fuori per test
    distanza = geodesic(centro_coords, bov_coords).meters

    # Layout a Colonne
    col1, col2 = st.columns([3, 1])

    with col1:
        # Mappa Satellitare
        m = folium.Map(location=centro_coords, zoom_start=15)
        folium.TileLayer(
            tiles='https://server.arcgisonline.com{z}/{y}/{x}',
            attr='Esri World Imagery', name='Satellite'
        ).add_to(m)

        # Disegna Recinto
        folium.Circle(location=centro_coords, radius=raggio_allarme, color="red", fill=True, fill_opacity=0.2).add_to(m)

        # Marker Bovini
        folium.Marker(location=bov_coords, popup=f"{bovino_test['nome']}", icon=folium.Icon(color='red', icon='cow', prefix='fa')).add_to(m)
        
        st_folium(m, width=900, height=500, returned_objects=[])

    with col2:
        st.subheader("Stato Allarmi")
        if distanza > raggio_allarme:
            st.error(f"🚨 FUORI RECINTO\n{bovino_test['nome']} a {int(distanza)}m")
            if st.button("🔔 Invia Allarme Telegram"):
                if invia_telegram(f"🚨 ALLARME: {bovino_test['nome']} è fuori dal recinto! Distanza: {int(distanza)}m"):
                    st.success("Telegram inviato!")
        else:
            st.success(f"✅ {bovino_test['nome']} è nel recinto.")
        
        st.metric("Batteria", f"{bovino_test['batteria']} V")

    st.subheader("📋 Lista Mandria")
    st.dataframe(df_bovini[['id', 'nome', 'stato', 'batteria']], use_container_width=True)

else:
    st.warning("Nessun bovino registrato. Usa la barra laterale per iniziare.")

st.info("Configurazione: Streamlit + SQLite + Telegram Bot. In attesa dei nuovi tracker.")
# --- PORTA D'INGRESSO PER DATI REALI (API) ---
# Questa parte permette di ricevere dati dall'esterno e aggiornare il database
if "update" in st.query_params:
    try:
        dev_id = st.query_params["id"]
        lat_val = float(st.query_params["lat"])
        lon_val = float(st.query_params["lon"])
        batt_val = float(st.query_params["batt"])
        
        # Aggiorna il database con i dati ricevuti
        c.execute("UPDATE mandria SET lat=?, lon=?, batteria=?, stato=? WHERE id=?", 
                  (lat_val, lon_val, batt_val, "Attivo", dev_id))
        conn.commit()
        st.write(f"Dato ricevuto per {dev_id}: {lat_val}, {lon_val}")
    except Exception as e:
        st.error(f"Errore aggiornamento API: {e}")
