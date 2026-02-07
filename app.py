import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
import requests

# 1. Configurazione Pagina (Caricamento immediato)
st.set_page_config(layout="wide")
st.title("🛰️ Monitoraggio Bovini - Satellitare")

# 2. Funzioni
def invia_telegram(msg):
    try:
        token = str(st.secrets["TELEGRAM_TOKEN"]).strip()
        chat_id = str(st.secrets["TELEGRAM_CHAT_ID"]).strip()
        url = f"https://api.telegram.org{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# 3. Caricamento Dati (Con reset se i dati sono corrotti)
saved_coords = []
df_mandria = pd.DataFrame(columns=['id', 'nome', 'lat', 'lon', 'stato_recinto', 'batteria'])

try:
    conn = st.connection("postgresql", type="sql")
    res_rec = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
    if not res_rec.empty:
        # Carichiamo le coordinate con protezione
        raw_coords = json.loads(res_rec.iloc[0]['coords'])
        # Verifichiamo che siano nel formato corretto [lat, lon]
        if isinstance(raw_coords, list) and len(raw_coords) > 0:
            saved_coords = raw_coords
    
    res_man = conn.query("SELECT * FROM mandria", ttl=0)
    if not res_man.empty:
        df_mandria = res_man
except Exception:
    st.sidebar.warning("⚠️ Database in fase di collegamento (IPv4 Pooler)...")

# 4. Layout
col1, col2 = st.columns([3, 1])

with col1:
    # CREAZIONE MAPPA FORZATA
    m = folium.Map(location=[45.1743, 9.2394], zoom_start=16)
    
    # Layer Satellitare (Tua versione base stabile)
    folium.TileLayer(
        tiles='https://mt1.google.com{x}&y={y}&z={z}',
        attr='Google Satellite', name='Google Satellite', overlay=False, control=False
    ).add_to(m)

    # Disegna il recinto solo se le coordinate sono valide
    if saved_coords:
        try:
            folium.Polygon(locations=saved_coords, color="yellow", weight=5, fill=True, fill_opacity=0.2).add_to(m)
        except:
            pass

    # Disegna i bovini solo se il DF non è vuoto
    if not df_mandria.empty:
        for i, row in df_mandria.iterrows():
            try:
                col_m = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
                folium.Marker([row['lat'], row['lon']], popup=row['nome'], icon=folium.Icon(color=col_m)).add_to(m)
            except:
                pass

    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    
    # Visualizzazione Mappa (Se fallisce, mostra l'errore specifico)
    try:
        st_folium(m, width=800, height=550, key="main_map")
    except Exception as e:
        st.error(f"Errore caricamento mappa: {e}")

with col2:
    st.subheader("🧪 Test Telegram")
    if st.button("Invia Messaggio"):
        ris = invia_telegram("👋 Test dal nuovo sistema!")
        if ris.get("ok"): st.success("✅ Inviato!")
        else: st.error(f"❌ Errore: {ris}")
