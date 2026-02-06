import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from shapely.geometry import Point, Polygon
import json
import pandas as pd
import requests

# --- DATABASE (Supabase) ---
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

# --- LOGICA DATI ---
try:
    df_recinto = conn.query("SELECT coords FROM recinto WHERE id = 1", ttl=0)
    saved_coords = json.loads(df_recinto.iloc[0]['coords']) if not df_recinto.empty else []
except Exception:
    saved_coords = []

try:
    df_mandria = conn.query("SELECT * FROM mandria", ttl=0)
except Exception:
    df_mandria = pd.DataFrame(columns=['id', 'nome', 'lat', 'lon', 'stato_recinto', 'batteria'])

st.set_page_config(layout="wide")
st.title("🛰️ Monitoraggio Bovini - Satellitare")

# --- SIDEBAR: AGGIUNGI E RIMUOVI ---
st.sidebar.header("📋 Gestione Mandria")

with st.sidebar.expander("➕ Aggiungi Bovino"):
    n_id = st.text_input("ID Tracker")
    n_nome = st.text_input("Nome/Marca")
    if st.button("Salva"):
        if n_id and n_nome:
            with conn.session as s:
                s.execute(
                    "INSERT INTO mandria (id, nome, lat, lon, stato_recinto, batteria) VALUES (:id, :nome, :lat, :lon, :stato, :bat) ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome",
                    {"id": n_id, "nome": n_nome, "lat": 45.1743, "lon": 9.2394, "stato": "DENTRO", "bat": 100}
                )
                s.commit()
            st.rerun()

if not df_mandria.empty:
    with st.sidebar.expander("🗑️ Rimuovi Bovino"):
        bov_da_eliminar = st.selectbox("Seleziona:", df_mandria['nome'].tolist(), key="del_bov")
        if st.button("Elimina"):
            with conn.session as s:
                s.execute("DELETE FROM mandria WHERE nome=:nome", {"nome": bov_da_eliminar})
                s.commit()
            st.rerun()

# --- LAYOUT PRINCIPALE ---
col1, col2 = st.columns([3, 1])

with col2:
    # --- INTERRUTTORE ALLARMI ---
    st.subheader("⚙️ Controllo")
    allarmi_attivi = st.toggle("Verifica Posizioni Attiva", value=True)

    st.write("---")
    st.subheader("🧪 Test Telegram")
    if st.button("Invia Messaggio di Prova"):
        risultato = invia_telegram("👋 Test connessione dalla Dashboard!")
        if risultato.get("ok"): st.success("✅ Inviato!")
        else: st.error("❌ Errore")

    st.write("---")
    st.subheader("📍 Test Movimento")
    if not df_mandria.empty:
        bov_sel = st.selectbox("Sposta:", df_mandria['nome'].tolist())
        n_lat = st.number_input("Lat", value=45.1743, format="%.6f")
        n_lon = st.number_input("Lon", value=9.2394, format="%.6f")
        
        if st.button("Aggiorna Posizione"):
            res_stato = df_mandria[df_mandria['nome'] == bov_sel]['stato_recinto'].values
            stato_vecchio = res_stato[0] if len(res_stato) > 0 else "DENTRO"
            
            nuovo_in = is_inside(n_lat, n_lon, saved_coords)
            stato_nuovo = "DENTRO" if nuovo_in else "FUORI"
            
            if allarmi_attivi and stato_vecchio == "DENTRO" and stato_nuovo == "FUORI":
                invia_telegram(f"🚨 ALLARME: {bov_sel} è USCITO!")
            
            with conn.session as s:
                s.execute(
                    "UPDATE mandria SET lat=:lat, lon=:lon, stato_recinto=:stato WHERE nome=:nome",
                    {"lat": n_lat, "lon": n_lon, "stato": stato_nuovo, "nome": bov_sel}
                )
                s.commit()
            st.rerun()

with col1:
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    # SATELLITE (Come originale)
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
        new_poly_raw = out['all_drawings'][-1]['geometry']['coordinates'][0]
        fixed_poly = [[p[1], p[0]] for p in new_poly_raw]
        if st.button("Salva Recinto"):
            with conn.session as s:
                s.execute(
                    "INSERT INTO recinto (id, coords) VALUES (1, :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords",
                    {"coords": json.dumps(fixed_poly)}
                )
                s.commit()
            st.rerun()

# --- LISTA BOVINI ---
st.write("---")
st.subheader(f"📊 Lista Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
