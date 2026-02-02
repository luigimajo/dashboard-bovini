import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import sqlite3
import json
import pandas as pd
import requests

# --- DATABASE AGGIORNATO ---
conn = sqlite3.connect('bovini.db', check_same_thread=False)
c = conn.cursor()
# Aggiunta colonna batteria
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

# --- CARICAMENTO ---
c.execute("SELECT coords FROM recinto WHERE id = 1")
res = c.fetchone()
saved_coords = json.loads(res[0]) if res and res[0] else []
df_mandria = pd.read_sql_query("SELECT * FROM mandria", conn)

st.set_page_config(layout="wide", page_title="Gestione Mandria")
st.title("🐄 Monitoraggio Avanzato Pascolo")

# --- SIDEBAR: GESTIONE BOVINI ---
st.sidebar.header("➕ Nuovo Bovino")
with st.sidebar.form("add_form"):
    new_id = st.text_input("ID Tracker (es. Heltec_01)")
    new_nome = st.text_input("Nome/Marca Auricolare")
    if st.form_submit_button("Aggiungi alla Mandria"):
        c.execute("INSERT OR REPLACE INTO mandria VALUES (?, ?, ?, ?, ?, ?)", 
                  (new_id, new_nome, 45.1743, 9.2394, "DENTRO", 100))
        conn.commit()
        st.rerun()

st.sidebar.write("---")
st.sidebar.header("🗑️ Rimuovi Bovino")
if not df_mandria.empty:
    to_delete = st.sidebar.selectbox("Seleziona da rimuovere:", df_mandria['nome'].tolist())
    if st.sidebar.button("Elimina Definitivamente"):
        c.execute("DELETE FROM mandria WHERE nome=?", (to_delete,))
        conn.commit()
        st.rerun()

# --- CORPO PRINCIPALE ---
col1, col2 = st.columns([2, 1])

with col1:
    # Mappa Satellitare
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    folium.TileLayer(tiles='https://mt1.google.com{x}&y={y}&z={z}', 
                     attr='Google', name='Google Satellite', overlay=False).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", fill=True, fill_opacity=0.1).add_to(m)

    for _, row in df_mandria.iterrows():
        icon_c = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], 
                      popup=f"{row['nome']} - Batt: {row['batteria']}%", 
                      icon=folium.Icon(color=icon_c, icon='cow', prefix='fa')).add_to(m)

    draw = Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True})
    draw.add_to(m)
    out = st_folium(m, width=700, height=500, key="main_map")

    if out and out.get('all_drawings'):
        new_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
        fixed_coords = [[p[1], p[0]] for p in new_coords]
        if st.button("Salva questo Nuovo Recinto"):
            c.execute("INSERT OR REPLACE INTO recinto (id, coords) VALUES (1, ?)", (json.dumps(fixed_coords),))
            conn.commit()
            st.rerun()

with col2:
    st.subheader("📊 Stato Mandria")
    if not df_mandria.empty:
        # Tabella formattata con icone batteria
        display_df = df_mandria.copy()
        display_df['batteria'] = display_df['batteria'].apply(lambda x: f"🔋 {x}%")
        st.dataframe(display_df[['nome', 'stato_recinto', 'batteria']], hide_index=True)
        
        st.write("---")
        st.subheader("🧪 Simulatore")
        target = st.selectbox("Muovi:", df_mandria['nome'].tolist())
        slat = st.slider("Lat", 45.1700, 45.1800, 45.1743, format="%.6f")
        slon = st.slider("Lon", 9.2300, 9.2450, 9.2394, format="%.6f")
        sbatt = st.slider("Livello Batteria", 0, 100, 85)
        
        if st.button("Invia Update"):
            c.execute("SELECT stato_recinto FROM mandria WHERE nome=?", (target,))
            vecchio = c.fetchone()[0]
            nuovo_in = is_inside(slat, slon, saved_coords)
            nuovo_stato = "DENTRO" if nuovo_in else "FUORI"
            
            if vecchio == "DENTRO" and nuovo_stato == "FUORI":
                invia_telegram(f"🚨 ALLARME: {target} è USCITO dal recinto!")
            
            c.execute("UPDATE mandria SET lat=?, lon=?, stato_recinto=?, batteria=? WHERE nome=?", 
                      (slat, slon, nuovo_stato, sbatt, target))
            conn.commit()
            st.rerun()
    else:
        st.info("Aggiungi un bovino dalla barra laterale per iniziare.")
