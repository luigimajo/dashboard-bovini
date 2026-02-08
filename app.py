import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import json
import pandas as pd
import requests
from sqlalchemy import text
import paho.mqtt.client as mqtt
import threading
from streamlit_autorefresh import st_autorefresh

# --- CONFIGURAZIONE ---
st.set_page_config(layout="wide")
st_autorefresh(interval=30000, key="datarefresh")
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
        # URL CORRETTO CON /bot
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- BRIDGE MQTT CON ALLARME AUTOMATICO ---
def avvia_ascolto_ttn():
    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            dev_id = payload['end_device_ids']['device_id']
            decoded = payload['uplink_message'].get('decoded_payload', {})
            
            lat, lon = decoded.get('latitude'), decoded.get('longitude')
            bat = decoded.get('battery_percent', 100)

            if lat and lon:
                # 1. Recupera stato attuale e recinto per l'allarme
                with conn.session as s:
                    # Carica coordinate recinto
                    res_rec = s.execute(text("SELECT coords FROM recinti WHERE id = 1")).fetchone()
                    coords_rec = json.loads(res_rec[0]) if res_rec else []
                    
                    # Carica stato precedente bovino
                    res_bov = s.execute(text("SELECT nome, stato_recinto FROM mandria WHERE id = :id"), {"id": dev_id}).fetchone()
                    
                    if res_bov and coords_rec:
                        nome_bov, stato_vecchio = res_bov
                        
                        # 2. Controllo Geofencing
                        nuovo_in = is_inside(lat, lon, coords_rec)
                        stato_nuovo = "DENTRO" if nuovo_in else "FUORI"
                        
                        # 3. Invia Telegram se è appena uscito
                        if stato_vecchio == "DENTRO" and stato_nuovo == "FUORI":
                            invia_telegram(f"🚨 ALLARME AUTOMATICO: {nome_bov} ({dev_id}) è USCITO dal recinto!")

                        # 4. Aggiorna DB
                        s.execute(
                            text("UPDATE mandria SET lat=:lat, lon=:lon, batteria=:bat, stato_recinto=:stato, ultimo_aggiornamento=NOW() WHERE id=:id"),
                            {"lat": lat, "lon": lon, "bat": bat, "stato": stato_nuovo, "id": dev_id}
                        )
                        s.commit()
        except Exception: pass

    try:
        client = mqtt.Client()
        user_ttn = f"{st.secrets['TTN_APP_ID']}@ttn"
        client.username_pw_set(user_ttn, st.secrets["TTN_API_KEY"])
        client.on_message = on_message
        client.connect(st.secrets["TTN_MQTT_HOST"], int(st.secrets["TTN_MQTT_PORT"]))
        client.subscribe("#")
        client.loop_forever()
    except Exception: pass

if 'mqtt_started' not in st.session_state:
    threading.Thread(target=avvia_ascolto_ttn, daemon=True).start()
    st.session_state['mqtt_started'] = True

# --- LOGICA UI (Query per visualizzazione) ---
try:
    df_rec = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
    saved_coords = json.loads(df_rec.iloc[0]['coords']) if not df_rec.empty else []
    df_mandria = conn.query("SELECT * FROM mandria", ttl=0)
except Exception as e:
    st.error(f"Errore caricamento: {e}")
    df_mandria, saved_coords = pd.DataFrame(), []

# --- INTERFACCIA (Mappa e Tabella) ---
st.title("🛰️ Monitoraggio Bovini - Satellitare (base1 supabase2)")

col1, col2 = st.columns([3, 1])
with col1:
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    folium.TileLayer(
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
        attr='Google Satellite', name='Google Satellite', overlay=False, control=False
    ).add_to(m)
    
    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", weight=5, fill=True, fill_opacity=0.2).add_to(m)
    
    for _, row in df_mandria.iterrows():
        col_m = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], popup=row['nome'], icon=folium.Icon(color=col_m)).add_to(m)
    
    st_folium(m, width=800, height=550, key="main_map")

with col2:
    st.subheader("📊 Mandria")
    st.dataframe(df_mandria[['nome', 'stato_recinto', 'batteria']], hide_index=True)
    if st.button("Invia Test Telegram"):
        invia_telegram("👋 Test manuale riuscito!")

    
    st.write("---")
    st.subheader("📍 Test Movimento")
    if not df_mandria.empty:
        bov_sel = st.selectbox("Sposta:", df_mandria['nome'].tolist())
        n_lat = st.number_input("Lat", value=45.1743, format="%.6f")
        n_lon = st.number_input("Lon", value=9.2394, format="%.6f")
        
        if st.button("Aggiorna Posizione"):
            bov_info = df_mandria[df_mandria['nome'] == bov_sel].iloc[0]
            nuovo_in = is_inside(n_lat, n_lon, saved_coords)
            stato_nuovo = "DENTRO" if nuovo_in else "FUORI"
            
            if bov_info['stato_recinto'] == "DENTRO" and stato_nuovo == "FUORI":
                invia_telegram(f"🚨 ALLARME: {bov_sel} è USCITO!")
            
            with conn.session as s:
                s.execute(
                    text("UPDATE mandria SET lat=:lat, lon=:lon, stato_recinto=:stato, ultimo_aggiornamento=NOW() WHERE nome=:nome"),
                    {"lat": n_lat, "lon": n_lon, "stato": stato_nuovo, "nome": bov_sel}
                )
                s.commit()
            st.rerun()

with col1:
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    folium.TileLayer(
   #    tiles='https://mt1.google.com{x}&y={y}&z={z}',
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',

        attr='Google Satellite', name='Google Satellite', overlay=False, control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", weight=5, fill=True, fill_opacity=0.2).add_to(m)

    for i, row in df_mandria.iterrows():
        col_m = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], popup=f"{row['nome']} ({row['batteria']}%)", icon=folium.Icon(color=col_m)).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    out = st_folium(m, width=800, height=550, key="main_map")

    if out and out.get('all_drawings'):
        new_poly = out['all_drawings'][-1]['geometry']['coordinates'][0]
        fixed_poly = [[p[1], p[0]] for p in new_poly]
        if st.button("Salva Recinto"):
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Recinto 1', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(fixed_poly)})
                s.commit()
            st.rerun()

st.write("---")
st.subheader("📊 Stato Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
