import streamlit as st
import streamlit.components.v1 as components
import folium
from streamlit_folium import st_folium
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timedelta
import uuid

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# --- SESSION STATE BASE (Ripristinato integrale) ---
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False
if "refresh_enabled" not in st.session_state:
    st.session_state.refresh_enabled = True
if "draft_points" not in st.session_state:
    st.session_state.draft_points = []
if "temp_coords" not in st.session_state:
    st.session_state.temp_coords = None
if "last_click_sig" not in st.session_state:
    st.session_state.last_click_sig = None
if "draw_session_id" not in st.session_state:
    st.session_state.draw_session_id = 0
if "lock_expires_at" not in st.session_state:
    st.session_state.lock_expires_at = None
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "debug" not in st.session_state:
    st.session_state.debug = True

LOCK_MINUTES = 5
now = datetime.now()
ora_log = now.strftime("%H:%M:%S.%f")[:-3]
conn = st.connection("postgresql", type="sql")

def dbg(msg: str):
    if st.session_state.debug:
        st.sidebar.write(msg)

# --- GESTIONE LOCK DB ---
def try_lock_recinto(lock_id: int, who: str, ttl_minutes: int) -> bool:
    with conn.session as s:
        res = s.execute(text("""
            UPDATE public.recinto_lock SET locked = true, locked_by = :who, locked_at = now()
            WHERE id = :id AND (locked = false OR locked_at < (now() - (:ttl || ' minutes')::interval))
            RETURNING id;"""), {"id": lock_id, "who": who, "ttl": str(ttl_minutes)}).fetchone()
        s.commit()
    return res is not None

def unlock_recinto(lock_id: int, who: str):
    with conn.session as s:
        s.execute(text("UPDATE public.recinto_lock SET locked = false, locked_by = NULL, locked_at = NULL WHERE id = :id AND locked_by = :who;"),
                  {"id": lock_id, "who": who})
        s.commit()

def get_lock_state(lock_id: int):
    try:
        df = conn.query(f"SELECT locked, locked_by, locked_at FROM public.recinto_lock WHERE id = {lock_id}", ttl=0)
        if df.empty: return False, None, None
        r = df.iloc[0]
        return bool(r["locked"]), r.get("locked_by"), r.get("locked_at")
    except: return False, None, None

# --- REFRESH ---
if st.session_state.refresh_enabled:
    st_autorefresh(interval=30000, key="timer_30s")

# --- TIMEOUT AUTO-UNLOCK ---
if st.session_state.edit_mode and st.session_state.lock_expires_at:
    if now >= st.session_state.lock_expires_at:
        unlock_recinto(1, st.session_state.session_id)
        st.session_state.edit_mode = False
        st.session_state.refresh_enabled = True
        st.rerun()

# --- CARICAMENTO DATI ---
@st.cache_data(ttl=2)
def load_data():
    df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
    df_g = conn.query("SELECT * FROM gateway ORDER BY ultima_attivita DESC", ttl=0)
    df_r = conn.query("SELECT * FROM recinti ORDER BY id ASC", ttl=0)
    return df_m, df_g, df_r

df_mandria, df_gateways, df_recinti = load_data()

# --- SIDEBAR ---
with st.sidebar:
    st.header("📡 STATO RETE LORA")
    st.write(f"Ultimo Refresh: **{ora_log}**")
    
    # LOCK STATE
    locked, l_by, l_at = get_lock_state(1)
    if locked:
        st.info("🔒 Recinto in modifica" if l_by != st.session_state.session_id else "🔒 Lock attivo (tua sessione)")
    else: st.success("🔓 Recinto libero")

    # FREQUENZA (Novità)
    st.divider()
    st.subheader("⏱️ Frequenza Tracker")
    curr_f = int(df_mandria['frequenza_desiderata'].iloc[0]) if not df_mandria.empty else 30
    freq_val = st.slider("Minuti (Normale):", 1, 120, curr_f)
    if st.button("Salva Frequenza"):
        with conn.session as s:
            s.execute(text("UPDATE mandria SET frequenza_desiderata = :f"), {"f": freq_val})
            s.commit()
        st.success(f"Configurato a {freq_val} min")

    # MULTI-RECINTO (Novità)
    st.divider()
    st.subheader("🗺️ Gestione Pascoli")
    if not df_recinti.empty:
        nomi_r = df_recinti['nome'].tolist()
        r_attivo = df_recinti[df_recinti['attivo']==True]
        idx_r = nomi_r.index(r_attivo['nome'].iloc[0]) if not r_attivo.empty else 0
        scelta_r = st.selectbox("Attiva recinto:", nomi_r, index=idx_r)
        if st.button("Applica Recinto"):
            with conn.session as s:
                s.execute(text("UPDATE recinti SET attivo = (nome = :n)"), {"n": scelta_r})
                s.execute(text("UPDATE mandria SET ultimo_aggiornamento = now()"))
                s.commit()
            st.rerun()

    # GATEWAY (Tuo codice originale)
    if not df_gateways.empty:
        for _, g in df_gateways.iterrows():
            col = "#28a745" if g["stato"] == "ONLINE" else "#dc3545"
            st.markdown(f'<div style="border-left:5px solid {col};padding:5px;"><b>{g["nome"]}</b></div>', unsafe_allow_html=True)

