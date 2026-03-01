import streamlit as st
import folium
import streamlit_folium
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

# --- Debug versioni (FONDAMENTALE SU STREAMLIT CLOUD) ---
with st.sidebar:
    st.caption("🔧 Versioni runtime")
    st.write("streamlit:", st.__version__)
    st.write("streamlit-folium:", getattr(streamlit_folium, "__version__", "unknown"))
    st.write("folium:", getattr(folium, "__version__", "unknown"))

# Session state
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False
if "temp_coords" not in st.session_state:
    st.session_state.temp_coords = None

# --- 2. REFRESH ---
if not st.session_state.edit_mode:
    st_autorefresh(interval=30000, key="timer_primario_30s")
else:
    # disarmo hard del timer nel browser
    st_autorefresh(interval=0, key="timer_edit_disabled")
    st.sidebar.warning("🏗️ MODALITÀ DISEGNO: Refresh Disabilitato")
    if st.sidebar.button("🔓 Esci e annulla"):
        st.session_state.edit_mode = False
        st.session_state.temp_coords = None
        st.rerun()

ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]
conn = st.connection("postgresql", type="sql")

# --- 3. CARICAMENTO DATI ---
@st.cache_data(ttl=2)
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_g = conn.query("SELECT * FROM gateway ORDER BY ultima_attivita DESC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = []
        if not df_r.empty:
            val = df_r.iloc[0]["coords"]
            coords = json.loads(val) if isinstance(val, str) else val
        return df_m, df_g, coords
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), []

df_mandria, df_gateways, saved_coords = load_data()

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("📡 STATO RETE LORA")
    st.write(f"Ultimo Refresh: **{ora_log}**")

    if not df_gateways.empty:
        for _, g in df_gateways.iterrows():
            status_color = "#28a745" if g["stato"] == "ONLINE" else "#dc3545"
            icon = "✅" if g["stato"] == "ONLINE" else "❌"
            st.markdown(
                f"""
                <div style="border-left: 5px solid {status_color}; padding: 10px; background-color: rgba(255,255,255,0.05); border-radius: 5px; margin-bottom: 10px;">
                    <b style="font-size: 14px;">{icon} {g['nome']}</b><br>
                    <small>Stato: {g['stato']}</small>
                </div>
                """,
                unsafe_allow_html=True,
            )

# --- 5. MAPPA ---
c_lat, c_lon = 37.9747, 13.5753
if not df_mandria.empty and "lat" in df_mandria.columns and "lon" in df_mandria.columns:
    df_v = df_mandria.dropna(subset=["lat", "lon"]).query("lat != 0 and lon != 0")
    if not df_v.empty:
        c_lat, c_lon = df_v["lat"].mean(), df_v["lon"].mean()

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# ✅ Tile URL corretto
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attr="Google Satellite",
    name="Google Satellite",
    overlay=False,
    control=False,
).add_to(m)

if saved_coords:
    folium.Polygon(locations=saved_coords, color="yellow", weight=3, fill=True, fill_opacity=0.2).add_to(m)

for _, row in df_mandria.iterrows():
    if pd.notna(row.get("lat")) and row["lat"] != 0:
        color = "green" if row.get("stato_recinto") == "DENTRO" else "red"
        folium.Marker([row["lat"], row["lon"]], icon=folium.Icon(color=color, icon="info-sign")).add_to(m)

Draw(draw_options={"polyline": False, "rectangle": False, "circle": False, "marker": False, "polygon": True}).add_to(m)

# --- 6. LAYOUT ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    if not st.session_state.edit_mode:
        if st.button("🏗️ INIZIA DISEGNO NUOVO RECINTO"):
            st.session_state.edit_mode = True
            st.session_state.temp_coords = None
            st.rerun()

    out = st_folium(
        m,
        use_container_width=True,
        height=650,
        key="main_map",
        returned_objects=["all_drawings", "last_active_drawing", "selected_layers", "bounds", "zoom"],
    )

    # DEBUG: mostra cosa arriva davvero
    with st.expander("🧪 DEBUG st_folium (draw)"):
        st.write("all_drawings:", None if not out else out.get("all_drawings"))
        st.write("last_active_drawing:", None if not out else out.get("last_active_drawing"))
        st.write("selected_layers:", None if not out else out.get("selected_layers"))

    # Estrazione disegno (all_drawings -> last_active_drawing)
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
            if isinstance(coords, list) and len(coords) > 0 and isinstance(coords[0], list):
                ring = coords[0]
                st.session_state.temp_coords = [[p[1], p[0]] for p in ring if isinstance(p, list) and len(p) >= 2]

    # Pulsante SALVA (identico)
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
        if "batteria" in df_mandria.columns:
            df_emergenza = df_mandria[(df_mandria["stato_recinto"] == "FUORI") | (df_mandria["batteria"] <= 20)]
            st.dataframe(df_emergenza[["nome", "batteria"]], hide_index=True)
        else:
            df_emergenza = df_mandria[(df_mandria["stato_recinto"] == "FUORI")]
            st.dataframe(df_emergenza[["nome"]], hide_index=True)
    else:
        st.info("Nessun dato mandria disponibile.")

st.divider()
st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
