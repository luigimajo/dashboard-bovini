import streamlit as st
import folium
from streamlit_folium import st_folium
import sqlite3
import pandas as pd

# --- CONFIGURAZIONE DATABASE ---
conn = sqlite3.connect('bovini.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS mandria (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, batteria REAL, stato TEXT)')
conn.commit()

st.set_page_config(page_title="Monitoraggio Bovini", layout="wide")

# --- SIDEBAR: GESTIONE MANDRIA ---
st.sidebar.title("🐂 Gestione Mandria")
nuovo_id = st.sidebar.text_input("ID Tracker (es. DevEUI)")
nuovo_nome = st.sidebar.text_input("Nome Bovino")

if st.sidebar.button("Registra Bovino"):
    try:
        c.execute('INSERT INTO mandria (id, nome, lat, lon, batteria, stato) VALUES (?, ?, ?, ?, ?, ?)', 
                  (nuovo_id, nuovo_nome, 45.17, 9.23, 4.2, "In attesa"))
        conn.commit()
        st.sidebar.success(f"{nuovo_nome} registrato!")
    except:
        st.sidebar.error("ID già esistente o errore.")

# --- DISPLAY LISTA BOVINI ---
st.sidebar.subheader("Lista Capi")
df = pd.read_sql_query("SELECT nome, batteria, stato FROM mandria", conn)
st.sidebar.dataframe(df)

# --- MAPPA PRINCIPALE ---
st.title("🚜 Dashboard Satellitare")

# Visualizzazione Mappa con fallback
m = folium.Map(location=[45.17, 9.23], zoom_start=15)
folium.TileLayer(
    tiles='https://server.arcgisonline.com{z}/{y}/{x}',
    attr='Esri World Imagery',
    name='Satellite'
).add_to(m)

# Recupera posizioni dal database e metti i marker
c.execute('SELECT nome, lat, lon FROM mandria')
for row in c.fetchall():
    folium.Marker([row[1], row[2]], popup=row[0], icon=folium.Icon(color='red')).add_to(m)

# Visualizzazione forzata
st_folium(m, width=1000, height=500, returned_objects=[])

st.write("---")
st.info("I dati del Gateway Dragino verranno visualizzati qui sotto.")
