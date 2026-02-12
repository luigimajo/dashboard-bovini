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

# Aggiorna l'interfaccia ogni 30 secondi per mostrare le nuove posizioni ricevute da TTN
st_autorefresh(interval=30000, key="datarefresh")

# Connessione al database Supabase (usa i secrets configurati)
conn = st.connection("postgresql", type="sql")

# --- CARICAMENTO DATI ---
def get_data():
    try:
        # Carichiamo lo stato aggiornato della mandria (scritto dal Webhook di TTN)
        df = conn.query("SELECT * FROM mandria ORDER BY id", ttl=0)
        
        # Carichiamo il recinto esistente
        df_rec = conn.query("SELECT coords FROM recinti WHERE id = 1", ttl=0)
        coords = json.loads(df_rec.iloc[0]['coords']) if not df_rec.empty else []
        
        return df, coords
    except Exception as e:
        st.error(f"Errore caricamento dati: {e}")
        return pd.DataFrame(), []

df_mandria, saved_coords = get_data()

# --- SIDEBAR: GESTIONE ANAGRAFICA ---
st.sidebar.header("📋 GESTIONE MANDRIA")

# Aggiunta nuovo tracker
with st.sidebar.expander("➕ Aggiungi Bovino"):
    n_id = st.text_input("ID Tracker (es. tracker-luigi)")
    n_nome = st.text_input("Nome/Marca Auricolare")
    if st.button("Salva Bovino"):
        if n_id and n_nome:
            with conn.session as s:
                s.execute(
                    text("INSERT INTO mandria (id, nome, lat, lon, stato_recinto, batteria) "
                         "VALUES (:id, :nome, 0, 0, 'DENTRO', 100) "
                         "ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome"),
                    {"id": n_id, "nome": n_nome}
                )
                s.commit()
            st.rerun()

# Rimozione tracker
if not df_mandria.empty:
    with st.sidebar.expander("🗑️ Rimuovi Bovino"):
        bov_del = st.selectbox("Seleziona da eliminare:", df_mandria['nome'].tolist())
        if st.button("Elimina"):
            with conn.session as s:
                s.execute(text("DELETE FROM mandria WHERE nome=:nome"), {"nome": bov_del})
                s.commit()
            st.rerun()

# --- LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.info("Il sistema riceve i dati dai gateway Dragino anche se questa pagina è chiusa.")

col_map, col_table = st.columns([3, 1])

with col_map:
    # Centriamo la mappa sull'ultima posizione nota o su una coordinata di default
    start_lat = df_mandria['lat'].mean() if not df_mandria.empty else 45.1743
    start_lon = df_mandria['lon'].mean() if not df_mandria.empty else 9.2394
    
    m = folium.Map(location=[start_lat, start_lon], zoom_start=16)
    
    # Layer Satellite Google
    folium.TileLayer(
             
    #   tiles='https://mt1.google.com{x}&y={y}&z={z}',
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
 
        attr='Google Satellite',
        name='Google Satellite',
        overlay=False,
        control=False
    ).add_to(m)

    # Disegna il recinto salvato
    if saved_coords:
        folium.Polygon(
            locations=saved_coords,
            color="yellow",
            weight=3,
            fill=True,
            fill_opacity=0.2,
            popup="Area Pascolo"
        ).add_to(m)

    # Posiziona i bovini sulla mappa
    for _, row in df_mandria.iterrows():
        # Colore marker basato sullo stato calcolato da Supabase
        col_m = 'green' if row['stato_recinto'] == "DENTRO" else 'red'
        
        info_popup = f"<b>{row['nome']}</b><br>Batteria: {row['batteria']}%<br>Aggiornato: {row['ultimo_aggiornamento']}"
        
        folium.Marker(
            [row['lat'], row['lon']], 
            popup=info_popup,
            tooltip=row['nome'],
            icon=folium.Icon(color=col_m, icon='info-sign')
        ).add_to(m)

    # Strumento per disegnare nuovi recinti
    Draw(draw_options={
        'polyline':False, 'rectangle':False, 'circle':False, 'marker':False, 'circlemarker':False, 'polygon':True
    }).add_to(m)
    
    # Visualizzazione mappa
    out = st_folium(m, width="100%", height=600, key="main_map")

    # Salvataggio nuovo recinto disegnato
    if out and out.get('all_drawings'):
        # Estraiamo le coordinate (invertendo lat/lon da GeoJSON a Folium)
        new_poly = [[p[1], p[0]] for p in out['all_drawings'][-1]['geometry']['coordinates'][0]]
        if st.button("💾 Salva Nuovo Recinto"):
            with conn.session as s:
                s.execute(
                    text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Recinto Principale', :coords) "
                         "ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"),
                    {"coords": json.dumps(new_poly)}
                )
                s.commit()
            st.success("Recinto aggiornato! Il database ricalcolerà gli allarmi automaticamente.")
            st.rerun()

with col_table:
    st.subheader("📊 Stato Mandria")
    if not df_mandria.empty:
        # Mostriamo una versione compatta della tabella
        st.dataframe(
            df_mandria[['nome', 'stato_recinto', 'batteria']], 
            hide_index=True,
            use_container_width=True
        )
    else:
        st.write("Nessun tracker registrato.")

st.write("---")
# Log completo in fondo alla pagina
st.subheader("📝 Dettaglio Ultimi Aggiornamenti")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
