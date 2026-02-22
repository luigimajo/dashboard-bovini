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

# --- STATO EDIT RECINTO (pausa refresh durante disegno) ---
if "editing_poly" not in st.session_state:
    st.session_state["editing_poly"] = False

# >>> bozza poligono (persistenza tra rerun)
if "draft_poly" not in st.session_state:
    st.session_state["draft_poly"] = None

# Aggiornamento automatico della dashboard ogni 30 secondi (disabilitato in edit)
if not st.session_state["editing_poly"]:
    st_autorefresh(interval=30000, key="datarefresh")

# Connessione a Supabase tramite SQLAlchemy
conn = st.connection("postgresql", type="sql")

# --- FUNZIONI CARICAMENTO DATI ---
def load_data():
    try:
        # Carichiamo i Bovini
        df_m = conn.query("SELECT * FROM mandria ORDER BY nome ASC", ttl=0)
        # Carichiamo i Gateway
        df_g = conn.query("SELECT * FROM gateway ORDER BY ultima_attivita DESC", ttl=0)
        # Carichiamo il Recinto
        df_r = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = json.loads(df_r.iloc[0]['coords']) if not df_r.empty else []
        return df_m, df_g, coords
    except Exception as e:
        st.error(f"Errore database: {e}")
        return pd.DataFrame(), pd.DataFrame(), []

df_mandria, df_gateways, saved_coords = load_data()

# --- SIDEBAR: STATO INFRASTRUTTURA (GATEWAY) ---
st.sidebar.header("📡 STATO RETE LORA")
if not df_gateways.empty:
    for _, g in df_gateways.iterrows():
        status_color = "#28a745" if g['stato'] == 'ONLINE' else "#dc3545"
        icon = "✅" if g['stato'] == 'ONLINE' else "❌"
        st.sidebar.markdown(f"""
            <div style="border-left: 5px solid {status_color}; padding: 10px; background-color: rgba(255,255,255,0.05); border-radius: 5px; margin-bottom: 10px;">
                <b style="font-size: 14px;">{icon} {g['nome']}</b><br>
                <small>Stato: {g['stato']}</small><br>
                <small>Ultimo segnale: {g['ultima_attivita'].strftime('%H:%M:%S')}</small>
            </div>
        """, unsafe_allow_html=True)
else:
    st.sidebar.info("Nessun Gateway configurato.")

with st.sidebar.expander("➕ Configura Nuovo Gateway"):
    g_id = st.text_input("ID Gateway (da TTN)")
    g_nome = st.text_input("Nome Località (es. Stalla Alta)")
    if st.button("Registra Gateway"):
        if g_id and g_nome:
            with conn.session as s:
                s.execute(text("INSERT INTO gateway (id, nome, stato) VALUES (:id, :nome, 'ONLINE')"), {"id": g_id, "nome": g_nome})
                s.commit()
            st.rerun()

# --- SIDEBAR: GESTIONE MANDRIA ---
st.sidebar.markdown("---")
st.sidebar.header("📋 GESTIONE BOVINI")
with st.sidebar.expander("➕ Aggiungi Bovino"):
    n_id = st.text_input("ID Tracker (es. tracker-luigi)")
    n_nome = st.text_input("Nome Animale")
    if st.button("Salva Bovino"):
        if n_id and n_nome:
            with conn.session as s:
                s.execute(text("INSERT INTO mandria (id, nome, lat, lon, stato_recinto) VALUES (:id, :nome, NULL, NULL, 'DENTRO') ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome"), {"id": n_id, "nome": n_nome})
                s.commit()
            st.rerun()

if not df_mandria.empty:
    with st.sidebar.expander("🗑️ Rimuovi Bovino"):
        bov_del = st.selectbox("Seleziona da eliminare:", df_mandria['nome'].tolist())
        if st.button("Elimina"):
            with conn.session as s:
                s.execute(text("DELETE FROM mandria WHERE nome=:nome"), {"nome": bov_del})
                s.commit()
            st.rerun()

# --- LOGICA MAPPA ---
# Escludiamo punti 0,0 o NULL per centrare la mappa
df_valid = df_mandria.dropna(subset=['lat', 'lon'])
df_valid = df_valid[(df_valid['lat'] != 0) & (df_valid['lon'] != 0)]

if not df_valid.empty:
    c_lat, c_lon = df_valid['lat'].mean(), df_valid['lon'].mean()
