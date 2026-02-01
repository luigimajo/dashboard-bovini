import streamlit as st
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Monitoraggio Bovini", layout="wide")

st.title("🚜 Sistema Monitoraggio Bovini 2026")

# Sidebar per gestione
st.sidebar.header("Configurazione")
bovino_nome = st.sidebar.text_input("Aggiungi Nome Bovino", "Bovino 1")
if st.sidebar.button("Aggiungi"):
    st.sidebar.success(f"{bovino_nome} aggiunto alla lista!")

# Simulazione Stato Gateway
st.sidebar.subheader("Stato Gateway")
st.sidebar.success("Dragino LPS8N: ONLINE")

# Creazione Mappa Satellitare
st.subheader("Mappa Satellitare Pascoli")
# Coordinate di partenza (Pavia - potrai cambiarle)
m = folium.Map(location=[45.17, 9.23], zoom_start=15, tiles='https://mt1.google.com{x}&y={y}&z={z}', attr='Google')

# Aggiungiamo un marker di esempio
folium.Marker(
    [45.17, 9.23], 
    popup="Bovino 1", 
    tooltip="Vedi dettagli",
    icon=folium.Icon(color='red', icon='info-sign')
).add_to(m)

# Visualizza la mappa
st_data = st_folium(m, width=1200, height=600)

st.info("In attesa di dati reali dal Webhook di TTN...")
