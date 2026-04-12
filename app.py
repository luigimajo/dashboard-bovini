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

# --- SESSION STATE ORIGINALE RIPRISTINATO ---
if "edit_mode" not in st.session_state: st.session_state.edit_mode = False
if "refresh_enabled" not in st.session_state: st.session_state.refresh_enabled = True
if "draft_points" not in st.session_state: st.session_state.draft_points = []
if "temp_coords" not in st.session_state: st.session_state.temp_coords = None
if "last_click_sig" not in st.session_state: st.session_state.last_click_sig = None
if "draw_session_id" not in st.session_state: st.session_state.draw_session_id = 0
if "lock_expires_at" not in st.session_state: st.session_state.lock_expires_at = None
if "session_id" not in st.session_state: st.session_state.session_id = str(uuid.uuid4())
if "debug" not in st.session_state: st.session_state.debug = False

LOCK_MINUTES = 5
now = datetime.now()
ora_log = now.strftime("%H:%M:%S.%f")[:-3]
conn = st.connection("postgresql", type="sql")

# --- FUNZIONI DI LOCK ---
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

# --- SIDEBAR: GESTIONE COMPLETA ---
with st.sidebar:
    st.header("📡 RETE E FREQUENZA")
    
    # 1. Slider Frequenza
    curr_f = int(df_mandria['frequenza_desiderata'].iloc[0]) if not df_mandria.empty else 30
    new_f = st.slider("Minuti Invio (Normale)", 1, 120, curr_f)
    if st.button("Aggiorna Frequenza"):
        with conn.session as s:
            s.execute(text("UPDATE mandria SET frequenza_desiderata = :f"), {"f": new_f})
            s.commit()
        st.success(f"Coda TTN: {new_f} min")

    st.divider()
    
    # 2. Gestione Gateway (Codice Originale Ripristinato)
    st.subheader("🛰️ Gateway")
    for _, g in df_gateways.iterrows():
        color = "#28a745" if g["stato"] == "ONLINE" else "#dc3545"
        st.markdown(f'<div style="border-left:5px solid {color}; padding-left:10px;"><b>{g["nome"]}</b> ({g["stato"]})</div>', unsafe_allow_html=True)
    
    with st.expander("➕/➖ Gestisci Gateway"):
        g_id = st.text_input("ID Gateway")
        g_nome = st.text_input("Nome")
        if st.button("Aggiungi"):
            with conn.session as s:
                s.execute(text("INSERT INTO gateway (id, nome, stato) VALUES (:id, :n, 'ONLINE')"), {"id": g_id, "n": g_nome})
                s.commit()
            st.rerun()
        g_del = st.selectbox("Rimuovi:", df_gateways['id'].tolist() if not df_gateways.empty else ["--"])
        if st.button("Elimina Gateway"):
            with conn.session as s:
                s.execute(text("DELETE FROM gateway WHERE id = :id"), {"id": g_del})
                s.commit()
            st.rerun()

    st.divider()

    # 3. Gestione Bovini (Codice Originale Ripristinato)
    st.subheader("🐄 Mandria")
    with st.expander("Aggiungi/Rimuovi Bovino"):
        b_id = st.text_input("ID Tracker")
        b_nome = st.text_input("Nome Bovino")
        if st.button("Salva"):
            with conn.session as s:
                s.execute(text("INSERT INTO mandria (id, nome, stato_recinto) VALUES (:id, :n, 'DENTRO') ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome"), {"id": b_id, "n": b_nome})
                s.commit()
            st.rerun()
        b_del = st.selectbox("Elimina:", df_mandria['nome'].tolist() if not df_mandria.empty else ["--"])
        if st.button("Elimina Bovino"):
            with conn.session as s:
                s.execute(text("DELETE FROM mandria WHERE nome = :n"), {"n": b_del})
                s.commit()
            st.rerun()

# --- MAPPA SATELLITARE E RECINTI ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_ctrl = st.columns([3, 1])

