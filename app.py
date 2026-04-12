import dash
from dash import html, dcc, Input, Output, State, callback_context
import dash_leaflet as dl
import dash_leaflet.express as dlx
import pandas as pd
import json
from sqlalchemy import create_param, text, create_engine
from datetime import datetime

# --- CONFIGURAZIONE DATABASE (Usa la tua stringa Supabase) ---
DB_URL = "postgresql://postgres:[PASSWORD]@[HOST]:5432/postgres"
engine = create_engine(DB_URL)

app = dash.Dash(__name__, title="Monitoraggio Bovini Dash")

# --- LAYOUT DELL'APP ---
app.layout = html.Div([
    # Timer per aggiornamento bovini (30 secondi) senza ricaricare la pagina
    dcc.Interval(id='interval-bovini', interval=30*1000, n_intervals=0),
    
    html.Div([
        html.H1("🛰️ SISTEMA MONITORAGGIO BOVINI H24", style={'textAlign': 'center'}),
    ], style={'padding': '10px'}),

    html.Div([
        # --- COLONNA SINISTRA: MAPPA ---
        html.Div([
            dl.Map([
                # LAYER SATELLITE GOOGLE
                dl.TileLayer(
                    url='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
                    attribution='Google Satellite'
                ),
                
                # Layer per i Recinti
                html.Div(id='layer-recinti'),
                
                # Layer per i Bovini
                html.Div(id='layer-bovini'),
                
                # TOOL DI DISEGNO (Integrato, non si resetta col refresh)
                dl.EditControl(id="edit-control", draw={'polyline':False, 'circle':False, 'marker':False, 'circlemarker':False, 'rectangle':False})
            ], 
            id='main-map', 
            center=[37.9747, 13.5753], 
            zoom=18, 
            style={'width': '100%', 'height': '70vh'})
        ], style={'width': '75%', 'display': 'inline-block', 'verticalAlign': 'top'}),

        # --- COLONNA DESTRA: CONTROLLI ---
        html.Div([
            html.H3("⚙️ Pannello Controllo"),
            html.Label("Frequenza Tracker (min):"),
            dcc.Slider(1, 60, 30, id='slider-freq', marks={i: str(i) for i in [1, 15, 30, 60]}),
            html.Button("Salva Frequenza", id='btn-save-freq', n_clicks=0),
            html.Hr(),
            html.H4("🛠️ Nuovo Recinto"),
            dcc.Input(id='input-nome-recinto', placeholder='Nome Pascolo', type='text'),
            html.Button("💾 Salva Recinto Disegnato", id='btn-save-recinto', n_clicks=0),
            html.Div(id='msg-salvataggio'),
            html.Hr(),
            html.H4("📡 Stato Gateway"),
            html.Div(id='lista-gateway')
        ], style={'width': '23%', 'display': 'inline-block', 'padding': '1%', 'backgroundColor': '#f9f9f9', 'height': '70vh', 'marginLeft': '1%'})
    ])
], style={'padding': '20px'})

# --- CALLBACK: AGGIORNAMENTO BOVINI E RECINTI ---
# Questa funzione viene chiamata ogni 30s o all'avvio
@app.callback(
    [Output('layer-bovini', 'children'),
     Output('layer-recinti', 'children'),
     Output('lista-gateway', 'children')],
    [Input('interval-bovini', 'n_intervals')]
)
def update_data(n):
    with engine.connect() as conn:
        df_m = pd.read_sql("SELECT * FROM mandria", conn)
        df_r = pd.read_sql("SELECT * FROM recinti", conn)
        df_g = pd.read_sql("SELECT * FROM gateway", conn)

    # Marker Bovini
    markers = []
    for _, b in df_m.iterrows():
        color = "green" if b['stato_recinto'] == 'DENTRO' else "red"
        markers.append(dl.Marker(position=[b['lat'], b['lon']], children=[
            dl.Tooltip(f"{b['nome']} ({b['batteria']}%)")
        ], icon={'iconUrl': f'https://githubusercontent.com{color}.png', 'iconSize': [25, 41]}))

    # Poligoni Recinti
    poligoni = []
    for _, r in df_r.iterrows():
        coords = json.loads(r['coords'])
        color = "green" if r['attivo'] else "orange"
        poligoni.append(dl.Polygon(positions=coords, color=color, fill=r['attivo']))

    # Lista Gateway
    gateways = [html.P(f"{'✅' if g['stato']=='ONLINE' else '❌'} {g['nome']}") for _, g in df_g.iterrows()]

    return markers, poligoni, gateways

# --- CALLBACK: SALVATAGGIO RECINTO ---
@app.callback(
    Output('msg-salvataggio', 'children'),
    Input('btn-save-recinto', 'n_clicks'),
    State('edit-control', 'geojson'),
    State('input-nome-recinto', 'value')
)
def save_new_fence(n_clicks, geojson, nome):
    if n_clicks > 0 and geojson:
        # Estrazione coordinate dal disegno Dash-Leaflet
        coords = geojson['features'][-1]['geometry']['coordinates'][0]
        # Invertiamo da [lon, lat] a [lat, lon] per il tuo DB
        clean_coords = [[p[1], p[0]] for p in coords]
        
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO recinti (nome, coords, attivo) VALUES (:n, :c, false)"),
                         {"n": nome if nome else "Nuovo Pascolo", "c": json.dumps(clean_coords)})
        return "✅ Recinto salvato correttamente!"
    return ""

if __name__ == '__main__':
    app.run_server(debug=True)
