import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import json
import pandas as pd
import requests
from sqlalchemy import text

# --- CONNESSIONE DATABASE ---
conn = st.connection("postgresql", type="sql")

# --- FUNZIONI ---
def is_inside(lat, lon, polygon_coords):
    if not polygon_coords or len(polygon_coords) < 3: return True
    poly = Polygon(polygon_coords)
    return poly.contains(Point(lat, lon))

def invia_telegram(msg):
    try:
        # Pulizia totale del token
        token = str(st.secrets["TELEGRAM_TOKEN"]).strip()
        chat_id = str(st.secrets["TELEGRAM_CHAT_ID"]).strip()
        # URL costruito in modo esplicito per evitare errori di parsing
        base_url = "https://api.telegram.org"
        full_url = f"{base_url}{token}/sendMessage"
        resp = requests.post(full_url, data={"chat_id": chat_id, "text": msg}, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- LOGICA DATI (Con protezione per la mappa) ---
saved_coords = []
df_mandria = pd.DataFrame(columns=['id', 'nome', 'lat', 'lon', 'stato_recinto', 'batteria'])

try:
    # Cerchiamo di caricare i dati, ma non blocchiamo l'app se fallisce
    res_recinto = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
    if not res_recinto.empty:
        saved_coords = json.loads(res_recinto.iloc[0]['coords'])
    
    res_mandria = conn.query("SELECT * FROM mandria", ttl=0)
    if not res_mandria.empty:
        df_mandria = res_mandria
except Exception as e:
    st.sidebar.error(f"Connessione DB fallita: IPv6 non supportato o credenziali errate.")

st.set_page_config(layout="wide")
st.title("🛰️ Monitoraggio Bovini - Satellitare")

# --- SIDEBAR ---
st.sidebar.header("📋 Gestione Mandria")
with st.sidebar.expander("➕ Aggiungi Bovino"):
    n_id = st.text_input("ID Tracker")
    n_nome = st.text_input("Nome/Marca")
    if st.button("Salva"):
        if n_id and n_nome:
            with conn.session as s:
                s.execute(
                    text("INSERT INTO mandria (id, nome, lat, lon, stato_recinto, batteria) "
                         "VALUES (:id, :nome, :lat, :lon, :stato, :bat) "
                         "ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome"),
                    {"id": n_id, "nome": n_nome, "lat": 45.1743, "lon": 9.2394, "stato": "DENTRO", "bat": 100}
                )
                s.commit()
            st.rerun()

# --- LAYOUT PRINCIPALE ---
col1, col2 = st.columns([3, 1])

with col2:
    allarmi_attivi = st.toggle("🔔 Verifica Posizioni Attiva", value=True)
    st.write("---")
    st.subheader("🧪 Test Telegram")
    if st.button("Invia Messaggio di Prova"):
        risultato = invia_telegram("👋 Test connessione dalla Dashboard!")
        if risultato.get("ok"): st.success("✅ Inviato!")
        else: st.error(f"❌ Errore API: {risultato}")

with col1:
    # MAPPA ORIGINALE - Ora visibile anche se il DB fallisce
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    folium.TileLayer(
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
        attr='Google Satellite', name='Google Satellite', overlay=False, control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", weight=5, fill=True, fill_opacity=0.2).add_to(m)

    for i, row in df_mandria.iterrows():
        col_m = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], popup=row['nome'], icon=folium.Icon(color=col_m)).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    out = st_folium(m, width=800, height=550, key="main_map")

    if out and out.get('all_drawings'):
        new_poly_raw = out['all_drawings'][-1]['geometry']['coordinates'][0]
        fixed_poly = [[p[1], p[0]] for p in new_poly_raw]
        if st.button("Salva Recinto"):
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Principale', :coords) "
                               "ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"),
                          {"coords": json.dumps(fixed_poly)})
                s.commit()
            st.rerun()

st.write("---")
st.subheader("📊 Lista Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
