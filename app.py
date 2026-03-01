import streamlit as st
import streamlit.components.v1 as components
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timedelta
import uuid

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# Inizializzazione stati di sessione
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False
if "temp_coords" not in st.session_state:
    st.session_state.temp_coords = None

# MODIFICA 1) refresh flag + session id + map key stabile + scadenza lock
if "refresh_enabled" not in st.session_state:
    st.session_state.refresh_enabled = True
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "draw_session_id" not in st.session_state:
    st.session_state.draw_session_id = 0
if "lock_expires_at" not in st.session_state:
    st.session_state.lock_expires_at = None

LOCK_MINUTES = 5
now = datetime.now()

ora_log = now.strftime("%H:%M:%S.%f")[:-3]
conn = st.connection("postgresql", type="sql")

# -----------------------------
# LOCK GLOBALE via DB (evita blocchi eterni + concorrenza multi-istanza)
# -----------------------------
def ensure_lock_table():
    """
    Prova a creare la tabella lock se non esiste.
    Se il DB user non ha permessi DDL, la tabella deve esistere già.
    """
    try:
        with conn.session as s:
            s.execute(text("""
                CREATE TABLE IF NOT EXISTS recinto_lock (
                    id integer PRIMARY KEY,
                    locked boolean NOT NULL DEFAULT false,
                    locked_by text,
                    locked_at timestamptz
                );
            """))
            s.execute(text("INSERT INTO recinto_lock (id) VALUES (1) ON CONFLICT (id) DO NOTHING;"))
            s.commit()
    except Exception:
        pass

ensure_lock_table()

def try_lock_recinto(lock_id: int, who: str, ttl_minutes: int) -> bool:
    """
    Lock atomico: acquisisce se unlocked o scaduto (locked_at vecchio).
    """
    with conn.session as s:
        res = s.execute(
            text("""
                UPDATE recinto_lock
                SET locked = true, locked_by = :who, locked_at = now()
                WHERE id = :id
                  AND (
                        locked = false
                     OR locked_at IS NULL
                     OR locked_at < (now() - (:ttl || ' minutes')::interval)
                  )
                RETURNING id;
            """),
            {"id": lock_id, "who": who, "ttl": str(ttl_minutes)},
        ).fetchone()
        s.commit()
    return res is not None

def unlock_recinto(lock_id: int, who: str):
    """
    Sblocca solo se sei tu l'owner.
    """
    with conn.session as s:
        s.execute(
            text("""
                UPDATE recinto_lock
                SET locked = false, locked_by = NULL, locked_at = NULL
                WHERE id = :id AND locked_by = :who;
            """),
            {"id": lock_id, "who": who},
        )
        s.commit()

@st.cache_data(ttl=2)
def get_lock_state(lock_id: int):
    try:
        df = conn.query(
            "SELECT locked, locked_by, locked_at FROM recinto_lock WHERE id = 1",
            ttl=0
        )
        if df.empty:
            return False, None, None
        r = df.iloc[0]
        return bool(r["locked"]), r.get("locked_by"), r.get("locked_at")
    except Exception:
        return False, None, None

# --- 2. LOGICA REFRESH STABILIZZATA (ANTI-RAFFICA + BLOCCO DISEGNO) ---
# MODIFICA 2) usa refresh_enabled anziché edit_mode
if st.session_state.refresh_enabled:
    st_autorefresh(interval=30000, key="timer_primario_30s")
else:
    st.sidebar.warning("🏗️ MODALITÀ DISEGNO: Refresh Disabilitato")

# MODIFICA 5) (nota anti-lock eterno) + timer 5 minuti:
# se scade, annulla, riabilita refresh, prova a sbloccare
if st.session_state.edit_mode and st.session_state.lock_expires_at is not None:
    if now >= st.session_state.lock_expires_at:
        try:
            unlock_recinto(1, st.session_state.session_id)
        except Exception:
            pass
        st.session_state.edit_mode = False
        st.session_state.temp_coords = None
        st.session_state.refresh_enabled = True
        st.session_state.lock_expires_at = None
        st.sidebar.error("⏱️ Tempo scaduto (5 min): disegno annullato, refresh riabilitato.")
        st.rerun()

# Pulsante annulla in sidebar (sempre disponibile in edit)
with st.sidebar:
    if st.session_state.edit_mode:
        if st.button("🔓 Esci e annulla"):
            try:
                unlock_recinto(1, st.session_state.session_id)
            except Exception:
                pass
            st.session_state.edit_mode = False
            st.session_state.temp_coords = None
            st.session_state.refresh_enabled = True
            st.session_state.lock_expires_at = None
            st.rerun()

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

    locked, locked_by, locked_at = get_lock_state(1)
    if locked:
        if locked_by == st.session_state.session_id:
            st.info("🔒 Lock recinto attivo (stai disegnando).")
        else:
            st.info("🔒 Recinto in modifica da un'altra sessione.")
        st.caption(f"locked_by: {locked_by}")
        st.caption(f"locked_at: {locked_at}")
    else:
        st.success("🔓 Nessun lock attivo sul recinto.")

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

# --- 5. COSTRUZIONE MAPPA ---
c_lat, c_lon = 37.9747, 13.5753
if not df_mandria.empty and "lat" in df_mandria.columns and "lon" in df_mandria.columns:
    df_v = df_mandria.dropna(subset=["lat", "lon"]).query("lat != 0 and lon != 0")
    if not df_v.empty:
        c_lat, c_lon = df_v["lat"].mean(), df_v["lon"].mean()

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# --- BLOCCO SATELLITE GOOGLE RICHIESTO (FISSO) ---
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attr="Google Satellite",
    name="Google Satellite",
    overlay=False,
    control=False,
).add_to(m)

