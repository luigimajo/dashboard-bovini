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

# Inizializzazione stati di sessione
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False
if "temp_coords" not in st.session_state:
    st.session_state.temp_coords = None

# --- 2. LOGICA REFRESH (ANTI-TRIPLETTE + BLOCCO DISEGNO) ---
# FIX: disarmo hard del timer quando entri in edit_mode
if not st.session_state.edit_mode:
    st_autorefresh(interval=30000, key="timer_primario_30s")
else:
    # Monta un autorefresh "diverso" con interval=0 per smontare il timer già armato nel browser
    st_autorefresh(interval=0, key="timer_edit_disabled")

    st.sidebar.warning("🏗️ MODALITÀ DISEGNO: Refresh Disabilitato")
    if st.sidebar.button("🔓 Esci e annulla"):
        st.session_state.edit_mode = False
        st.session_state.temp_coords = None
        st.rerun()

ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]
conn = st.connection("postgresql", type="sql")

# --- 3. FUNZIONE CARICAMENTO DATI ---
@st.cache_data(ttl=2)
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = []
        if not df_r.empty:
            val = df_r.iloc[0]["coords"]
            coords = json.loads(val) if isinstance(val, str) else val
        return df_m, coords
    except Exception:
        return pd.DataFrame(), []

df_mandria, saved_coords = load_data()

# --- 4. COSTRUZIONE MAPPA (CON PROTEZIONE KEYERROR) ---
c_lat, c_lon = 37.9747, 13.5753

if not df_mandria.empty and "lat" in df_mandria.columns and "lon" in df_mandria.columns:
    df_valid = df_mandria.dropna(subset=["lat", "lon"])
    df_valid = df_valid[(df_valid["lat"] != 0) & (df_valid["lon"] != 0)]
    if not df_valid.empty:
        c_lat, c_lon = df_valid["lat"].mean(), df_valid["lon"].mean()

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attr="Google Satellite",
    name="Google Satellite",
    overlay=False,
    control=False,
).add_to(m)

if saved_coords:
    folium.Polygon(
        locations=saved_coords,
        color="yellow",
        weight=3,
        fill=True,
        fill_opacity=0.2,
    ).add_to(m)

if not df_mandria.empty and "lat" in df_mandria.columns:
    for _, row in df_mandria.iterrows():
        if pd.notna(row["lat"]) and row["lat"] != 0:
            color = "green" if row["stato_recinto"] == "DENTRO" else "red"
            folium.Marker(
                [row["lat"], row["lon"]],
                icon=folium.Icon(color=color, icon="info-sign"),
            ).add_to(m)

Draw(
    draw_options={"polyline": False, "rectangle": False, "circle": False, "marker": False, "polygon": True}
).add_to(m)

# --- 5. LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.sidebar.write(f"Ultimo Refresh: {ora_log}")

col_map, col_table = st.columns([3, 1])

with col_map:
    if not st.session_state.edit_mode:
        if st.button("🏗️ INIZIA DISEGNO NUOVO RECINTO"):
            st.session_state.edit_mode = True
            st.session_state.temp_coords = None
            st.rerun()

    # Render Mappa
    out = st_folium(m, width="100%", height=650, key="main_map")

    # --- CATTURA COORDINATE (robusta) ---
    # prova all_drawings, poi last_active_drawing
    drawing = None
    if out:
        if out.get("all_drawings") and isinstance(out["all_drawings"], list) and len(out["all_drawings"]) > 0:
            drawing = out["all_drawings"][-1]
        elif out.get("last_active_drawing") and isinstance(out["last_active_drawing"], dict):
            drawing = out["last_active_drawing"]

    if drawing and isinstance(drawing, dict):
        geom = drawing.get("geometry")
        if isinstance(geom, dict) and geom.get("type") == "Polygon":
            coords = geom.get("coordinates")
            # GeoJSON Polygon: [ [ [lon,lat], ... ] , ... ]
            if isinstance(coords, list) and len(coords) > 0 and isinstance(coords[0], list):
                ring = coords[0]
                st.session_state.temp_coords = [[p[1], p[0]] for p in ring if isinstance(p, list) and len(p) >= 2]

    # --- Pulsante SALVA (identico al tuo) ---
    if st.session_state.edit_mode:
        if st.session_state.temp_coords:
            st.success("📍 Poligono pronto per il salvataggio!")
            if st.button("💾 CONFERMA E SALVA DEFINITIVAMENTE"):
                with conn.session as s:
                    s.execute(
                        text(
                            "INSERT INTO recinti (id, nome, coords) "
                            "VALUES (1, 'Pascolo', :coords) "
                            "ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"
                        ),
                        {"coords": json.dumps(st.session_state.temp_coords)},
                    )
                    s.commit()

                st.session_state.edit_mode = False
                st.session_state.temp_coords = None
                st.success("Recinto salvato correttamente!")
                # time.sleep(1)  # se vuoi rimetterlo, puoi, ma non è necessario
                st.rerun()
        else:
            st.info("Disegna il recinto sulla mappa e chiudi il poligono cliccando sul primo punto.")

with col_table:
    st.subheader("⚠️ Stato")
    if not df_mandria.empty:
        # Nota: qui presumo che la colonna 'batteria' esista sempre come nel tuo codice.
        df_emergenza = df_mandria[(df_mandria["stato_recinto"] == "FUORI") | (df_mandria["batteria"] <= 20)]
        st.dataframe(df_emergenza[["nome", "batteria"]], hide_index=True)

st.divider()
st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)

# 6. RITARDO DI STABILIZZAZIONE (sconsigliato)
# time.sleep(1)