else:
    c_lat, c_lon = 37.9747, 13.5753 # Coordinate di default

# Creazione Oggetto Folium
m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

# Layer Satellite Google
folium.TileLayer(
    tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
    attr='Google Satellite',
    name='Google Satellite',
    overlay=False,
    control=False
).add_to(m)

# Disegno Recinto salvato
if saved_coords:
    folium.Polygon(locations=saved_coords, color="yellow", weight=3, fill=True, fill_opacity=0.2).add_to(m)

# >>> Disegno Recinto in BOZZA (persistente finché non salvi/annulli)
if st.session_state["draft_poly"]:
    folium.Polygon(
        locations=st.session_state["draft_poly"],
        color="black",
        weight=3,
        fill=True,
        fill_opacity=0.15
    ).add_to(m)

# Marker Bovini
for _, row in df_mandria.iterrows():
    if pd.notna(row['lat']) and row['lat'] != 0:
        color = 'green' if row['stato_recinto'] == 'DENTRO' else 'red'
        folium.Marker(
            [row['lat'], row['lon']],
            popup=f"<b>{row['nome']}</b><br>Batteria: {row['batteria']}%<br>Stato: {row['stato_recinto']}",
            icon=folium.Icon(color=color, icon='info-sign')
        ).add_to(m)

# Strumento Disegno
Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)

# --- LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.info("I dati vengono ricevuti e processati da Supabase anche quando questa pagina è chiusa.")

# --- CONTROLLO MODALITÀ EDIT (pausa refresh) ---
colA, colB, colC = st.columns([1, 1, 3])
with colA:
    if not st.session_state["editing_poly"]:
        if st.button("✏️ Modifica recinto (pausa refresh)"):
            st.session_state["editing_poly"] = True
            st.session_state["draft_poly"] = None
            st.rerun()
with colB:
    if st.session_state["editing_poly"]:
        if st.button("❌ Annulla modifica"):
            st.session_state["editing_poly"] = False
            st.session_state["draft_poly"] = None
            st.rerun()

if st.session_state["editing_poly"]:
    st.warning("Modalità modifica attiva: refresh automatico DISABILITATO finché non salvi o annulli.")

col_map, col_table = st.columns([3, 1])

with col_map:
    out = st_folium(m, width="100%", height=650, key="main_map")

    # >>> Salviamo SEMPRE la bozza quando chiudi la poligonale (così non sparisce al rerun)
    if out and out.get('all_drawings'):
        raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
        new_poly = [[p[1], p[0]] for p in raw_coords]  # Lon/Lat -> Lat/Lon
        st.session_state["draft_poly"] = new_poly

        if st.button("💾 Conferma e Salva Nuovo Recinto"):
            with conn.session as s:
                s.execute(
                    text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) "
                         "ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"),
                    {"coords": json.dumps(new_poly)}
                )
                s.commit()
            st.success("Recinto aggiornato!")
            st.session_state["editing_poly"] = False
            st.session_state["draft_poly"] = None
            st.rerun()

with col_table:
    st.subheader("⚠️ Pannello Emergenze")

    df_emergenza = df_mandria[
        (df_mandria['stato_recinto'] == 'FUORI') | 
        (df_mandria['batteria'] <= 20)
    ].copy()

    if not df_emergenza.empty:
        def genera_avvisi(row):
            avvisi = []
            if row['stato_recinto'] == 'FUORI':
                avvisi.append("🚨 FUORI")
            if row['batteria'] <= 20:
                avvisi.append("🪫 BATTERIA")
            return " + ".join(avvisi)

        df_emergenza['PROBLEMA'] = df_emergenza.apply(genera_avvisi, axis=1)

        st.error(f"Trovate {len(df_emergenza)} criticità!")
        st.dataframe(
            df_emergenza[['nome', 'PROBLEMA', 'batteria', 'ultimo_aggiornamento']], 
            hide_index=True, 
            use_container_width=True
        )
    else:
        st.success("✅ Tutto sotto controllo: mandria nel recinto e batterie cariche.")

    st.divider()

    with st.expander("🔍 Stato complessivo (Tutti i 150 capi)"):
        st.dataframe(
            df_mandria.sort_values(by='nome')[['nome', 'stato_recinto', 'batteria']], 
            hide_index=True,
            use_container_width=True
        )

st.write("---")
st.subheader("📝 Storico Aggiornamenti")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
