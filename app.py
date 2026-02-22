import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")
st_autorefresh(interval=30000, key="datarefresh")
conn = st.connection("postgresql", type="sql")

# --- CARICAMENTO DATI ---
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_g = conn.query("SELECT * FROM gateway ORDER BY ultima_attivita DESC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = json.loads(df_r.iloc[0]['coords']) if not df_r.empty else []
        return df_m, df_g, coords
    except Exception as e:
        st.error(f"Errore database: {e}")
        return pd.DataFrame(), pd.DataFrame(), []

df_mandria, df_gateways, saved_coords = load_data()

# --- CALCOLO CENTRO MAPPA (Risolve NameError) ---
df_valid = df_mandria.dropna(subset=['lat', 'lon'])
df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]

if not df_valid.empty:
    c_lat, c_lon = df_valid['lat'].mean(), df_valid['lon'].mean()
else:
    c_lat, c_lon = 37.9747, 13.5753 # Coordinate di default

# --- LOGICA MAPPA ---
# Usiamo tiles=None e aggiungiamo Google Satellite manualmente
m = folium.Map(location=[c_lat, c_lon], zoom_start=18)

folium.TileLayer(
    tiles='https://mt1.google.com{x}&y={y}&z={z}',
    attr='Google Satellite',
    name='Google Satellite',
    overlay=False,
    control=False
).add_to(m)

# 1. DISEGNO RECINTO ESISTENTE
if saved_coords:
    folium.Polygon(
        locations=saved_coords, 
        color="yellow", 
        weight=3, 
        fill=True, 
        fill_opacity=0.2
    ).add_to(m)

# 2. STRUMENTO DISEGNO (Versione stabile senza FeatureGroup esterno)
Draw(
    export=False,
    position='topleft',
    draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True},
    edit_options={'edit': True, 'remove': True} 
).add_to(m)

# 3. MARKER BOVINI
for _, row in df_mandria.iterrows():
    if pd.notna(row['lat']) and row['lat'] != 0:
        color = 'green' if row['stato_recinto'] == 'DENTRO' else 'red'
        folium.Marker(
            [row['lat'], row['lon']],
            popup=f"<b>{row['nome']}</b><br>Batt: {row['batteria']}%",
            icon=folium.Icon(color=color, icon='info-sign')
        ).add_to(m)

# --- LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    # Key fissa per evitare il reset del disegno durante il refresh
    out = st_folium(m, width=None, height=650, key="main_map", use_container_width=True)
    
    # SALVATAGGIO RECINTO
    if out and out.get('all_drawings'):
        # Estraiamo le coordinate dell'ultimo poligono disegnato
        last_poly = out['all_drawings'][-1]['geometry']['coordinates'][0]
        # Invertiamo da [Lon, Lat] a [Lat, Lon] per il nostro database
        new_coords = [[p[1], p[0]] for p in last_poly]
        
        if st.button("💾 SALVA NUOVO RECINTO"):
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), 
                          {"coords": json.dumps(new_coords)})
                s.commit()
            st.success("Recinto salvato! La dashboard si aggiornerà.")
            st.rerun()

with col_table:
    st.subheader("⚠️ Emergenze")
    df_err = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
    if not df_err.empty:
        st.error(f"Criticità: {len(df_err)}")
        st.dataframe(df_err[['nome', 'stato_recinto', 'batteria']], hide_index=True)
    else:
        st.success("Tutto OK")
    
    st.divider()
    with st.expander("🔍 Tutti i capi"):
        st.dataframe(df_mandria[['nome', 'stato_recinto', 'batteria']], hide_index=True)

st.write("---")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
