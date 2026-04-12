import dash
from dash import html, dcc, Input, Output, State
import dash_leaflet as dl
import pandas as pd
import json
from sqlalchemy import create_engine, text
from datetime import datetime

# --- CONFIGURAZIONE DATABASE ---
# Sostituisci con la tua stringa di connessione Supabase
DB_URL = "postgresql://postgres:TUA_PASSWORD@IL_TUO_HOST:5432/postgres"
engine = create_engine(DB_URL)

# Inizializzazione App
app = dash.Dash(__name__, 
                title="SISTEMA MONITORAGGIO BOVINI H24",
                external_scripts=["https://cloudflare.com"])
server = app.server # Necessario per il Procfile (gunicorn)

# --- LAYOUT ---
app.layout = html.Div([
    # Timer per aggiornamento dati (30 secondi)
    dcc.Interval(id='interval-refresh', interval=30*1000, n_intervals=0),
    
    # Intestazione
    html.Div([
        html.H2("🛰️ MONITORAGGIO BOVINI H24 - DASH VERSION", style={'color': '#2c3e50', 'margin-bottom': '0'}),
        html.P(id='last-update-text', style={'color': '#7f8c8d'})
    ], style={'padding': '15px', 'backgroundColor': 'white', 'textAlign': 'center', 'boxShadow': '0 2px 5px rgba(0,0,0,0.1)'}),

    html.Div([
        # --- COLONNA SINISTRA: MAPPA ---
        html.Div([
            dl.Map([
                # Google Satellite Layer
                dl.TileLayer(
                    url='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
               #     url='https://google.com{x}&y={y}&z={z}',
                    attribution='Google Satellite',
                    id="satellite-layer"
                ),
                
                # Layer per Recinti (Popolati dal database)
                dl.LayerGroup(id='layer-recinti'),
                
                # Layer per Bovini (Popolati dal database)
                dl.LayerGroup(id='layer-bovini'),
                
                # Tool di Disegno (Poligono)
                dl.EditControl(
                    id="edit-control",
                    draw={
                        "polyline": False, "rectangle": False, "circle": False, 
                        "marker": False, "circlemarker": False,
                        "polygon": {"allowIntersection": False, "drawError": {"color": "#e1e1e1", "message": "No!"}}
                    }
                )
            ], 
            id='main-map', 
            center=[37.9747, 13.5753], 
            zoom=18, 
            style={'width': '100%', 'height': '85vh'})
        ], style={'width': '75%', 'display': 'inline-block', 'padding': '5px'}),

        # --- COLONNA DESTRA: CONTROLLI ---
        html.Div([
            html.Div([
                html.H4("⏱️ Frequenza Tracker"),
                dcc.Slider(1, 60, 30, step=1, id='slider-freq', marks={1: '1m', 30: '30m', 60: '60m'}),
                html.Button("Invia Comando", id='btn-save-freq', className="btn-save", style={'width': '100%', 'marginTop': '10px'}),
                html.Div(id='msg-freq', style={'fontSize': '12px', 'marginTop': '5px'})
            ], className="control-card"),

            html.Div([
                html.H4("🗺️ Nuovo Pascolo"),
                dcc.Input(id='input-nome-recinto', type='text', placeholder='Nome recinto...', style={'width': '90%'}),
                html.P("Disegna il poligono sulla mappa e premi Salva:"),
                html.Button("💾 Salva Nuovo Recinto", id='btn-save-recinto', n_clicks=0, style={'width': '100%', 'backgroundColor': '#28a745', 'color': 'white'}),
                html.Div(id='msg-recinto', style={'fontSize': '12px', 'marginTop': '5px'})
            ], className="control-card", style={'marginTop': '20px'}),

            html.Div([
                html.H4("📡 Gateway & Info"),
                html.Div(id='lista-gateway', style={'maxHeight': '200px', 'overflowY': 'auto'})
            ], className="control-card", style={'marginTop': '20px'})
            
        ], style={'width': '22%', 'display': 'inline-block', 'verticalAlign': 'top', 'padding': '10px'})
    ], style={'display': 'flex'})
], style={'backgroundColor': '#f4f7f6', 'minHeight': '100vh'})

