import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="SISTEMA MONITORAGGIO BOVINI H24")

# Inizializzazione stato del blocco refresh
if "lock_refresh" not in st.session_state:
    st.session_state.lock_refresh = False

# --- LOGICA REFRESH AUTOMATICO ---
# Il refresh avviene solo se lock_refresh è False
if not st.session_state.lock_refresh:
    st_autorefresh(interval=30000, key="datarefresh")
else:
    st.sidebar.warning("🔄 REFRESH BLOCCATO (Operazione in corso)")

# Connessione a Supabase tramite SQLAlchemy
conn = st.connection("postgresql", type="sql")

# --- FUNZIONI CARICAMENTO DATI ---
def load_data():
    try:
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        df_g = conn.query("SELECT * FROM gateway ORDER BY ultima_attivita DESC", ttl=0)
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = json.loads(df_r.iloc[0]['coords']) if not df_r.empty else []
        return df_m, df_g, coords
    except Exception as e:
        st.error(f"Errore database: {e}")
        return pd.DataFrame(), pd.DataFrame(), []

df_mandria, df_gateways, saved_coords = load_data()

# --- SIDEBAR: STATO INFRASTRUTTURA ---
st.sidebar.header("📡 STATO RETE LORA")
if not df_gateways.empty:
    for _, g in df_gateways.iterrows():
        status_color = "#28a745" if g['stato'] == 'ONLINE' else "#dc3545"
        icon = "✅" if g['stato'] == 'ONLINE' else "❌"
        st.sidebar.markdown(f"""
            <div style="border-left: 5px solid {status_color}; padding: 10px; background-color: rgba(255,255,255,0.05); border-radius: 5px; margin-bottom: 10px;">
                <b style="font-size: 14px;">{icon} {g['nome']}</b><br>
                <small>Stato: {g['stato']}</small>
            </div>
        """, unsafe_allow_html=True)

# --- SIDEBAR: GESTIONE (CON BLOCCO REFRESH AUTOMATICO) ---
st.sidebar.markdown("---")
st.sidebar.header("📋 GESTIONE")

# Expander 1: Nuovo Gateway
with st.sidebar.expander("➕ Configura Nuovo Gateway"):
    st.session_state.lock_refresh = True # Blocca finché l'expander è aperto
    g_id = st.text_input("ID Gateway (da TTN)")
    g_nome = st.text_input("Nome Località")
    if st.button("Registra Gateway"):
        if g_id and g_nome:
            with conn.session as s:
                s.execute(text("INSERT INTO gateway (id, nome, stato) VALUES (:id, :nome, 'ONLINE')"), {"id": g_id, "nome": g_nome})
                s.commit()
            st.session_state.lock_refresh = False
            st.rerun()

# Expander 2: Aggiungi Bovino
with st.sidebar.expander("➕ Aggiungi Bovino"):
    st.session_state.lock_refresh = True
    n_id = st.text_input("ID Tracker (es. tracker-luigi)")
    n_nome = st.text_input("Nome Animale")
    if st.button("Salva Bovino"):
        if n_id and n_nome:
            with conn.session as s:
                s.execute(text("INSERT INTO mandria (id, nome, lat, lon, stato_recinto) VALUES (:id, :nome, NULL, NULL, 'DENTRO') ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome"), {"id": n_id, "nome": n_nome})
                s.commit()
            st.session_state.lock_refresh = False
            st.rerun()

# Expander 3: Rimuovi Bovino
if not df_mandria.empty:
    with st.sidebar.expander("🗑️ Rimuovi Bovino"):
        st.session_state.lock_refresh = True
        bov_del = st.selectbox("Seleziona da eliminare:", df_mandria['nome'].tolist())
        if st.button("Elimina"):
            with conn.session as s:
                s.execute(text("DELETE FROM mandria WHERE nome=:nome"), {"nome": bov_del})
                s.commit()
            st.session_state.lock_refresh = False
            st.rerun()

# --- LOGICA MAPPA ---
df_valid = df_mandria.dropna(subset=['lat', 'lon'])
df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]
c_lat, c_lon = (df_valid['lat'].mean(), df_valid['lon'].mean()) if not df_valid.empty else (37.9747, 13.5753)

m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)
folium.TileLayer(
    tiles='https://mt1.google.com{x}&y={y}&z={z}',
    attr='Google Satellite',
    name='Google Satellite'
).add_to(m)

if saved_coords:
    folium.Polygon(locations=saved_coords, color="yellow", weight=3, fill=True, fill_opacity=0.2).add_to(m)

for _, row in df_mandria.iterrows():
    if pd.notna(row['lat']) and row['lat'] != 0:
        color = 'green' if row['stato_recinto'] == 'DENTRO' else 'red'
        folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color=color, icon='info-sign')).add_to(m)

Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)

# --- LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")

col_map, col_table = st.columns([3, 1])

with col_map:
    # PULSANTE CRITICO PER IL DISEGNO
    if not st.session_state.lock_refresh:
        if st.button("🏗️ CLICCA QUI PER DISEGNARE IL RECINTO (Blocca Refresh)"):
            st.session_state.lock_refresh = True
            st.rerun()
    else:
        if st.button("🔓 ANNULLA MODIFICHE E SBLOCCA REFRESH"):
            st.session_state.lock_refresh = False
            st.rerun()

    out = st_folium(m, width="100%", height=650, key="main_map")
    
    if out and out.get('all_drawings'):
        # Inversione coordinate per database
        raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
        new_poly = [[p[1], p[0]] for p in raw_coords]
        
        if st.button("💾 Conferma e Salva Nuovo Recinto"):
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), {"coords": json.dumps(new_poly)})
                s.commit()
            st.success("Recinto aggiornato!")
            st.session_state.lock_refresh = False
            st.rerun()

with col_table:
    st.subheader("⚠️ Pannello Emergenze")
    df_emergenza = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)].copy()
    if not df_emergenza.empty:
        st.error(f"Trovate {len(df_emergenza)} criticità!")
        st.dataframe(df_emergenza[['nome', 'batteria']], hide_index=True)
    else:
        st.success("✅ Tutto OK")

st.subheader("📝 Storico Aggiornamenti")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
