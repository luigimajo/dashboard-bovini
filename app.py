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

# --- 1. CONFIGURAZIONE PAGINA E COSTANTI ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

LOCK_MINUTES = 5
now = datetime.now()
ora_log = now.strftime("%H:%M:%S.%f")[:-3]

# --- 2. SESSION STATE (MEMORIA DINAMICA) ---
if "map_center" not in st.session_state:
    st.session_state.map_center = [37.9747, 13.5753]
if "map_zoom" not in st.session_state:
    st.session_state.map_zoom = 18
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

conn = st.connection("postgresql", type="sql")

# --- FUNZIONI DI LOCK DB ---
def try_lock_recinto(lock_id, who, ttl):
    with conn.session as s:
        res = s.execute(text("""
            UPDATE public.recinto_lock SET locked = true, locked_by = :who, locked_at = now()
            WHERE id = :id AND (locked = false OR locked_at < (now() - (:ttl || ' minutes')::interval))
            RETURNING id;"""), {"id": lock_id, "who": who, "ttl": str(ttl)}).fetchone()
        s.commit()
    return res is not None

def unlock_recinto(lock_id, who):
    with conn.session as s:
        s.execute(text("UPDATE public.recinto_lock SET locked = false, locked_by = NULL, locked_at = NULL WHERE id = :id AND locked_by = :who"), 
                  {"id": lock_id, "who": who})
        s.commit()

# --- CARICAMENTO DATI ---
@st.cache_data(ttl=2)
def load_data():
    df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
    df_g = conn.query("SELECT * FROM gateway ORDER BY ultima_attivita DESC", ttl=0)
    df_r = conn.query("SELECT * FROM recinti ORDER BY id ASC", ttl=0)
    return df_m, df_g, df_r

df_mandria, df_gateways, df_recinti = load_data()

# --- REFRESH ---
if st.session_state.refresh_enabled:
    st_autorefresh(interval=30000, key="timer_30s")

# --- SIDEBAR ---
with st.sidebar:
    st.header("📡 RETE E FREQUENZA")
    st.write(f"Ultimo Refresh: **{ora_log}**")
    
    st.subheader("⏱️ Frequenza Tracker")
    curr_f = int(df_mandria['frequenza_desiderata'].iloc[0]) if not df_mandria.empty else 30
    new_f = st.slider("Minuti Invio (Normale)", 1, 120, curr_f)
    if st.button("Aggiorna Frequenza Tracker", key="btn_freq"):
        with conn.session as s:
            s.execute(text("UPDATE mandria SET frequenza_desiderata = :f"), {"f": new_f})
            s.commit()
        st.success(f"Coda TTN aggiornata a {new_f} min")

    st.divider()
    st.subheader("🛰️ Gateway")
    for _, g in df_gateways.iterrows():
        color = "#28a745" if g["stato"] == "ONLINE" else "#dc3545"
        st.markdown(f'<div style="border-left:5px solid {color}; padding-left:10px;"><b>{g["nome"]}</b> ({g["stato"]})</div>', unsafe_allow_html=True)
    
    with st.expander("➕ Gestisci Mandria"):
        b_id = st.text_input("ID Tracker", key="in_b_id")
        b_nome = st.text_input("Nome", key="in_b_nome")
        if st.button("Salva Bovino", key="btn_add_b"):
            with conn.session as s:
                s.execute(text("INSERT INTO mandria (id, nome, stato_recinto) VALUES (:id, :n, 'DENTRO') ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome"), {"id": b_id, "n": b_nome})
                s.commit()
            st.rerun()

# --- MAPPA E CONTROLLI ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
# CORREZIONE RIGA 105: aggiunto l'argomento [3, 1] per definire le proporzioni delle colonne
col_map, col_ctrl = st.columns([3, 1])

