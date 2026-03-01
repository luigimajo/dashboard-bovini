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

# --- Helper: estrazione universale poligono da qualsiasi struttura out ---
def find_latest_polygon_coords(obj):
    """
    Cerca ricorsivamente dentro 'obj' (dict/list) una Feature GeoJSON Polygon e restituisce:
    - coords in formato [[lat, lon], ...] (anello esterno)
    Se non trova niente, ritorna None.
    """
    def is_polygon_feature(d):
        try:
            if not isinstance(d, dict):
                return False
            # Feature GeoJSON classica
            if d.get("type") == "Feature" and isinstance(d.get("geometry"), dict):
                g = d["geometry"]
                return g.get("type") == "Polygon" and isinstance(g.get("coordinates"), list)
            # Alcune varianti: dict con chiave geometry direttamente
            if isinstance(d.get("geometry"), dict):
                g = d["geometry"]
                return g.get("type") == "Polygon" and isinstance(g.get("coordinates"), list)
            return False
        except Exception:
            return False

    def extract_latlon_from_polygon_coords(coords):
        # coords: [ [ [lon,lat], [lon,lat], ... ] , ... ]  (ring esterno = coords[0])
        if not (isinstance(coords, list) and len(coords) > 0 and isinstance(coords[0], list) and len(coords[0]) > 0):
            return None
        ring = coords[0]
        out_latlon = []
        for p in ring:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                lon, lat = p[0], p[1]
                out_latlon.append([lat, lon])
        return out_latlon if len(out_latlon) >= 3 else None

    # DFS ricorsivo: ritorna l'ultima Polygon trovata (se ce ne sono più)
    found = None

    def walk(x):
        nonlocal found
        if isinstance(x, dict):
            if is_polygon_feature(x):
                g = x.get("geometry", x)
                coords = g.get("coordinates")
                latlon = extract_latlon_from_polygon_coords(coords)
                if latlon:
                    found = latlon
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for it in x:
                walk(it)

    walk(obj)
    return found

# --- 5. COSTRUZIONE MAPPA ---
c_lat, c_lon = 37.9747, 13.5753
if not df_mandria.empty and "lat" in df_mandria.columns and "lon" in df_mandria.columns:
    df_v = df_mandria.dropna(subset=["lat", "lon"]).query("lat != 0 and lon != 0")
    if not df_v.empty:
        c_lat, c_lon = df_v["lat"].mean(), df_v["lon"].mean()

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attr="Google Satellite",
    name="Google Satellite",
    overlay=False,
    control=False,
).add_to(m)

Draw(
    draw_options={"polyline": False, "rectangle": False, "circle": False, "marker": False, "polygon": True},
    edit_options={"edit": False, "remove": False},
).add_to(m)

# Overlay (recinto salvato + marker)
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

# --- 6. LAYOUT PRINCIPALE ---
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
        center=[c_lat, c_lon],
        zoom=18,
        feature_group_to_add=fg,
        use_container_width=True,
        height=650,
        key="main_map",
    )

    # --- Estrazione universale Polygon da out (compatibile con versioni diverse) ---
    if out:
        coords = find_latest_polygon_coords(out)
        if coords:
            st.session_state.temp_coords = coords

    # (DEBUG opzionale: se vuoi vedere cosa arriva davvero, lascia questo expander)
    with st.expander("🔎 Debug disegno (se serve)"):
        if out is None:
            st.write("out = None")
        else:
            st.write("Chiavi out:", list(out.keys()) if isinstance(out, dict) else type(out))
            # Attenzione: non stampare tutto se enorme
            st.write(out)

    # --- UI SALVATAGGIO ---
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
