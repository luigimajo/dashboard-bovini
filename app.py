import streamlit as st
import folium
from streamlit_folium import st_folium
import sqlite3
import requests
import pandas as pd
from geopy.distance import geodesic

# --- CONFIGURAZIONE INIZIALE ---
st.set_page_config(page_title="Monitoraggio Bovini 2026", layout="wide")

# Funzione per inviare allarmi Telegram (Sicura)
def invia_telegram(msg):
    try:
        # Recuperiamo i dati dai Secrets di Streamlit (non dal codice)
        token = str(st.secrets["8398754184:AAHF3KH5CK8pf4J5xFKpYzaTTq7DE1FwGPA"]).strip()
        chat_id = str(st.secrets["6892481042"]).strip()
        
        # Pulizia di sicurezza se hai incollato "bot" per errore
        if token.lower().startswith('bot'):
            token = token[3:]
            
        # Costruzione URL con barre forzate
        base_url = "https://api.telegram.org"
        full_url = f"{base_url}/bot{token}/sendMessage"
        
        params = {"chat_id": chat_id, "text": msg}
        response = requests.get(full_url, params=params, timeout=10)
        
        if response.status_code == 200:
            return True
        else:
            st.error(f"Errore Telegram: {response.text}")
            return False
    except Exception as e:
        st.error(f"Errore configurazione: {e}")
        return False

# --- GESTIONE DATABASE ---
conn = sqlite3.connect('bovini.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS mandria 
             (id TEXT PRIMARY KEY, nome TEXT, lat REAL, lon REAL, batteria REAL, stato TEXT)''')
conn.commit()

# --- SIDEBAR: GESTIONE ---
st.sidebar.title("🐂 Gestione Mandria")

# Aggiunta Bovino
with st.sidebar.expander("➕ Registra Nuovo Capo"):
    n_id = st.text_input("ID Tracker (DevEUI)")
    n_nome = st.text_input("Nome Animale")
    if st.button("Salva nel Database"):
        try:
            c.execute("INSERT INTO mandria VALUES (?, ?, ?, ?, ?, ?)", 
                      (n_id, n_nome, 45.1743, 9.2394, 4.2, "In attesa"))
            conn.commit()
            st.success(f"{n_nome} registrato!")
        except:
            st.error("Errore: ID già esistente.")

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
