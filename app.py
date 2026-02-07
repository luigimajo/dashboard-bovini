import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import json
import pandas as pd
import requests
from datetime import datetime

# --- CONNESSIONE DATABASE (PostgreSQL / Supabase) ---
# Usa le credenziali definite in [connections.postgresql] nel file secrets
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
        resp = requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- CARICAMENTO DATI ---
df_recinti = conn.query("SELECT * FROM recinti", ttl=0)
df_mandria = conn.query("SELECT * FROM mandria", ttl=0)

# Gestione caricamento coordinate recinto
saved_coords = []
if not df_recinti.empty:
    # Carichiamo il primo recinto disponibile come riferimento per i test
    saved_coords = json.loads(df_recinti.iloc[0]['coords'])

st.set_page_config(layout="wide", page_title="Monitoraggio Bovini")
st.title("🛰️ Monitoraggio Bovini - Satellitare")

# --- SIDEBAR: GESTIONE ---
st.sidebar.header("📋 Gestione Mandria")

with st.sidebar.expander("➕ Aggiungi Bovino"):
    n_id = st.text_input("ID Tracker (DevEUI)")
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

if not df_mandria.empty:
    with st.sidebar.expander("🗑️ Rimuovi Bovino"):
        bov_da_eliminar = st.selectbox("Seleziona:", df_mandria['nome'].tolist(), key="del_bov")
        if st.button("Elimina"):
            with conn.session as s:
                s.execute("DELETE FROM mandria WHERE nome = :nome", {"nome": bov_da_eliminar})
                s.commit()
            st.rerun()

# --- LAYOUT PRINCIPALE ---
col1, col2 = st.columns([3, 1])

with col2:
    st.subheader("⚙️ Controllo Allarmi")
    allarme_globale = st.toggle("Verifica Posizioni Attiva", value=True)
    
    st.write("---")
    st.subheader("🧪 Test Telegram")
    if st.button("Invia Messaggio di Prova"):
        risultato = invia_telegram("👋 Test connessione dalla Dashboard!")
        if risultato.get("ok"): st.success("✅ Inviato!")
        else: st.error("❌ Errore")

    st.write("---")
    st.subheader("📍 Test Movimento Manuale")
    if not df_mandria.empty:
        bov_sel = st.selectbox("Sposta:", df_mandria['nome'].tolist())
        n_lat = st.number_input("Lat", value=45.1743, format="%.6f")
        n_lon = st.number_input("Lon", value=9.2394, format="%.6f")
        
        if st.button("Aggiorna Posizione"):
            # Filtriamo il DF per trovare il bovino selezionato
            bov_row = df_mandria[df_mandria['nome'] == bov_sel].iloc[0]
            stato_vecchio = bov_row['stato_recinto']
            
            nuovo_in = is_inside(n_lat, n_lon, saved_coords)
            stato_nuovo = "DENTRO" if nuovo_in else "FUORI"
            
            if allarme_globale and stato_vecchio == "DENTRO" and stato_nuovo == "FUORI":
                invia_telegram(f"🚨 ALLARME: {bov_sel} è USCITO dal recinto!")
            
            with conn.session as s:
                s.execute(
                    "UPDATE mandria SET lat=:lat, lon=:lon, stato_recinto=:stato, ultimo_aggiornamento=NOW() WHERE nome=:nome",
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

    # Mostra tutti i recinti
    for _, r in df_recinti.iterrows():
        c_list = json.loads(r['coords'])
        folium.Polygon(locations=c_list, color="yellow", weight=5, fill=True, fill_opacity=0.2, popup=r['nome']).add_to(m)

    # Mostra i bovini
    for _, row in df_mandria.iterrows():
        color_marker = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker(
            [row['lat'], row['lon']], 
            popup=f"{row['nome']} (Bat: {row['batteria']}%)", 
            icon=folium.Icon(color=color_marker)
        ).add_to(m)

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    
    out = st_folium(m, width=700, height=500, key="main_map")

    if out and out.get('all_drawings'):
        # Prendiamo l'ultimo disegno fatto sulla mappa
        last_draw = out['all_drawings'][-1]['geometry']['coordinates'][0]
        # Invertiamo le coordinate da [lon, lat] a [lat, lon] per Folium
        fixed_poly = [[p[1], p[0]] for p in last_draw]
        
        st.write("---")
        nome_nuovo_recinto = st.text_input("Nome per questo recinto:", value="Pascolo 1")
        if st.button("💾 Salva Nuovo Recinto"):
            with conn.session as s:
                s.execute(
                    "INSERT INTO recinti (nome, coords) VALUES (:nome, :coords)",
                    {"nome": nome_nuovo_recinto, "coords": json.dumps(fixed_poly)}
                )
                s.commit()
            st.rerun()

# --- TABELLA RIASSUNTIVA ---
st.write("---")
st.subheader("📊 Stato Mandria")
if not df_mandria.empty:
    st.dataframe(df_mandria, use_container_width=True, hide_index=True)