# --- CALLBACK: AGGIORNAMENTO DATI (BOVINI, RECINTI, GATEWAY) ---
@app.callback(
    [Output('layer-bovini', 'children'),
     Output('layer-recinti', 'children'),
     Output('lista-gateway', 'children'),
     Output('last-update-text', 'children')],
    [Input('interval-refresh', 'n_intervals')]
)
def refresh_data(n):
    with engine.connect() as conn:
        df_m = pd.read_sql("SELECT * FROM mandria", conn)
        df_r = pd.read_sql("SELECT * FROM recinti", conn)
        df_g = pd.read_sql("SELECT * FROM gateway", conn)

    # 1. Marker Bovini
    bovini_markers = []
    for _, b in df_m.iterrows():
        if b['lat'] and b['lon']:
            color = "green" if b['stato_recinto'] == 'DENTRO' else "red"
            bovini_markers.append(dl.Marker(
                position=[b['lat'], b['lon']],
                children=[dl.Tooltip(f"{b['nome']} - Batt: {b['batteria']}%")],
                # Usiamo icone colorate standard Leaflet
                icon={"iconUrl": f"https://rawgit.com{color}.png", "iconSize": [25, 41]}
            ))

    # 2. Poligoni Recinti
    recinti_poligoni = []
    for _, r in df_r.iterrows():
        # In Dash-Leaflet le posizioni sono già [lat, lon]
        recinti_poligoni.append(dl.Polygon(
            positions=json.loads(r['coords']),
            color="green" if r['attivo'] else "orange",
            fill=r['attivo'],
            fillOpacity=0.2,
            children=[dl.Tooltip(r['nome'])]
        ))

    # 3. Lista Gateway
    gateway_list = [html.Div([
        html.Span("● ", style={'color': 'green' if g['stato'] == 'ONLINE' else 'red'}),
        html.Span(f"{g['nome']}")
    ], style={'padding': '5px'}) for _, g in df_g.iterrows()]

    update_time = f"Ultimo aggiornamento: {datetime.now().strftime('%H:%M:%S')}"
    
    return bovini_markers, recinti_poligoni, gateway_list, update_time

# --- CALLBACK: SALVATAGGIO NUOVO RECINTO ---
@app.callback(
    Output('msg-recinto', 'children'),
    Input('btn-save-recinto', 'n_clicks'),
    [State('edit-control', 'geojson'),
     State('input-nome-recinto', 'value')]
)
def save_fence(n_clicks, geojson, nome):
    if n_clicks > 0 and geojson:
        try:
            # Dash-Leaflet EditControl restituisce GeoJSON standard: [lon, lat]
            # Dobbiamo invertire in [lat, lon] per il tuo database
            raw_coords = geojson['features'][-1]['geometry']['coordinates'][0]
            clean_coords = [[p[1], p[0]] for p in raw_coords]
            
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO recinti (nome, coords, attivo) VALUES (:n, :c, false)"),
                             {"n": nome if nome else "Nuovo Pascolo", "c": json.dumps(clean_coords)})
            return "✅ Recinto salvato!"
        except Exception as e:
            return f"❌ Errore: {str(e)}"
    return ""

# --- CALLBACK: AGGIORNA FREQUENZA ---
@app.callback(
    Output('msg-freq', 'children'),
    Input('btn-save-freq', 'n_clicks'),
    State('slider-freq', 'value')
)
def update_frequency(n_clicks, value):
    if n_clicks and n_clicks > 0:
        with engine.begin() as conn:
            conn.execute(text("UPDATE mandria SET frequenza_desiderata = :v"), {"v": value})
        return f"✅ Frequenza impostata a {value} min"
    return ""

if __name__ == '__main__':
    app.run_server(debug=False)
