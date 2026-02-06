import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import json
import pandas as pd
import requests
from datetime import datetime

# --- CONNESSIONE DATABASE ---
conn = st.connection("postgresql", type="sql")

# --- FUNZIONI CORE ---
def is_inside(lat, lon, polygon_coords):
    if not polygon_coords or len(polygon_coords) < 3: return True
    poly = Polygon(polygon_coords)
    return poly.contains(Point(lat, lon))

def invia_telegram(msg):
    try:
        token = st.secrets["TELEGRAM_TOKEN"].strip()
        chat_id = st.secrets["TELEGRAM_CHAT_ID"].strip()
        url = f"https://api.telegram.org{token}/sendMessage"
        resp = requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- INTEGRAZIONE TTN (Dati Reali) ---
def fetch_ttn_data():
    """Recupera l'ultimo uplink da TTN Storage Integration"""
    app_id = st.secrets["TTN_APP_ID"]
    api_key = st.secrets["TTN_API_KEY"]
    url = f"https://eu1.cloud.thethings.network{app_id}/packages/storage/uplink_message"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "text/event-stream"}
    
    try:
        # Limitiamo la ricerca agli ultimi dati per non sovraccaricare
        response = requests.get(url, headers=headers, params={"limit": 10, "order": "-received_at"}, timeout=15)
        if response.status_code == 200:
            # TTN Storage restituisce oggetti JSON separati da newline
            lines = response.text.strip().split('\n')
            for line in reversed(lines):
                data = json.loads(line)
                device_id = data["end_device_ids"]["device_id"]
                payload = data.get("uplink_message", {}).get("decoded_payload", {})
                
                lat = payload.get("latitude") or payload.get("lat")
                lon = payload.get("longitude") or payload.get("lon")
                bat = payload.get("battery") or payload.get("batt", 100)
                
                if lat and lon:
                    return device_id, lat, lon, bat
    except Exception as e:
        st.error(f"Errore TTN: {e}")
    return None

# --- CARICAMENTO DATI DB ---
df_recinti = conn.query("SELECT * FROM recinti", ttl=0)
df_mandria = conn.query("SELECT * FROM mandria", ttl=0)

# Coordinate del primo recinto (se presente) per calcolo dentro/fuori
saved_coords = []
if not df_recinti.empty:
    saved_coords = json.loads(df_recinti.iloc[0]['coords'])

st.set_page_config(layout="wide", page_title="Monitoraggio Bovini")
st.title("🛰️ Monitoraggio Bovini - Satellitare")

# --- SIDEBAR: GESTIONE ---
st.sidebar.header("📋 Gestione Mandria")

with st.sidebar.expander("➕ Aggiungi Bovino"):
    n_id = st.text_input("ID Tracker (es. heltec-v3-01)")
    n_nome = st.text_input("Nome Bovino")
    if st.button("Salva Bovino"):
        if n_id and n_nome:
            with conn.session as s:
                s.execute(
                    "INSERT INTO mandria (id, nome, lat, lon, batteria, stato_recinto, allarme_attivo) VALUES (:id, :nome, :lat, :lon, :bat, :stato, :allarme) ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome",
                    {"id": n_id, "nome": n_nome, "lat": 45.1743, "lon": 9.2394, "bat": 100, "stato": "DENTRO", "allarme": True}
                )
                s.commit()
            st.rerun()

# --- LAYOUT PRINCIPALE ---
col1, col2 = st.columns([3, 1])

with col2:
    st.subheader("⚙️ Controllo Sistema")
    allarme_globale = st.toggle("Verifica Posizioni Attiva", value=True, help="Disabilita per spostamenti programmati")
    
    if st.button("🔄 Sincronizza con TTN"):
        ttn_res = fetch_ttn_data()
        if ttn_res:
            dev_id, t_lat, t_lon, t_bat = ttn_res
            # Verifica se il device esiste nel nostro DB
            if dev_id in df_mandria['id'].values:
                bov_info = df_mandria[df_mandria['id'] == dev_id].iloc[0]
                vecchio_stato = bov_info['stato_recinto']
                nuovo_stato = "DENTRO" if is_inside(t_lat, t_lon, saved_coords) else "FUORI"
                
                # Logica Allarme
                if allarme_globale and vecchio_stato == "DENTRO" and nuovo_stato == "FUORI":
                    invia_telegram(f"🚨 ALLARME TTN: {bov_info['nome']} ({dev_id}) è USCITO!")
                
                with conn.session as s:
                    s.execute(
                        "UPDATE mandria SET lat=:lat, lon=:lon, batteria=:bat, stato_recinto=:st, ultimo_aggiornamento=NOW() WHERE id=:id",
                        {"lat": t_lat, "lon": t_lon, "bat": t_bat, "st": nuovo_stato, "id": dev_id}
                    )
                    s.commit()
                st.success(f"Aggiornato: {dev_id}")
                st.rerun()
            else:
                st.warning(f"Device {dev_id} trovato su TTN ma non nel Database locale.")
        else:
            st.info("Nessun nuovo dato da TTN negli ultimi minuti.")

    st.write("---")
    st.subheader("📍 Test Movimento")
    if not df_mandria.empty:
        bov_sel = st.selectbox("Sposta:", df_mandria['nome'].tolist())
        n_lat = st.number_input("Lat Test", value=45.1743, format="%.6f")
        n_lon = st.number_input("Lon Test", value=9.2394, format="%.6f")
        if st.button("Aggiorna Manuale"):
            bov_row = df_mandria[df_mandria['nome'] == bov_sel].iloc[0]
            nuovo_in = is_inside(n_lat, n_lon, saved_coords)
            stato_nuovo = "DENTRO" if nuovo_in else "FUORI"
            
            if allarme_globale and bov_row['stato_recinto'] == "DENTRO" and stato_nuovo == "FUORI":
                invia_telegram(f"🚨 ALLARME TEST: {bov_sel} è USCITO!")
            
            with conn.session as s:
                s.execute("UPDATE mandria SET lat=:lat, lon=:lon, stato_recinto=:st, ultimo_aggiornamento=NOW() WHERE nome=:n",
                          {"lat": n_lat, "lon": n_lon, "st": stato_nuovo, "n": bov_sel})
                s.commit()
            st.rerun()

with col1:
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    folium.TileLayer(tiles='https://mt1.google.com{x}&y={y}&z={z}', attr='Google Satellite', name='Google').add_to(m)

    for _, r in df_recinti.iterrows():
        folium.Polygon(locations=json.loads(r['coords']), color="yellow", fill=True, fill_opacity=0.2, popup=r['nome']).add_to(m)

    for _, row in df_mandria.iterrows():
        color = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], popup=f"{row['nome']} ({row['batteria']}%)", icon=folium.Icon(color=color)).add_to(m)

    Draw(draw_options={'polyline':False,'polygon':True}).add_to(m)
    out = st_folium(m, width=800, height=500, key="main_map")

    if out and out.get('all_drawings'):
        new_coords = [[p[1], p[0]] for p in out['all_drawings'][-1]['geometry']['coordinates'][0]]
        nome_rec = st.text_input("Nome Recinto:")
        if st.button("Salva Recinto") and nome_rec:
            with conn.session as s:
                s.execute("INSERT INTO recinti (nome, coords) VALUES (:n, :c)", {"n": nome_rec, "c": json.dumps(new_coords)})
                s.commit()
            st.rerun()

st.subheader("📊 Lista Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