# --- MAPPA SATELLITARE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    # Google Satellite ripristinato
    m = folium.Map(location=[37.9747, 13.5753], zoom_start=18, tiles=None)
    folium.TileLayer(
        tiles="https://google.com{x}&y={y}&z={z}",
        attr="Google Satellite", name="Google Satellite", overlay=False
    ).add_to(m)

    # Disegna recinti (Verde = Attivo, Giallo = Altri)
    for _, r in df_recinti.iterrows():
        color = "green" if r['attivo'] else "orange"
        folium.Polygon(locations=json.loads(r['coords']), color=color, weight=2, fill=r['attivo'], fill_opacity=0.2, popup=r['nome']).add_to(m)

    # Marker Bovini (Verde/Rosso)
    for _, row in df_mandria.iterrows():
        if pd.notna(row.get("lat")) and row["lat"] != 0:
            color = "green" if row["stato_recinto"] == "DENTRO" else "red"
            folium.Marker([row["lat"], row["lon"]], popup=row["nome"], icon=folium.Icon(color=color)).add_to(m)

    # Logica Disegno (Polilinea Azzurra)
    if st.session_state.edit_mode:
        folium.LatLngPopup().add_to(m)
        if len(st.session_state.draft_points) >= 2:
            folium.PolyLine(st.session_state.draft_points, color="cyan", weight=3).add_to(m)
        if st.session_state.temp_coords:
            folium.Polygon(st.session_state.temp_coords, color="cyan", fill=True, fill_opacity=0.3).add_to(m)

    # Bottone Inizio
    if not st.session_state.edit_mode:
        if st.button("🏗️ NUOVO RECINTO"):
            if try_lock_recinto(1, st.session_state.session_id, LOCK_MINUTES):
                st.session_state.edit_mode = True
                st.session_state.refresh_enabled = False
                st.session_state.lock_expires_at = datetime.now() + timedelta(minutes=LOCK_MINUTES)
                st.session_state.draft_points = []
                st.session_state.draw_session_id += 1
                st.rerun()
    
    # Visualizzazione Countdown HTML (Tuo codice)
    if st.session_state.edit_mode and st.session_state.lock_expires_at:
        expires_iso = st.session_state.lock_expires_at.strftime("%Y-%m-%dT%H:%M:%S")
        components.html(f"""<script>
            const expires = new Date("{expires_iso}").getTime();
            setInterval(() => {{
                const now = Date.now();
                let s = Math.floor((expires - now)/1000);
                if (s<0) s=0;
                document.getElementById("cd").textContent = String(Math.floor(s/60)).padStart(2,'0') + ":" + String(s%60).padStart(2,'0');
            }}, 1000);
        </script><div style='color:white;'>⏱️ Scadenza: <span id='cd'>--:--</span></div>""", height=30)

    # Render Mappa e Cattura Click
    out = st_folium(m, width="100%", height=600, key=f"map_{st.session_state.draw_session_id}")

    if st.session_state.edit_mode and out and out.get("last_clicked"):
        lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
        if not st.session_state.draft_points or [lat, lon] != st.session_state.draft_points[-1]:
            st.session_state.draft_points.append([lat, lon])
            st.rerun()

    # Bottoni Editor
    if st.session_state.edit_mode:
        nome_n = st.text_input("Nome Pascolo:", f"Recinto {len(df_recinti)+1}")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("✅ Chiudi Poligono"):
                if len(st.session_state.draft_points) > 2:
                    st.session_state.temp_coords = st.session_state.draft_points + [st.session_state.draft_points[0]]
                    st.rerun()
        with c2:
            if st.session_state.temp_coords and st.button("💾 SALVA"):
                with conn.session as s:
                    s.execute(text("UPDATE recinti SET attivo = false"))
                    s.execute(text("INSERT INTO recinti (nome, coords, attivo) VALUES (:n, :c, true)"), 
                              {"n": nome_n, "c": json.dumps(st.session_state.temp_coords)})
                    s.commit()
                unlock_recinto(1, st.session_state.session_id)
                st.session_state.edit_mode = False
                st.session_state.refresh_enabled = True
                st.rerun()
        with c3:
            if st.button("❌ Annulla"):
                unlock_recinto(1, st.session_state.session_id)
                st.session_state.edit_mode = False
                st.session_state.refresh_enabled = True
                st.rerun()

with col_table:
    st.subheader("⚠️ Emergenze")
    df_e = df_mandria[df_mandria["stato_recinto"]=="FUORI"]
    if not df_e.empty: st.error(f"Bovini Fuori: {len(df_e)}"); st.table(df_e[["nome", "batteria"]])
    else: st.success("Tutti dentro")

st.divider()
st.subheader("📝 Storico Posizioni")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
