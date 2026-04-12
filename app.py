import streamlit as st
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timedelta
import uuid

# --- 1. CONFIGURAZIONE E COSTANTI ---
st.set_page_config(layout="wide", page_title="MONITORAGGIO BOVINI H24")

if "map_center" not in st.session_state:
    st.session_state.map_center = [37.9747, 13.5753]
if "map_zoom" not in st.session_state:
    st.session_state.map_zoom = 18
if "refresh_enabled" not in st.session_state:
    st.session_state.refresh_enabled = True

LOCK_MINUTES = 5
now = datetime.now()
ora_log = now.strftime("%H:%M:%S")
conn = st.connection("postgresql", type="sql")

# --- 2. CARICAMENTO DATI ---
@st.cache_data(ttl=2)
def load_data():
    df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
    df_g = conn.query("SELECT * FROM gateway ORDER BY ultima_attivita DESC", ttl=0)
    df_r = conn.query("SELECT * FROM recinti ORDER BY id ASC", ttl=0)
    return df_m, df_g, df_r

df_mandria, df_gateways, df_recinti = load_data()

# --- 3. REFRESH ---
if st.session_state.refresh_enabled:
    st_autorefresh(interval=30000, key="timer_global")

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("📡 RETE E FREQUENZA")
    st.write(f"Ultimo Refresh: **{ora_log}**")
    
    # Frequenza
    curr_f = int(df_mandria['frequenza_desiderata'].iloc[0]) if not df_mandria.empty else 30
    new_f = st.slider("Minuti Invio (Normale)", 1, 120, curr_f)
    if st.button("Aggiorna Frequenza"):
        with conn.session as s:
            s.execute(text("UPDATE mandria SET frequenza_desiderata = :f"), {"f": new_f})
            s.commit()
        st.success(f"Impostato a {new_f} min")

    st.divider()
    st.subheader("🛠️ GESTIONE RECINTI")
    if not df_recinti.empty:
        r_nomi = df_recinti['nome'].tolist()
        r_sel = st.selectbox("Seleziona Pascolo:", r_nomi)
        
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
    with st.expander("🛰️ Stato Gateway"):
        for _, g in df_gateways.iterrows():
            st.write(f"{'✅' if g['stato']=='ONLINE' else '❌'} {g['nome']}")

# --- 5. MAPPA (GOOGLE SATELLITE + DRAW PLUGIN) ---
st.title("🛰️ SISTEMA MONITORAGGIO BOVINI")

# Creazione Mappa
m = folium.Map(
    location=st.session_state.map_center, 
    zoom_start=st.session_state.map_zoom, 
    tiles=None
)

folium.TileLayer(
    tiles='https://google.com{x}&y={y}&z={z}',
    attr='Google', name='Google Satellite', overlay=False, control=False
).add_to(m)

# Disegna Recinti esistenti
for _, r in df_recinti.iterrows():
    color = "green" if r['attivo'] else "orange"
    folium.Polygon(locations=json.loads(r['coords']), color=color, weight=2, fill=r['attivo'], fill_opacity=0.2, popup=r['nome']).add_to(m)

# Marker Bovini
for _, row in df_mandria.iterrows():
    if pd.notna(row.get("lat")):
        color = "green" if row["stato_recinto"] == "DENTRO" else "red"
        folium.Marker([row["lat"], row["lon"]], popup=row["nome"], icon=folium.Icon(color=color)).add_to(m)

# PLUGIN DI DISEGNO: permette di disegnare senza rerun
draw = Draw(
    draw_options={'polyline': False, 'rectangle': False, 'circle': False, 'circlemarker': False, 'marker': False},
    edit_options={'remove': True}
)
draw.add_to(m)

# Render unico della mappa
out = st_folium(m, width="100%", height=650, key="main_map")

# --- 6. LOGICA DI SALVATAGGIO E POSIZIONE ---
if out:
    # Salva posizione attuale per evitare il salto al refresh
    if out.get("center"):
        st.session_state.map_center = [out["center"]["lat"], out["center"]["lng"]]
    if out.get("zoom"):
        st.session_state.map_zoom = out["zoom"]

    # Se l'utente ha appena finito di disegnare un poligono
    if out.get("all_drawings") and len(out["all_drawings"]) > 0:
        # Prendi l'ultimo poligono disegnato
        last_draw = out["all_drawings"][-1]
        if last_draw['geometry']['type'] == 'Polygon':
            # Folium Draw restituisce [lon, lat], invertiamo per il tuo formato [lat, lon]
            raw_coords = last_draw['geometry']['coordinates'][0]
            clean_coords = [[p[1], p[0]] for p in raw_coords]
            
            st.subheader("💾 Salva Nuovo Recinto")
            nome_nuovo = st.text_input("Nome Pascolo:", value=f"Recinto {len(df_recinti)+1}")
            
            if st.button("Conferma Salvataggio"):
                try:
                    with conn.session as s:
                        # Inserisce nuovo (non attivo di default come richiesto)
                        s.execute(text("INSERT INTO recinti (nome, coords, attivo) VALUES (:n, :c, false)"),
                                  {"n": nome_nuovo, "c": json.dumps(clean_coords)})
                        s.commit()
                    st.success(f"Recinto '{nome_nuovo}' salvato! Attivalo dalla sidebar.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")

st.divider()
st.subheader("📝 Storico Mandria")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
