import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import time

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# Inizializzazione stato blocco refresh
if "lock_manuale" not in st.session_state:
    st.session_state.lock_manuale = False

# --- 2. LOGICA REFRESH STABILIZZATA ---
if not st.session_state.lock_manuale:
    st_autorefresh(interval=30000, key="datarefresh_stabile")
else:
    st.sidebar.warning("⚠️ REFRESH BLOCCATO: Modifica recinto in corso")
    if st.sidebar.button("🔓 SBLOCCA E ANNULLA"):
        st.session_state.lock_manuale = False
        st.rerun()

ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]
conn = st.connection("postgresql", type="sql")

# --- 3. CARICAMENTO DATI ---
@st.cache_data(ttl=10)
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = json.loads(df_r.iloc[0]['coords']) if not df_r.empty else []
        return df_m, coords
    except Exception as e:
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 4. COSTRUZIONE MAPPA ---
df_valid = df_mandria.dropna(subset=['lat', 'lon'])
df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]
c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# --- BLOCCO SATELLITE GOOGLE RICHIESTO (ESATTO) ---
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
        folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color=color, icon='info-sign')).add_to(m)

Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)

# --- 5. LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.sidebar.write(f"Ultimo Refresh: **{ora_log}**")

col_map, col_table = st.columns([3, 1])

# --- (Parti precedenti invariate: Configurazione, Blocco Refresh, Dati, Mappa) ---

with col_map:
    # PULSANTE DI SICUREZZA (Blocca il timer dei 30s)
    if not st.session_state.lock_manuale:
        if st.button("🏗️ INIZIA A DISEGNARE (Blocca Refresh)"):
            st.session_state.lock_manuale = True
            st.rerun()
    
    # Visualizzazione Mappa (con Satellite Google bloccato nel blocco 'm')
    out = st_folium(m, width="100%", height=650, key="main_map")
    
    # GESTIONE SALVATAGGIO PERSISTENTE
    if st.session_state.lock_manuale:
        st.info("💡 Suggerimento: chiudi il poligono cliccando sul primo punto per abilitare il salvataggio.")
        
        # Il tasto è ora sempre presente durante la fase di modifica
        if st.button("💾 CONFERMA E SALVA NUOVO RECINTO"):
            if out and out.get('all_drawings') and len(out['all_drawings']) > 0:
                # Recupero coordinate GeoJSON [Lon, Lat]
                raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
                # Conversione in formato Folium/Database [Lat, Lon]
                new_poly = [[p[1], p[0]] for p in raw_coords]
                
                with conn.session as s:
                    s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(new_poly)})
                    s.commit()
                
                st.success("✅ Recinto salvato! Il monitoraggio ripartirà tra poco.")
                st.session_state.lock_manuale = False
                time.sleep(2)
                st.rerun()
            else:
                st.error("⚠️ Nessun poligono rilevato. Assicurati di aver chiuso il disegno sulla mappa.")

# --- (Resto del codice: Tabelle, Storico, Sleep finale) ---

with col_table:
    st.subheader("⚠️ Emergenze")
    df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
    st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)

st.write("---")
st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
