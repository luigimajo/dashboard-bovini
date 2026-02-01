import streamlit as st
import folium
from streamlit_folium import st_folium
import sqlite3
import requests
from geopy.distance import geodesic # Aggiungi 'geopy' al file requirements.txt

# --- FUNZIONI CORE ---
def invia_telegram(msg):
    token = st.secrets["TELEGRAM_TOKEN"]
    chat_id = st.secrets["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org{token}/sendMessage?chat_id={chat_id}&text={msg}"
    requests.get(url)

# --- APP ---
st.title("🚜 Dashboard Bovini 2026")

# Configurazione Recinto in Sidebar
st.sidebar.header("📍 Recinto Virtuale")
raggio_allarme = st.sidebar.slider("Raggio (metri)", 50, 1000, 200)
centro_coords = (45.1743, 9.2394) # Pavia di test

# Mappa
m = folium.Map(location=centro_coords, zoom_start=15)
folium.TileLayer(tiles='https://server.arcgisonline.com{z}/{y}/{x}', attr='Esri').add_to(m)
folium.Circle(location=centro_coords, radius=raggio_allarme, color="red", fill=True).add_to(m)

# Simula posizione bovino per test
bovino_coords = (45.1760, 9.2410) 
distanza = geodesic(centro_coords, bovino_coords).meters

if distanza > raggio_allarme:
    st.error(f"⚠️ ALLARME: Bovino fuori recinto! Distanza: {int(distanza)}m")
    if st.button("Invia Allarme a Telegram"):
        invia_telegram(f"🚨 ATTENZIONE: Un bovino è uscito dal recinto! Distanza attuale: {int(distanza)} metri.")
else:
    st.success("✅ Tutti i bovini sono nel recinto.")

st_folium(m, width=1000, height=500)
