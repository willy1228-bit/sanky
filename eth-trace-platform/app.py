import dash
from dash import dcc, html, Input, Output, State
import pandas as pd
import requests
import plotly.graph_objects as go
import datetime
import os

app = dash.Dash(__name__)
server = app.server  # 給 Render / Gunicorn 用

app.layout = html.Div([
    html.H1("ETH 交易追蹤平台"),

    html.Div([
        html.Label("Etherscan API Key"),
        dcc.Input(id="api-key", type="text", placeholder="輸入 API key", value="", style={"width": "300px"}),

        html.Label("起始錢包地址"),
        dcc.Input(id="start-address", type="text", placeholder="輸入地址", value="", style={"width": "300px"}),

        html.Label("最大層級"),
        dcc.Input(id="max-depth", type="number", value=1),

        html.Label("方向"),
        dcc.Dropdown(
            id="direction",
            options=[
                {"label": "轉入", "value": "in"},
                {"label": "轉出", "value": "out"},
                {"label": "雙向", "value": "both"},
            ],
            value="both"
        ),

        html.Label("開始日期"),
        dcc.Input(id="start-date", type="date", value=str(datetime.date.today() - datetime.timedelta(days=30))),

        html.Label("結束日期"),
        dcc.Input(id="end-date", type="date", value=str(datetime.date.today())),

        html.Button("開始追蹤", id="start-btn", n_clicks=0)
    ], style={"display": "grid", "gap": "8px", "max-width": "400px"}),

    html.Div(id="status-output", style={"margin-top": "20px", "whiteSpace": "pre-wrap"}),

    html.Div([
        html.Button("+1 層級", id="add-level", n_clicks=0),
        html.Button("-1 層級", id="remove-level", n_clicks=0)
    ], style={"margin-top": "20px"}),

    dcc.Graph(id="sankey-graph")
])

def fetch_transactions(address, api_key, start_block=0, end_block=99999999, direction="both"):
    url = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&startblock={start_block}&endblock={end_block}&sort=asc&apikey={api_key}"
    resp = requests.get(url).json()
    if resp.get("status") != "1":
        return []
    txs = resp["result"]
    if direction == "in":
        return [t for t in txs if t["to"].lower() == address.lower()]
    elif direction == "out":
        return [t for t in txs if t["from"].lower() == address.lower()]
    return txs

@app.callback(
    Output("status-output", "children"),
    Output("sankey-graph", "figure"),
    Input("start-btn", "n_clicks"),
    State("api-key", "value"),
    State("start-address", "value"),
    State("max-depth", "value"),
    State("direction", "value"),
    State("start-date", "value"),
    State("end-date", "value")
)
def start_tracking(n_clicks, api_key, root_address, max_depth, direction, start_date, end_date):
    if n_clicks == 0 or not api_key or not root_address:
        return "請輸入 API key 和起始地址", go.Figure()

    # 簡化版抓資料（沒有分層遞迴）
    txs = fetch_transactions(root_address, api_key, direction=direction)

    if not txs:
        return "沒有找到交易紀錄", go.Figure()

    # 處理成 Sankey 資料
    addresses = {}
    source_idx, target_idx, values = [], [], []

    for tx in txs:
        s = tx["from"].lower()
        t = tx["to"].lower()
        val = int(tx["value"]) / 1e18
        for addr in [s, t]:
            if addr not in addresses:
                addresses[addr] = len(addresses)
        source_idx.append(addresses[s])
        target_idx.append(addresses[t])
        values.append(val)

    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=15,
            thickness=20,
            line=dict(color="black", width=0.5),
            label=list(addresses.keys())
        ),
        link=dict(
            source=source_idx,
            target=target_idx,
            value=values
        )
    )])

    return f"抓取到 {len(txs)} 筆交易", fig

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=int(os.environ.get("PORT", 8050)), debug=False)
