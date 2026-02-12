import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import json
import pandas as pd
from sqlalchemy import text
from streamlit_autorefresh import st_autorefresh

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(layout="wide", page_title="MONITORAGGIO BOVINI - Cloud Mode")

# Aggiornamento automatico ogni 30 secondi
st_autorefresh(interval=30000, key="datarefresh")

# Connessione a Supabase
conn = st.connection("postgresql", type="sql")

# --- CARICAMENTO DATI ---
def get_data():
    try:
        # Carichiamo la mandria
        df = conn.query("SELECT * FROM mandria ORDER BY id", ttl=0)
        # Carichiamo il recinto
        df_rec = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = json.loads(df_rec.iloc[0]['coords']) if not df_rec.empty else []
        return df, coords
    except Exception as e:
        return pd.DataFrame(), []

df_mandria, saved_coords = get_data()

# --- SIDEBAR: GESTIONE ANAGRAFICA ---
st.sidebar.header("📋 GESTIONE MANDRIA")

with st.sidebar.expander("➕ Aggiungi Bovino"):
    n_id = st.text_input("ID Tracker (es. tracker-luigi)")
    n_nome = st.text_input("Nome/Marca")
    if st.button("Salva Bovino"):
        if n_id and n_nome:
            with conn.session as s:
                # Inseriamo coordinate nulle invece di 0,0 per evitare l'Atlantico
                s.execute(
                    text("INSERT INTO mandria (id, nome, lat, lon, stato_recinto, batteria) "
                         "VALUES (:id, :nome, NULL, NULL, 'DENTRO', 100) "
                         "ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome"),
                    {"id": n_id, "nome": n_nome}
                )
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

# --- LOGICA COORDINATE MAPPA ---
# Escludiamo i valori nulli o 0.0 dal calcolo del centro mappa
df_posizionati = df_mandria.dropna(subset=['lat', 'lon'])
df_posizionati = df_posizionati[(df_posizionati['lat'] != 0) & (df_posizionati['lon'] != 0)]

if not df_posizionati.empty:
    center_lat = df_posizionati['lat'].mean()
    center_lon = df_posizionati['lon'].mean()
else:
    # Se non ci sono bovini con segnale GPS, centra sulla tua zona (es. Sicilia o tua stalla)
    center_lat, center_lon = 45.1743, 9.2394 

# --- LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")

col_map, col_table = st.columns([3, 1])

with col_map:
    # Creazione mappa base
    m = folium.Map(location=[center_lat, center_lon], zoom_start=17, tiles=None)

    # Vista Satellite Google
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google Satellite',
        name='Google Satellite',
        overlay=False,
        control=False
    ).add_to(m)

    # Disegna Recinto
    if saved_coords:
        folium.Polygon(
            locations=saved_coords,
            color="yellow",
            weight=4,
            fill=True,
            fill_opacity=0.2
        ).add_to(m)

    # Disegna Bovini
    for _, row in df_mandria.iterrows():
        # Saltiamo il marker se non c'è ancora una posizione valida
        if pd.isna(row['lat']) or row['lat'] == 0:
            continue
            
        col_m = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        folium.Marker(
            [row['lat'], row['lon']], 
            popup=f"{row['nome']} ({row['batteria']}%)",
            icon=folium.Icon(color=col_m, icon='info-sign')
        ).add_to(m)

    # Strumento per disegnare
    Draw(draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True}).add_to(m)
    
    # Render Mappa
    out = st_folium(m, width="100%", height=600, key="main_map")

    # Logica salvataggio recinto (inverte Lon/Lat del disegno in Lat/Lon per Folium)
    if out and out.get('all_drawings'):
        # Prendiamo l'ultimo disegno
        raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
        # Invertiamo ogni coppia da [Lon, Lat] a [Lat, Lon]
        new_poly = [[p[1], p[0]] for p in raw_coords]
        
        if st.button("💾 Salva Nuovo Recinto"):
            with conn.session as s:
                s.execute(
                    text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"),
                    {"coords": json.dumps(new_poly)}
                )
                s.commit()
            st.success("Recinto salvato correttamente!")
            st.rerun()

with col_table:
    st.subheader("📊 Stato")
    if not df_mandria.empty:
        st.dataframe(df_mandria[['nome', 'stato_recinto', 'batteria']], hide_index=True)
    else:
        st.write("Mandria vuota")

st.write("---")
st.dataframe(df_mandria, use_container_width=True)