# Recinto salvato
if saved_coords:
    folium.Polygon(locations=saved_coords, color="yellow", weight=3, fill=True, fill_opacity=0.2).add_to(m)

# EXTRA: ridisegna il poligono temporaneo ad ogni rerun (se già chiuso almeno una volta)
if st.session_state.edit_mode and st.session_state.temp_coords:
    folium.Polygon(locations=st.session_state.temp_coords, color="cyan", weight=3, fill=True, fill_opacity=0.15).add_to(m)

for _, row in df_mandria.iterrows():
    if pd.notna(row["lat"]) and row["lat"] != 0:
        color = "green" if row["stato_recinto"] == "DENTRO" else "red"
        folium.Marker([row["lat"], row["lon"]], icon=folium.Icon(color=color, icon="info-sign")).add_to(m)

Draw(draw_options={"polyline": False, "rectangle": False, "circle": False, "marker": False, "polygon": True}).add_to(m)

# --- 6. LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
col_map, col_table = st.columns([3, 1])

with col_map:
    # MODIFICA 3) quando inizi: prova lock DB + disabilita refresh + avvia timer 5 min + key mappa stabile
    if not st.session_state.edit_mode:
        if st.button("🏗️ INIZIA DISEGNO NUOVO RECINTO"):
            ok = False
            try:
                ok = try_lock_recinto(1, st.session_state.session_id, LOCK_MINUTES)
            except Exception:
                ok = False

            if not ok:
                st.error("🔒 Qualcun altro sta modificando il recinto (lock attivo). Riprova tra poco.")
            else:
                st.session_state.edit_mode = True
                st.session_state.refresh_enabled = False
                st.session_state.temp_coords = None
                st.session_state.lock_expires_at = datetime.now() + timedelta(minutes=LOCK_MINUTES)

                # key nuova SOLO quando inizi un nuovo recinto (evita remount casuali)
                st.session_state.draw_session_id += 1
                st.rerun()

    # Timer visibile (client-side, NON fa rerun)
    if st.session_state.edit_mode and st.session_state.lock_expires_at:
        expires_iso = st.session_state.lock_expires_at.isoformat()
        components.html(
            f"""
            <div style="padding:10px;border:1px solid rgba(255,255,255,0.25);border-radius:8px;">
              <div style="font-weight:700;margin-bottom:6px;">⏱️ Tempo massimo per disegnare: {LOCK_MINUTES} minuti</div>
              <div>Tempo rimanente: <span id="cd" style="font-weight:800;">--:--</span></div>
            </div>
            <script>
              const expires = new Date("{expires_iso}").getTime();
              const el = document.getElementById("cd");
              function tick(){{
                const now = Date.now();
                let s = Math.floor((expires - now)/1000);
                if (s < 0) s = 0;
                const mm = String(Math.floor(s/60)).padStart(2,'0');
                const ss = String(s%60).padStart(2,'0');
                el.textContent = mm + ":" + ss;
              }}
              tick();
              setInterval(tick, 250);
            </script>
            """,
            height=80,
        )

    # MODIFICA EXTRA: key mappa basata su draw_session_id (stabile durante il disegno)
    map_key = f"main_map_{st.session_state.draw_session_id}"
    out = st_folium(m, width="100%", height=650, key=map_key)

    if out and out.get("all_drawings") and len(out["all_drawings"]) > 0:
        raw = out["all_drawings"][-1]["geometry"]["coordinates"]
        st.session_state.temp_coords = (
            [[p[1], p[0]] for p in raw[0]]
            if isinstance(raw[0][0], list)
            else [[p[1], p[0]] for p in raw]
        )

    # MODIFICA 4) quando salvi: salva, unlock, riabilita refresh, reset timer
    if st.session_state.edit_mode:
        if st.session_state.temp_coords:
            st.success("📍 Poligono pronto!")
            if st.button("💾 SALVA NUOVO RECINTO"):
                with conn.session as s:
                    s.execute(
                        text(
                            "INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) "
                            "ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"
                        ),
                        {"coords": json.dumps(st.session_state.temp_coords)},
                    )
                    s.commit()

                try:
                    unlock_recinto(1, st.session_state.session_id)
                except Exception:
                    pass

                st.session_state.edit_mode = False
                st.session_state.temp_coords = None
                st.session_state.refresh_enabled = True
                st.session_state.lock_expires_at = None
                st.rerun()
        else:
            st.info("Disegna sulla mappa e chiudi il poligono.")

with col_table:
    st.subheader("⚠️ Pannello Emergenze")
    df_emergenza = df_mandria[(df_mandria["stato_recinto"] == "FUORI") | (df_mandria.get("batteria", 100) <= 20)].copy()

    if not df_emergenza.empty:
        def genera_avvisi(row):
            avv = []
            if row.get("stato_recinto") == "FUORI":
                avv.append("🚨 FUORI")
            if row.get("batteria", 100) <= 20:
                avv.append("🪫 BATTERIA")
            return " + ".join(avv)

        df_emergenza["PROBLEMA"] = df_emergenza.apply(genera_avvisi, axis=1)
        st.error(f"Criticità: {len(df_emergenza)}")
        st.dataframe(df_emergenza[["nome", "PROBLEMA", "batteria"]], hide_index=True)
    else:
        st.success("✅ Tutto Sotto Controllo")

st.divider()
st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
