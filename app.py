import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import json
import pandas as pd
import requests
from sqlalchemy import text # Necessario per le query su Postgres

# --- CONNESSIONE DATABASE (Supabase via Pooler 6543) ---
conn = st.connection("postgresql", type="sql")

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
        resp = requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- LOGICA DATI (Puntando alle tue tabelle Supabase) ---
saved_coords = []
df_mandria = pd.DataFrame()

try:
    # Caricamento recinto ID 1 dalla tua tabella 'recinti'
    res_rec = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
    if not res_rec.empty:
        saved_coords = json.loads(res_rec.iloc[0]['coords'])
    
    # Caricamento mandria dalla tua tabella 'mandria'
    df_mandria = conn.query("SELECT * FROM mandria", ttl=0)
except Exception as e:
    st.sidebar.error("⚠️ Errore Database. Verifica i Secrets.")

st.set_page_config(layout="wide")
st.title("🛰️ Monitoraggio Bovini - Satellitare (Base1_Supabase)")

# --- SIDEBAR: AGGIUNGI E RIMUOVI ---
st.sidebar.header("📋 Gestione Mandria")

with st.sidebar.expander("➕ Aggiungi Bovino"):
    n_id = st.text_input("ID Tracker")
    n_nome = st.text_input("Nome/Marca")
    if st.button("Salva"):
        if n_id and n_nome:
            with conn.session as s:
                s.execute(
                    text("INSERT INTO mandria (id, nome, lat, lon, stato_recinto, batteria, allarme_attivo) "
                         "VALUES (:id, :nome, :lat, :lon, :stato, :bat, :alarm) "
                         "ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome"),
                    {"id": n_id, "nome": n_nome, "lat": 45.1743, "lon": 9.2394, "stato": "DENTRO", "bat": 100, "alarm": True}
                )
                s.commit()
            st.rerun()

# --- LAYOUT PRINCIPALE (3:1 come Base1) ---
col1, col2 = st.columns([3, 1])

with col2:
    st.subheader("🧪 Test Telegram")
    if st.button("Invia Messaggio di Prova"):
        risultato = invia_telegram("👋 Test connessione Base1_Supabase!")
        if risultato.get("ok"): st.success("✅ Inviato!")
        else: st.error("❌ Errore")

    st.write("---")
    st.subheader("📍 Test Movimento")
    if not df_mandria.empty:
        bov_sel = st.selectbox("Sposta:", df_mandria['nome'].tolist())
        n_lat = st.number_input("Lat", value=45.1743, format="%.6f")
        n_lon = st.number_input("Lon", value=9.2394, format="%.6f")
        
        if st.button("Aggiorna Posizione"):
            bov_info = df_mandria[df_mandria['nome'] == bov_sel].iloc[0]
            stato_vecchio = bov_info['stato_recinto']
            
            nuovo_in = is_inside(n_lat, n_lon, saved_coords)
            stato_nuovo = "DENTRO" if nuovo_in else "FUORI"
            
            if stato_vecchio == "DENTRO" and stato_nuovo == "FUORI":
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
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
        attr='Google Satellite', name='Google Satellite', overlay=False, control=False
    ).add_to(m)

    if saved_coords:
        folium.Polygon(locations=saved_coords, color="yellow", weight=5, fill=True, fill_opacity=0.2).add_to(m)

    for i, row in df_mandria.iterrows():
        col = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker([row['lat'], row['lon']], popup=row['nome'], icon=folium.Icon(color=col)).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    out = st_folium(m, width=800, height=550, key="main_map")

    if out and out.get('all_drawings'):
        new_poly = out['all_drawings'][-1]['geometry']['coordinates'][0]
        fixed_poly = [[p[1], p[0]] for p in new_poly]
        if st.button("Salva Recinto"):
            with conn.session as s:
                s.execute(
                    text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Recinto 1', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"),
                    {"coords": json.dumps(fixed_poly)}
                )
                s.commit()
            st.rerun()

st.write("---")
st.subheader(f"📊 Lista Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
