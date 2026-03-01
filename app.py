import streamlit as st
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import time

import leafmap.foliumap as leafmap

# --- CONFIG ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24 (LEAFMAP DRAW)")

# --- SESSION ---
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False
if "temp_coords" not in st.session_state:
    st.session_state.temp_coords = None

# --- REFRESH ---
if not st.session_state.edit_mode:
    st_autorefresh(interval=30000, key="timer_view_30s")
else:
    st_autorefresh(interval=0, key="timer_edit_disabled")
    st.sidebar.warning("🏗️ MODALITÀ DISEGNO: Refresh Disabilitato")
    if st.sidebar.button("🔓 Esci e annulla"):
        st.session_state.edit_mode = False
        st.session_state.temp_coords = None
        st.rerun()

ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]
conn = st.connection("postgresql", type="sql")

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

# --- SIDEBAR ---
with st.sidebar:
    st.header("📡 STATO RETE LORA")
    st.write(f"Ultimo Refresh: **{ora_log}**")

# --- CENTER ---
c_lat, c_lon = 37.9747, 13.5753
if not df_mandria.empty and "lat" in df_mandria.columns and "lon" in df_mandria.columns:
    df_v = df_mandria.dropna(subset=["lat", "lon"]).query("lat != 0 and lon != 0")
    if not df_v.empty:
        c_lat, c_lon = df_v["lat"].mean(), df_v["lon"].mean()

st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    if not st.session_state.edit_mode:
        if st.button("🏗️ INIZIA DISEGNO NUOVO RECINTO"):
            st.session_state.edit_mode = True
            st.session_state.temp_coords = None
            st.rerun()

    # MAP
    m = leafmap.Map(center=(c_lat, c_lon), zoom=18)

    # Google Satellite
    m.add_tile_layer(
        url="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        name="Google Satellite",
        attribution="Google",
    )

    # View overlays
    if not st.session_state.edit_mode:
        if saved_coords:
            m.add_polygon(saved_coords, layer_name="Recinto", fill_opacity=0.2)

        if not df_mandria.empty and "lat" in df_mandria.columns and "lon" in df_mandria.columns:
            for _, row in df_mandria.iterrows():
                if pd.notna(row["lat"]) and row["lat"] != 0:
                    m.add_marker(location=(row["lat"], row["lon"]), popup=str(row.get("nome", "")))

    # Draw only in edit mode
    if st.session_state.edit_mode:
        m.add_draw_control(
            export=True,
            draw_polygon=True,
            draw_polyline=False,
            draw_rectangle=False,
            draw_circle=False,
            draw_circlemarker=False,
            draw_marker=False,
        )

    out = m.to_streamlit(height=650)

    # DEBUG: mostra output completo (solo in edit, così è leggibile)
    with st.expander("🧪 DEBUG leafmap output"):
        st.write(out)

    # Estrai GeoJSON: prendiamo l'ultima feature Polygon trovata ovunque dentro out
    def find_last_polygon(obj):
        found = None

        def walk(x):
            nonlocal found
            if isinstance(x, dict):
                # Feature
                if x.get("type") == "Feature" and isinstance(x.get("geometry"), dict):
                    g = x["geometry"]
                    if g.get("type") == "Polygon" and isinstance(g.get("coordinates"), list):
                        found = x
                # FeatureCollection
                if x.get("type") == "FeatureCollection" and isinstance(x.get("features"), list):
                    for f in x["features"]:
                        walk(f)
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for it in x:
                    walk(it)

        walk(obj)
        return found

    if st.session_state.edit_mode and out is not None:
        feat = find_last_polygon(out)
        if feat:
            coords = feat["geometry"]["coordinates"]  # [ [ [lon,lat], ... ] ]
            ring = coords[0]
            st.session_state.temp_coords = [[p[1], p[0]] for p in ring if isinstance(p, list) and len(p) >= 2]

    # Save UI (identico testo)
    if st.session_state.edit_mode:
        if st.session_state.temp_coords:
            st.success(f"📍 Poligono rilevato ({len(st.session_state.temp_coords)} punti).")
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
                st.success("✅ Recinto salvato!")
                st.session_state.edit_mode = False
                st.session_state.temp_coords = None
                time.sleep(1)
                st.rerun()
        else:
            st.info("Disegna sulla mappa e chiudi il poligono cliccando sul primo punto.")

with col_table:
    st.subheader("⚠️ Stato")
    if not df_mandria.empty:
        cols = ["nome"]
        if "batteria" in df_mandria.columns:
            df_emergenza = df_mandria[(df_mandria["stato_recinto"] == "FUORI") | (df_mandria["batteria"] <= 20)].copy()
            cols = ["nome", "batteria"]
        else:
            df_emergenza = df_mandria[(df_mandria["stato_recinto"] == "FUORI")].copy()
        st.dataframe(df_emergenza[cols], hide_index=True)

st.divider()
st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
