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

# Aggiornamento automatico della dashboard ogni 30 secondi
st_autorefresh(interval=30000, key="datarefresh")

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
                <small>Stato: {g['stato']}</small><br>
                <small>Ultimo segnale: {g['ultima_attivita'].strftime('%H:%M:%S')}</small>
            </div>
        """, unsafe_allow_html=True)

# --- SIDEBAR: GESTIONE MANDRIA ---
st.sidebar.markdown("---")
st.sidebar.header("📋 GESTIONE BOVINI")
with st.sidebar.expander("➕ Aggiungi/Rimuovi"):
    n_id = st.text_input("ID Tracker")
    n_nome = st.text_input("Nome Animale")
    if st.button("Salva Bovino"):
        with conn.session as s:
            s.execute(text("INSERT INTO mandria (id, nome, stato_recinto) VALUES (:id, :nome, 'DENTRO') ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome"), {"id": n_id, "nome": n_nome})
            s.commit()
        st.rerun()

# --- LOGICA MAPPA CORRETTA ---
m = folium.Map(location=[c_lat, c_lon], zoom_start=18, tiles=None)

folium.TileLayer(
    tiles='https://mt1.google.com{x}&y={y}&z={z}',
    attr='Google Satellite',
    name='Google Satellite',
    overlay=False, control=False
).add_to(m)

# 1. DISEGNO DEL RECINTO SALVATO (Semplice Poligono)
if saved_coords:
    folium.Polygon(
        locations=saved_coords,
        color="yellow",
        weight=3,
        fill=True,
        fill_opacity=0.2,
        tooltip="Recinto Attuale"
    ).add_to(m)

# 2. STRUMENTO DISEGNO (Versione Standard più stabile)
# Nota: Per modificare il recinto, ricalcalo sopra quello vecchio 
# o usa questa versione che non manda in crash il JSON encoder
Draw(
    export=False,
    position='topleft',
    draw_options={
        'polyline': False, 
        'rectangle': False, 
        'circle': False, 
        'marker': False, 
        'circlemarker': False, 
        'polygon': True
    },
    edit_options={'edit': True, 'remove': True} 
).add_to(m)

# Marker Bovini (Invariati)
for _, row in df_mandria.iterrows():
    if pd.notna(row['lat']) and row['lat'] != 0:
        color = 'green' if row['stato_recinto'] == 'DENTRO' else 'red'
        folium.Marker(
            [row['lat'], row['lon']],
            popup=f"<b>{row['nome']}</b>",
            icon=folium.Icon(color=color, icon='info-sign')
        ).add_to(m)

# --- LAYOUT ---
with col_map:
    # L'uso di st_folium con i parametri corretti risolve il crash
    out = st_folium(m, width=700, height=650, key="cow_map")
    
    if out and out.get('all_drawings'):
        # Logica di cattura identica a prima
        raw_coords = out['all_drawings'][-1]['geometry']['coordinates'][0]
        new_poly = [[p[1], p[0]] for p in raw_coords]
        
        if st.button("💾 SALVA NUOVO RECINTO"):
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), 
                          {"coords": json.dumps(new_poly)})
                s.commit()
            st.success("Recinto salvato!")
            st.rerun()


# 2. STRUMENTO DISEGNO COLLEGATO AL GRUPPO
Draw(
    export=False,
    position='topleft',
    draw_options={'polyline':False,'rectangle':False,'circle':False,'marker':False,'polygon':True},
    edit_options={'featureGroup': fg_edit, 'edit': True, 'remove': True} # ABILITA EDITING
).add_to(m)

# Marker Bovini
for _, row in df_mandria.iterrows():
    if pd.notna(row['lat']) and row['lat'] != 0:
        color = 'green' if row['stato_recinto'] == 'DENTRO' else 'red'
        folium.Marker(
            [row['lat'], row['lon']],
            popup=f"<b>{row['nome']}</b><br>Batt: {row['batteria']}%",
            icon=folium.Icon(color=color, icon='info-sign')
        ).add_to(m)

# --- LAYOUT PRINCIPALE ---
st.title("🛰️ MONITORAGGIO BOVINI H24")
st.info("💡 **Per modificare:** Clicca la matita (Edit), trascina i vertici gialli o i punti medi per aggiungerne nuovi. Clicca 'Save' nel menu matita e poi il tasto blu sotto.")

col_map, col_table = st.columns([3, 1])

with col_map:
    # Key fissa per evitare reset durante il refresh
    out = st_folium(m, width="100%", height=650, key="cow_map")
    
    # Cattura coordinate (Nuovo disegno o Modifica esistente)
    new_poly = None
    if out and out.get('all_drawings'):
        # Prende l'ultimo poligono attivo (sia esso nuovo o editato)
        last_drawing = out['all_drawings'][-1]
        raw_coords = last_drawing['geometry']['coordinates'][0]
        # Inversione Lon/Lat -> Lat/Lon per Supabase
        new_poly = [[p[1], p[0]] for p in raw_coords]
        
        # Pulizia: rimuove l'ultimo punto se duplicato (chiusura automatica GeoJSON)
        if len(new_poly) > 1 and new_poly[0] == new_poly[-1]:
            new_poly.pop()

    if new_poly:
        st.warning(f"Rilevata modifica al recinto ({len(new_poly)} vertici).")
        if st.button("💾 CONFERMA E SALVA NUOVO RECINTO"):
            with conn.session as s:
                s.execute(text("INSERT INTO recinti (id, nome, coords) VALUES (1, 'Pascolo', :coords) ON CONFLICT (id) DO UPDATE SET coords = EXCLUDED.coords"), 
                          {"coords": json.dumps(new_poly)})
                s.commit()
            st.success("Recinto salvato su Supabase!")
            st.rerun()

with col_table:
    st.subheader("⚠️ Emergenze")
    df_err = df_mandria[(df_mandria['stato_recinto'] == 'FUORI') | (df_mandria['batteria'] <= 20)]
    if not df_err.empty:
        st.error(f"Criticità: {len(df_err)}")
        st.dataframe(df_err[['nome', 'stato_recinto', 'batteria']], hide_index=True)
    else:
        st.success("Tutto OK")
    
    st.divider()
    with st.expander("🔍 Tutti i capi"):
        st.dataframe(df_mandria[['nome', 'stato_recinto', 'batteria']], hide_index=True)

st.subheader("📝 Storico Aggiornamenti")
st.dataframe(df_mandria, use_container_width=True, hide_index=True)