with col_map:
    m = folium.Map(
        location=st.session_state.map_center, 
        zoom_start=st.session_state.map_zoom, 
        tiles=None
    )
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google Satellite', name='Google Satellite', overlay=False, control=False
    ).add_to(m)

    for _, r in df_recinti.iterrows():
        color = "green" if r['attivo'] else "orange"
        folium.Polygon(locations=json.loads(r['coords']), color=color, weight=2, fill=r['attivo'], fill_opacity=0.2, popup=r['nome']).add_to(m)

    for _, row in df_mandria.iterrows():
        if pd.notna(row.get("lat")) and row["lat"] != 0:
            color = "green" if row["stato_recinto"] == "DENTRO" else "red"
            folium.Marker([row["lat"], row["lon"]], popup=row["nome"], icon=folium.Icon(color=color)).add_to(m)

    if st.session_state.edit_mode:
        folium.LatLngPopup().add_to(m)
        if len(st.session_state.draft_points) >= 2:
            folium.PolyLine(st.session_state.draft_points, color="cyan", weight=3).add_to(m)
        if st.session_state.temp_coords:
            folium.Polygon(st.session_state.temp_coords, color="cyan", fill=True, fill_opacity=0.4).add_to(m)

    # RENDER MAPPA
    out = st_folium(m, width="100%", height=650, key=f"map_{st.session_state.draw_session_id}")

    # AGGIORNAMENTO POSIZIONE (Sincronizzato per evitare salti)
    if out is not None:
        if out.get("center") and (out["center"]["lat"] != st.session_state.map_center[0]):
            st.session_state.map_center = [out["center"]["lat"], out["center"]["lng"]]
        if out.get("zoom") and (out["zoom"] != st.session_state.map_zoom):
            st.session_state.map_zoom = out["zoom"]

    if st.session_state.edit_mode and out and out.get("last_clicked"):
        lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
        click_sig = (round(lat, 6), round(lon, 6))
        if click_sig != st.session_state.last_click_sig:
            st.session_state.draft_points.append([lat, lon])
            st.session_state.last_click_sig = click_sig
            st.rerun()

with col_ctrl:
    st.subheader("🛠️ GESTIONE RECINTI")
    
    if not df_recinti.empty:
        r_nomi = df_recinti['nome'].tolist()
        r_att_df = df_recinti[df_recinti['attivo']==True]
        idx_init = r_nomi.index(r_att_df['nome'].iloc[0]) if not r_att_df.empty else 0
        r_sel = st.selectbox("Seleziona Pascolo:", r_nomi, index=idx_init, key="sel_r_manage")
        
        ca, ce = st.columns(2)
        with ca:
            if st.button("✅ Attiva", key="btn_r_act"):
                with conn.session as s:
                    s.execute(text("UPDATE recinti SET attivo = (nome = :n)"), {"n": r_sel})
                    s.execute(text("UPDATE mandria SET ultimo_aggiornamento = now()"))
                    s.commit()
                st.rerun()
        with ce:
            if st.button("🗑️ Elimina", key="btn_r_del"):
                with conn.session as s:
                    s.execute(text("DELETE FROM recinti WHERE nome = :n"), {"n": r_sel})
                    s.commit()
                st.rerun()

    st.divider()
    if not st.session_state.edit_mode:
        if st.button("🏗️ NUOVO RECINTO", key="btn_start_draw"):
            if try_lock_recinto(1, st.session_state.session_id, LOCK_MINUTES):
                st.session_state.edit_mode = True
                st.session_state.refresh_enabled = False
                st.session_state.lock_expires_at = datetime.now() + timedelta(minutes=LOCK_MINUTES)
                st.session_state.draft_points = []
                st.session_state.temp_coords = None
                st.rerun()
    else:
        st.write(f"Punti: **{len(st.session_state.draft_points)}**")
        b_undo, b_close, b_reset = st.columns(3)
        with b_undo:
            if st.button("↩️ Undo", key="btn_undo"): 
                if st.session_state.draft_points: st.session_state.draft_points.pop(); st.session_state.temp_coords=None; st.rerun()
        with b_close:
            if st.button("✅ Chiudi", key="btn_close"):
                if len(st.session_state.draft_points) > 2:
                    st.session_state.temp_coords = st.session_state.draft_points + [st.session_state.draft_points[0]]
                    st.rerun()
        with b_reset:
            if st.button("🧹 Reset", key="btn_reset"): 
                st.session_state.draft_points = []; st.session_state.temp_coords = None; st.rerun()

        if st.session_state.temp_coords:
            nome_n = st.text_input("Nome Pascolo:", f"Recinto {len(df_recinti)+1}", key="in_new_r_name")
            if st.button("💾 SALVA", key="btn_save_r"):
                try:
                    js_c = json.dumps(st.session_state.temp_coords)
                    with conn.session as s:
                        s.execute(text("INSERT INTO recinti (nome, coords, attivo) VALUES (:n, :c, false)"), {"n": nome_n, "c": js_c})
                        s.commit()
                    unlock_recinto(1, st.session_state.session_id)
                    st.session_state.edit_mode = False
                    st.session_state.refresh_enabled = True
                    st.rerun()
                except Exception as e: st.error(f"Errore: {e}")
        
        if st.button("❌ Annulla", key="btn_cancel_edit"):
            unlock_recinto(1, st.session_state.session_id)
            st.session_state.edit_mode = False
            st.session_state.refresh_enabled = True
            st.rerun()

st.divider()
st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
