import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh
from datetime import datetime

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# --- 1b. SESSION STATE ---
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False
if "temp_coords" not in st.session_state:
    st.session_state.temp_coords = None

# --- 2. REFRESH ROBUSTO: DISARMA TIMER IN EDIT MODE ---
if st.session_state.edit_mode:
    # Disarma hard il timer già "armato" nel browser
    st_autorefresh(interval=0, key="timer_edit_disabled")
    st.sidebar.warning("🏗️ MODALITÀ DISEGNO: Refresh Disabilitato")
    if st.sidebar.button("🔓 Esci e annulla"):
        st.session_state.edit_mode = False
        st.session_state.temp_coords = None
        st.rerun()
else:
    st_autorefresh(interval=30000, key="timer_view_30s")

ora_log = datetime.now().strftime("%H:%M:%S.%f")[:-3]
conn = st.connection("postgresql", type="sql")

# --- 3. FUNZIONE CARICAMENTO DATI ---
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

# --- 4. SIDEBAR: GESTIONE INFRASTRUTTURA E MANDRIA ---
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

    with st.expander("➕ Configura Nuovo Gateway"):
        g_id = st.text_input("ID Gateway (TTN)")
        g_nome = st.text_input("Nome Località")
        if st.button("Registra Gateway"):
            if g_id and g_nome:
                with conn.session as s:
                    s.execute(
                        text("INSERT INTO gateway (id, nome, stato) VALUES (:id, :nome, 'ONLINE')"),
                        {"id": g_id, "nome": g_nome},
                    )
                    s.commit()
                st.rerun()

    st.divider()
    st.header("📋 GESTIONE BOVINI")

    with st.expander("➕ Aggiungi Bovino"):
        n_id = st.text_input("ID Tracker")
        n_nome = st.text_input("Nome Animale")
        if st.button("Salva Bovino"):
            if n_id and n_nome:
                with conn.session as s:
                    s.execute(
                        text(
                            "INSERT INTO mandria (id, nome, lat, lon, stato_recinto) "
                            "VALUES (:id, :nome, NULL, NULL, 'DENTRO') "
                            "ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome"
                        ),
                        {"id": n_id, "nome": n_nome},
                    )
                    s.commit()
                st.rerun()

    if not df_mandria.empty:
        with st.expander("🗑️ Rimuovi Bovino"):
            bov_del = st.selectbox("Elimina:", df_mandria["nome"].tolist())
            if st.button("Conferma Eliminazione"):
                with conn.session as s:
                    s.execute(text("DELETE FROM mandria WHERE nome=:nome"), {"nome": bov_del})
                    s.commit()
                st.rerun()

# --- 5. CENTRO MAPPA ---
c_lat, c_lon = 37.9747, 13.5753
if not df_mandria.empty and "lat" in df_mandria.columns and "lon" in df_mandria.columns:
    df_v = df_mandria.dropna(subset=["lat", "lon"]).query("lat != 0 and lon != 0")
    if not df_v.empty:
        c_lat, c_lon = df_v["lat"].mean(), df_v["lon"].mean()

# --- 6. FUNZIONI MAPPA ---
def build_base_map(center_lat, center_lon):
    m = folium.Map(location=[center_lat, center_lon], zoom_start=18, tiles=None)
    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        attr="Google Satellite",
        name="Google Satellite",
        overlay=False,
        control=False,
    ).add_to(m)
    return m

def add_draw(m):
    Draw(
        draw_options={"polyline": False, "rectangle": False, "circle": False, "marker": False, "polygon": True},
        edit_options={"edit": False, "remove": False},
    ).add_to(m)

def build_overlay_feature_group(saved_coords, df_mandria):
    fg = folium.FeatureGroup(name="overlay", overlay=True, control=False)

    if saved_coords:
        folium.Polygon(
            locations=saved_coords,
            color="yellow",
            weight=3,
            fill=True,
            fill_opacity=0.2,
        ).add_to(fg)

    for _, row in df_mandria.iterrows():
        if pd.notna(row.get("lat")) and row["lat"] != 0:
            color = "green" if row.get("stato_recinto") == "DENTRO" else "red"
            folium.Marker(
                [row["lat"], row["lon"]],
                icon=folium.Icon(color=color, icon="info-sign"),
            ).add_to(fg)

    return fg

