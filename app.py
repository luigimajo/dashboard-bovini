import streamlit as st
from streamlit_autorefresh import st_autorefresh
import time

# --- 1. REFRESH PRIORITARIO (Eseguito prima di tutto) ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

if "lock_refresh" not in st.session_state:
    st.session_state.lock_refresh = False

# Il timer viene renderizzato subito in un'area dedicata
refresh_area = st.empty()
with refresh_area:
    if not st.session_state.lock_refresh:
        # Key fissa per stabilità totale
        st_autorefresh(interval=30000, key="timer_primario_stabile")
    else:
        st.sidebar.warning("⚠️ REFRESH SOSPESO")

# --- 2. IMPORT LIBRERIE PESANTI (Dopo il timer) ---
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text

# --- 3. CARICAMENTO DATI OTTIMIZZATO ---
conn = st.connection("postgresql", type="sql")

@st.cache_data(ttl=2) # Cache brevissima per non bloccare il flusso dello script
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = []
        if not df_r.empty:
            val = df_r.iloc[0]['coords']
            coords = json.loads(val) if isinstance(val, str) else val
        return df_m, coords
    except:
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 4. MAPPA E LAYOUT ---
# (Qui il tuo codice della mappa rimane identico)
c_lat, c_lon = 37.9747, 13.5753
m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# TUO LAYER ORIGINALE RIPRISTINATO
folium.TileLayer(
    tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
    attr='Google Satellite',
    name='Google Satellite',
    overlay=False,
    control=False
).add_to(m)


if saved_coords:
    folium.Polygon(locations=saved_coords, color="yellow", weight=3, fill=True, fill_opacity=0.2).add_to(m)

for _, row in df_mandria.iterrows():
    if pd.notna(row['lat']) and row['lat'] != 0:
        color = 'green' if row['stato_recinto'] == 'DENTRO' else 'red'
        folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color=color)).add_to(m)

Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)

st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    # Gestione Blocco Disegno
    if not st.session_state.lock_refresh:
        if st.button("🏗️ INIZIA DISEGNO (Blocca Refresh)"):
            st.session_state.lock_refresh = True
            st.rerun()
    else:
        if st.button("🔓 ANNULLA E SBLOCCA"):
            st.session_state.lock_refresh = False
            st.rerun()

    out = st_folium(m, width="100%", height=600, key="mappa_unica")
    
    if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
        if st.button("💾 SALVA NUOVO RECINTO"):
            raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
            new_poly = [[p[1], p[0]] for p in raw_coords]
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(new_poly)})
                s.commit()
            st.session_state.lock_refresh = False
            st.success("Salvato!")
            st.rerun()

with col_table:
    st.subheader("⚠️ Stato")
    st.dataframe(df_mandria[['nome', 'stato_recinto']], hide_index=True)
