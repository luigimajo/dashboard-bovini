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

# --- 2. REFRESH ROBUSTO ---
if st.session_state.edit_mode:
    # Disarma il timer per evitare cancellazioni durante il disegno
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

# --- 4. SIDEBAR (GESTIONE INVARIA) ---
with st.sidebar:
    st.header("📡 STATO RETE LORA")
    st.write(f"Ultimo Refresh: **{ora_log}**")
    # ... (il tuo codice sidebar esistente per gateway e bovini)

# --- 5. COSTRUZIONE MAPPA ---
c_lat, c_lon = 37.9747, 13.5753
if not df_mandria.empty and "lat" in df_mandria.columns and "lon" in df_mandria.columns:
    df_v = df_mandria.dropna(subset=["lat", "lon"]).query("lat != 0 and lon != 0")
    if not df_v.empty:
        c_lat, c_lon = df_v["lat"].mean(), df_v["lon"].mean()

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# BLOCCO SATELLITE GOOGLE (FISSO)
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attr="Google Satellite",
    name="Google Satellite",
    overlay=False,
    control=False,
).add_to(m)

# Plugin Draw
Draw(
    draw_options={"polyline": False, "rectangle": False, "circle": False, "marker": False, "polygon": True},
    edit_options={"edit": False, "remove": False},
).add_to(m)

# FeatureGroup per elementi statici
fg = folium.FeatureGroup(name="overlay")
if saved_coords:
    folium.Polygon(locations=saved_coords, color="yellow", weight=3, fill=True, fill_opacity=0.2).add_to(fg)

for _, row in df_mandria.iterrows():
    if pd.notna(row.get("lat")) and row["lat"] != 0:
        color = "green" if row.get("stato_recinto") == "DENTRO" else "red"
        folium.Marker([row["lat"], row["lon"]], icon=folium.Icon(color=color, icon="info-sign")).add_to(fg)

# --- 6. LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    # Tasto per entrare in modalità edit
    if not st.session_state.edit_mode:
        if st.button("🏗️ INIZIA DISEGNO NUOVO RECINTO"):
            st.session_state.edit_mode = True
            st.session_state.temp_coords = None
            st.rerun()

    # Visualizzazione Mappa
    out = st_folium(
        m,
        feature_group_to_add=fg,
        use_container_width=True,
        height=650,
        key="main_map",
    )

    # CATTURA COORDINATE: Se la mappa rimanda disegni, li salviamo in session_state subito
    if out and out.get("all_drawings"):
        drawings = out.get("all_drawings")
        if len(drawings) > 0:
            raw = drawings[-1]["geometry"]["coordinates"]
            # Gestione poligono (GeoJSON [[[lon,lat]]])
            if isinstance(raw[0][0], list):
                st.session_state.temp_coords = [[p[1], p[0]] for p in raw[0]]
            else:
                st.session_state.temp_coords = [[p[1], p[0]] for p in raw]

    # MOSTRA IL TASTO SALVA: se siamo in edit_mode, il tasto deve apparire
    if st.session_state.edit_mode:
        if st.session_state.temp_coords:
            st.success(f"📍 Poligono rilevato ({len(st.session_state.temp_coords)} punti).")
            # IL TASTO SALVA ORA È QUI SOTTO, PERSISTENTE
            if st.button("💾 SALVA NUOVO RECINTO"):
                with conn.session as s:
                    s.execute(
                        text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"),
                        {"coords": json.dumps(st.session_state.temp_coords)},
                    )
                    s.commit()
                st.session_state.edit_mode = False
                st.session_state.temp_coords = None
                st.success("Recinto aggiornato!")
                time.sleep(1)
                st.rerun()
        else:
            st.info("Disegna sulla mappa e chiudi il poligono cliccando sul primo punto.")

with col_table:
    st.subheader("⚠️ Pannello Emergenze")
    # ... (il tuo codice tabella emergenze)

# ... (il resto dello storico aggiornamenti)


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