def extract_polygon_from_out(out_dict):
    """
    Estrae l'ultimo poligono chiuso da out['all_drawings'] o out['last_active_drawing'].
    Ritorna coords in formato [[lat, lon], ...] oppure None.
    """
    if not out_dict or not isinstance(out_dict, dict):
        return None

    drawing = None
    if out_dict.get("all_drawings"):
        try:
            if len(out_dict["all_drawings"]) > 0:
                drawing = out_dict["all_drawings"][-1]
        except Exception:
            drawing = None
    if drawing is None and out_dict.get("last_active_drawing"):
        drawing = out_dict["last_active_drawing"]

    if not drawing or not isinstance(drawing, dict):
        return None

    geom = drawing.get("geometry") if isinstance(drawing.get("geometry"), dict) else None
    if not geom:
        return None

    if geom.get("type") != "Polygon":
        return None

    raw = geom.get("coordinates")
    # GeoJSON Polygon: [ [ [lon,lat], ... ] , ... ] -> prendiamo anello esterno [0]
    if not (isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], list)):
        return None

    ring = raw[0]
    coords = []
    for p in ring:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            lon, lat = p[0], p[1]
            coords.append([lat, lon])

    return coords if len(coords) >= 3 else None

# --- 7. LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    if not st.session_state.edit_mode:
        if st.button("🏗️ INIZIA DISEGNO NUOVO RECINTO"):
            st.session_state.edit_mode = True
            st.session_state.temp_coords = None
            st.rerun()

    # --- VIEW MODE: dynamic update (ok per marker/recinto) ---
    if not st.session_state.edit_mode:
        m = build_base_map(c_lat, c_lon)
        add_draw(m)  # lo lasciamo anche in view, non dà fastidio
        fg = build_overlay_feature_group(saved_coords, df_mandria)

        out = st_folium(
            m,
            center=[c_lat, c_lon],
            zoom=18,
            feature_group_to_add=fg,
            use_container_width=True,
            height=650,
            key="main_map_view",
        )

    # --- EDIT MODE: NO dynamic update + key diversa (necessario per ricevere i drawings) ---
    else:
        m = build_base_map(c_lat, c_lon)
        add_draw(m)

        # (opzionale) puoi mostrare anche il vecchio recinto mentre disegni:
        if saved_coords:
            folium.Polygon(
                locations=saved_coords,
                color="yellow",
                weight=3,
                fill=True,
                fill_opacity=0.15,
            ).add_to(m)

        out = st_folium(
            m,
            use_container_width=True,
            height=650,
            key="main_map_edit",  # <-- key diversa = componente separato
        )

    # --- Estrazione poligono chiuso ---
    new_coords = extract_polygon_from_out(out)
    if new_coords:
        st.session_state.temp_coords = new_coords

    # --- UI salvataggio ---
    # Mostra se in edit mode o se abbiamo già temp_coords
    if st.session_state.edit_mode or st.session_state.temp_coords:
        if st.session_state.temp_coords:
            st.success("📍 Poligono pronto!")
            if st.button("💾 SALVA NUOVO RECINTO"):
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
                st.rerun()
        else:
            st.info("Disegna sulla mappa e chiudi il poligono.")

with col_table:
    st.subheader("⚠️ Pannello Emergenze")

    if "batteria" in df_mandria.columns:
        df_emergenza = df_mandria[
            (df_mandria["stato_recinto"] == "FUORI") | (df_mandria["batteria"] <= 20)
        ].copy()
    else:
        df_emergenza = df_mandria[(df_mandria["stato_recinto"] == "FUORI")].copy()

    if not df_emergenza.empty:
        def genera_avvisi(row):
            avv = []
            if row.get("stato_recinto") == "FUORI":
                avv.append("🚨 FUORI")
            if "batteria" in df_emergenza.columns:
                b = row.get("batteria")
                if pd.notna(b) and b <= 20:
                    avv.append("🪫 BATTERIA")
            return " + ".join(avv)

        df_emergenza["PROBLEMA"] = df_emergenza.apply(genera_avvisi, axis=1)
        st.error(f"Criticità: {len(df_emergenza)}")

        cols = ["nome", "PROBLEMA"]
        if "batteria" in df_emergenza.columns:
            cols.append("batteria")
        st.dataframe(df_emergenza[cols], hide_index=True)
    else:
        st.success("✅ Tutto Sotto Controllo")

st.divider()
st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