with col_map:
    # Mappa Google Satellite Costante
    m = folium.Map(location=[37.9747, 13.5753], zoom_start=18, tiles=None)
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google Satellite', name='Google Satellite', overlay=False
    ).add_to(m)

    # Disegna Recinti
    for _, r in df_recinti.iterrows():
        color = "green" if r['attivo'] else "orange"
        folium.Polygon(locations=json.loads(r['coords']), color=color, weight=2, fill=r['attivo'], fill_opacity=0.2, popup=r['nome']).add_to(m)

    # Marker Bovini
    for _, row in df_mandria.iterrows():
        if pd.notna(row.get("lat")):
            color = "green" if row["stato_recinto"] == "DENTRO" else "red"
            folium.Marker([row["lat"], row["lon"]], popup=row["nome"], icon=folium.Icon(color=color)).add_to(m)

    # Modalità Edit (Punti Azzurri)
    if st.session_state.edit_mode:
        folium.LatLngPopup().add_to(m)
        if len(st.session_state.draft_points) >= 2:
            folium.PolyLine(st.session_state.draft_points, color="cyan", weight=3).add_to(m)
        if st.session_state.temp_coords:
            folium.Polygon(st.session_state.temp_coords, color="cyan", fill=True, fill_opacity=0.4).add_to(m)

    # Bottone Nuova Modifica
    if not st.session_state.edit_mode:
        if st.button("🏗️ INIZIA NUOVO RECINTO"):
            if try_lock_recinto(1, st.session_state.session_id, LOCK_MINUTES):
                st.session_state.edit_mode = True
                st.session_state.refresh_enabled = False
                st.session_state.lock_expires_at = datetime.now() + timedelta(minutes=LOCK_MINUTES)
                st.session_state.draft_points = []
                st.session_state.temp_coords = None
                st.session_state.draw_session_id += 1
                st.rerun()

    # Mappa Interattiva
    out = st_folium(m, width="100%", height=650, key=f"map_{st.session_state.draw_session_id}")

    # Cattura Click
    if st.session_state.edit_mode and out and out.get("last_clicked"):
        lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
        click_sig = (round(lat, 6), round(lon, 6))
        if click_sig != st.session_state.last_click_sig:
            st.session_state.draft_points.append([lat, lon])
            st.session_state.last_click_sig = click_sig
            st.rerun()

with col_ctrl:
    st.subheader("🛠️ GESTIONE RECINTI")
    
    # 1. Attiva/Elimina Recinti Esistenti
    if not df_recinti.empty:
        r_nomi = df_recinti['nome'].tolist()
        r_sel = st.selectbox("Seleziona Recinto:", r_nomi)
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ Attiva"):
                with conn.session as s:
                    s.execute(text("UPDATE recinti SET attivo = (nome = :n)"), {"n": r_sel})
                    s.execute(text("UPDATE mandria SET ultimo_aggiornamento = now()"))
                    s.commit()
                st.rerun()
        with c2:
            if st.button("🗑️ Elimina"):
                with conn.session as s:
                    s.execute(text("DELETE FROM recinti WHERE nome = :n"), {"n": r_sel})
                    s.commit()
                st.rerun()

    st.divider()

    # 2. Editor Disegno (Ripristinato Integrale)
    if st.session_state.edit_mode:
        st.info("Clicca sulla mappa satellitare")
        st.write(f"Punti: {len(st.session_state.draft_points)}")
        
        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("↩️ Undo"): 
                if st.session_state.draft_points: st.session_state.draft_points.pop(); st.rerun()
        with b2:
            if st.button("✅ Chiudi"):
                if len(st.session_state.draft_points) > 2:
                    st.session_state.temp_coords = st.session_state.draft_points + [st.session_state.draft_points[0]]
                    st.rerun()
        with b3:
            if st.button("🧹 Reset"): st.session_state.draft_points = []; st.rerun()

                   # --- LOGICA SALVATAGGIO (Sostituisci questo blocco nell'Editor) ---
    if st.session_state.edit_mode:
        st.info("Clicca sulla mappa satellitare")
        st.write(f"Punti: {len(st.session_state.draft_points)}")
        
        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("↩️ Undo"): 
                if st.session_state.draft_points: st.session_state.draft_points.pop(); st.rerun()
        with b2:
            if st.button("✅ Chiudi"):
                if len(st.session_state.draft_points) > 2:
                    # Chiusura corretta del poligono
                    st.session_state.temp_coords = st.session_state.draft_points + [st.session_state.draft_points[0]]
                    st.rerun()
        with b3:
            if st.button("🧹 Reset"): 
                st.session_state.draft_points = []; st.session_state.temp_coords = None; st.rerun()

        # QUESTO È IL BLOCCO CHE DAVA ERRORE (Controlla gli spazi qui sotto)
        if st.session_state.temp_coords:
            nome_n = st.text_input("Nome Nuovo Pascolo:", f"Pascolo {datetime.now().strftime('%H:%M')}")
            if st.button("💾 SALVA DEFINITIVO"):
                try:
                    js_c = json.dumps(st.session_state.temp_coords)
                    with conn.session as s:
                        s.execute(text("UPDATE recinti SET attivo = false"))
                        s.execute(text("INSERT INTO recinti (nome, coords, attivo) VALUES (:n, :c, true)"), 
                                  {"n": nome_n, "c": js_c})
                        s.commit()
                    unlock_recinto(1, st.session_state.session_id)
                    st.session_state.edit_mode = False
                    st.session_state.refresh_enabled = True
                    st.session_state.draft_points = []
                    st.session_state.temp_coords = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")


# --- TABELLE FINALI ---
st.divider()
st.subheader("📝 Storico Mandria Completo")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
