import time
import pandas as pd
from datetime import datetime, timezone
from typing import List, Set
import os
import streamlit as st
import plotly.graph_objects as go
import locale
from io import BytesIO
import uuid  # 用於生成唯一 key

# ======== 設定中文星期 ========
try:
    locale.setlocale(locale.LC_TIME, 'zh_TW.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_TIME, 'Chinese_Taiwan')
    except:
        pass

# ======== API 與路徑設定 ========
API_KEY = "39MHHNXSEHSAQBTQY1MYA9AZBEXNYRHF7J"
BASE_URL = "https://api.etherscan.io/api"

# ======== Streamlit 介面 ========
st.set_page_config(page_title="ERC20 金流追蹤", layout="wide")
st.title("🔍 ERC20 Token 金流追蹤與桑基圖可視化")

ROOT_ADDRESS = st.text_input("請輸入追蹤起始錢包地址").strip()
MAX_DEPTH = st.number_input("最多追蹤層級", min_value=1, max_value=10, value=3, step=1)
DIRECTION_FILTER = st.selectbox("交易方向篩選", ["全部", "轉入", "轉出"], index=0)

start_date_input = st.date_input("查詢開始日期 (yyyy-mm-dd)", value=None, key="start")
end_date_input = st.date_input("查詢結束日期 (yyyy-mm-dd)", value=None, key="end")

weekdays = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]
if start_date_input:
    st.write(f"開始日期: {start_date_input.strftime('%Y-%m-%d')} {weekdays[start_date_input.weekday()]}")
if end_date_input:
    st.write(f"結束日期: {end_date_input.strftime('%Y-%m-%d')} {weekdays[end_date_input.weekday()]}")

top_n = st.number_input("每層顯示前 N 筆最大交易", min_value=1, max_value=100, value=10, step=1)
OUTPUT_FILE = f"{ROOT_ADDRESS[:6]}_erc20_trace.csv" if ROOT_ADDRESS else "erc20_trace.csv"

# ======== session_state 初始化 ========
if "in_layer" not in st.session_state:
    st.session_state.in_layer = 0
if "out_layer" not in st.session_state:
    st.session_state.out_layer = 0
if "df_trace" not in st.session_state:
    st.session_state.df_trace = pd.DataFrame()

# ======== 時間與區塊高度 ========
def timestamp_from_date(date_obj):
    if not date_obj:
        return None
    return int(datetime.combine(date_obj, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())

def get_block_number_by_timestamp(timestamp: int) -> int:
    params = {
        "module": "block",
        "action": "getblocknobytime",
        "timestamp": timestamp,
        "closest": "before",
        "apikey": API_KEY
    }
    response = requests.get(BASE_URL, params=params)
    data = response.json()
    return int(data["result"]) if data["status"] == "1" else 0

START_TS = timestamp_from_date(start_date_input)
END_TS = timestamp_from_date(end_date_input)
START_BLOCK = get_block_number_by_timestamp(START_TS) if START_TS else 0
END_BLOCK = get_block_number_by_timestamp(END_TS) if END_TS else 99999999

# ======== 抓取 ERC20 交易 ========
def fetch_all_transactions(address: str):
    all_tx = []
    page = 1
    offset = 10000
    while True:
        params = {
            "module": "account",
            "action": "tokentx",  # ✅ ERC20 Token transfer
            "address": address,
            "startblock": START_BLOCK,
            "endblock": END_BLOCK,
            "page": page,
            "offset": offset,
            "sort": "asc",
            "apikey": API_KEY
        }
        data = requests.get(BASE_URL, params=params).json()
        if data["status"] != "1":
            break
        txs = data["result"]
        if not txs:
            break
        all_tx.extend(txs)
        if len(txs) < offset:
            break
        page += 1
        time.sleep(0.2)
    return all_tx

# ======== 過濾與格式化 ========
def filter_and_parse_transactions(txs, current_address, depth, from_address):
    parsed = []
    current_lower = current_address.lower()
    for tx in txs:
        ts = int(tx["timeStamp"])
        direction = ""
        if tx["to"].lower() == current_lower:
            direction = "轉入"
            if DIRECTION_FILTER == "轉出":
                continue
        elif tx["from"].lower() == current_lower:
            direction = "轉出"
            if DIRECTION_FILTER == "轉入":
                continue
        else:
            continue

        token_decimal = int(tx.get("tokenDecimal", 18))
        token_symbol = tx.get("tokenSymbol", "UNKNOWN")
        raw_value = int(tx["value"]) if tx["value"].isdigit() else 0
        token_value = raw_value / (10 ** token_decimal)

        parsed.append({
            "層級": f"L{depth}",
            "追蹤來源": from_address,
            "地址": current_address,
            "交易哈希": tx["hash"],
            "區塊": tx["blockNumber"],
            "時間": datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            "From": tx["from"],
            "To": tx["to"],
            "方向": direction,
            "Token": token_symbol,
            "金額 (Token)": round(token_value, 8),
            "Token Decimal": token_decimal,
            "交易費 (ETH)": round(int(tx["gasPrice"]) * int(tx["gasUsed"]) / 1e18, 8)
        })
    return parsed

def append_single_tx_to_csv(tx_dict):
    df_tmp = pd.DataFrame([tx_dict])
    if not os.path.exists(OUTPUT_FILE):
        df_tmp.to_csv(OUTPUT_FILE, index=False, mode='w', encoding='utf-8-sig')
    else:
        df_tmp.to_csv(OUTPUT_FILE, index=False, mode='a', header=False, encoding='utf-8-sig')

# ======== 側邊欄固定下載按鈕 (唯一 key) ========
def download_buttons():
    df = st.session_state.df_trace
    if df.empty:
        st.sidebar.info("目前尚無資料可下載")
        return

    csv_data = df.to_csv(index=False, encoding="utf-8-sig")
    excel_buffer = BytesIO()
    df.to_excel(excel_buffer, index=False, sheet_name="交易資料")
    excel_buffer.seek(0)

    unique_id = str(uuid.uuid4())  # 產生唯一 key

    st.sidebar.download_button(
        label="下載 CSV",
        data=csv_data,
        file_name=OUTPUT_FILE,
        mime="text/csv",
        key=f"download_csv_{unique_id}"
    )
    st.sidebar.download_button(
        label="下載 Excel",
        data=excel_buffer,
        file_name=OUTPUT_FILE.replace(".csv", ".xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"download_excel_{unique_id}"
    )

download_buttons()  # 初始化側邊欄按鈕

# ======== 多層追蹤 ========
def start_tracking(root_address):
    if not root_address:
        st.warning("請輸入有效的錢包地址")
        return

    df_trace = st.session_state.df_trace
    progress_text = st.empty()
    progress_bar = st.progress(0)

    addresses_to_process = [(root_address, 1, "ROOT")]
    seen: Set[str] = set()
    total_addresses = 1
    processed_addresses = 0

    while addresses_to_process:
        current_address, depth, from_address = addresses_to_process.pop(0)
        addr_lower = current_address.lower()
        if addr_lower in seen or depth > MAX_DEPTH:
            continue
        seen.add(addr_lower)

        txs = fetch_all_transactions(current_address)
        parsed = filter_and_parse_transactions(txs, current_address, depth, from_address)
        for tx in parsed:
            append_single_tx_to_csv(tx)
            df_trace = pd.concat([df_trace, pd.DataFrame([tx])], ignore_index=True)
            st.session_state.df_trace = df_trace  # 更新 session_state

            counterparty = tx["To"] if tx["方向"] == "轉出" else tx["From"]
            if counterparty.lower() != addr_lower and counterparty.lower() not in seen:
                addresses_to_process.append((counterparty, depth + 1, f"L{depth}"))
                total_addresses += 1

        processed_addresses += 1
        progress_text.text(f"抓取地址 {processed_addresses}/{total_addresses}: {current_address}")
        progress_bar.progress(processed_addresses / total_addresses)

    progress_text.text("抓取完成 ✅")
    progress_bar.empty()
    tokens = df_trace["Token"].unique()
    st.success(f"✅ 追蹤結束，共 {len(df_trace)} 筆交易，涉及 Token: {', '.join(tokens)}")
    st.dataframe(df_trace)
    download_buttons()  # 更新下載按鈕

if st.button("開始追蹤"):
    start_tracking(ROOT_ADDRESS)

# ======== 桑基圖資料準備 ========
@st.cache_data
def prepare_graph_data(df):
    df["Layer"] = df["層級"].str.extract(r'L(\d+)').astype(int)

    address_depth = {}
    for _, row in df.iterrows():
        for addr in [row["From"], row["To"]]:
            if addr not in address_depth or row["Layer"] < address_depth[addr]:
                address_depth[addr] = row["Layer"]

    all_labels = sorted(set(df["From"]) | set(df["To"]), key=lambda x: address_depth.get(x, 99))
    label_map = {label: i for i, label in enumerate(all_labels)}

    df["source"] = df["From"].map(label_map)
    df["target"] = df["To"].map(label_map)

    in_layer_data = {}
    out_layer_data = {}
    for l in df["Layer"].unique():
        in_layer_data[l] = df[(df["Layer"] == l) & (df["方向"] == "轉入")].copy()
        out_layer_data[l] = df[(df["Layer"] == l) & (df["方向"] == "轉出")].copy()

    max_layer = df["Layer"].max()
    layer_base_colors = [
        "rgba(44,160,44,0.4)", "rgba(31,119,180,0.4)", "rgba(255,127,14,0.4)",
        "rgba(214,39,40,0.4)", "rgba(148,103,189,0.4)", "rgba(140,86,75,0.4)"
    ]
    layer_colors = {layer: layer_base_colors[(layer - 1) % len(layer_base_colors)] for layer in range(1, max_layer + 1)}
    node_colors = [layer_colors.get(address_depth.get(lbl, 1), "lightblue") for lbl in all_labels]

    return in_layer_data, out_layer_data, max_layer, all_labels, node_colors, layer_colors

# ======== 桑基圖生成 ========
if os.path.exists(OUTPUT_FILE):
    df = pd.read_csv(OUTPUT_FILE, encoding='utf-8-sig')
    if not df.empty:
        in_layer_data, out_layer_data, max_layer, all_labels, node_colors, layer_colors = prepare_graph_data(df)

        col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
        if col_btn1.button("轉入 +1 層") and st.session_state.in_layer < max_layer:
            st.session_state.in_layer += 1
        if col_btn2.button("轉入 -1 層") and st.session_state.in_layer > 0:
            st.session_state.in_layer -= 1
        if col_btn3.button("轉出 +1 層") and st.session_state.out_layer < max_layer:
            st.session_state.out_layer += 1
        if col_btn4.button("轉出 -1 層") and st.session_state.out_layer > 0:
            st.session_state.out_layer -= 1

        def make_trace(data, top_n):
            data = data.sort_values(by="金額 (Token)", ascending=False).head(top_n)
            return dict(
                source=data["source"].tolist(),
                target=data["target"].tolist(),
                value=data["金額 (Token)"].tolist(),
                color=[layer_colors.get(l, "rgba(128,128,128,0.4)") for l in data["Layer"]]
            )

        source, target, value, color = [], [], [], []
        for i in range(1, st.session_state.in_layer + 1):
            if i in in_layer_data:
                trace = make_trace(in_layer_data[i], top_n)
                source += trace["source"]
                target += trace["target"]
                value += trace["value"]
                color += trace["color"]
        for i in range(1, st.session_state.out_layer + 1):
            if i in out_layer_data:
                trace = make_trace(out_layer_data[i], top_n)
                source += trace["source"]
                target += trace["target"]
                value += trace["value"]
                color += trace["color"]

        fig = go.Figure(data=[go.Sankey(
            node=dict(pad=15, thickness=20, line=dict(color="black", width=0.5),
                      label=all_labels, color=node_colors),
            link=dict(source=source, target=target, value=value, color=color)
        )])
        fig.update_layout(
            title_text=f"ERC20 流向圖（轉入 L{st.session_state.in_layer}，轉出 L{st.session_state.out_layer}，Top {top_n}）",
            font_size=10
        )
        st.plotly_chart(fig, use_container_width=True)

# ======== 新增：從現有資料選擇錢包再追蹤 ========
if not st.session_state.df_trace.empty:
    df_wallets = st.session_state.df_trace.copy()

    # 從 From 和 To 收集錢包的層級與交易數
    wallet_info = {}
    for _, row in df_wallets.iterrows():
        for col in ["From", "To"]:
            addr = row[col]
            layer_num = int(row["層級"].replace("L", ""))
            if addr not in wallet_info:
                wallet_info[addr] = {"layer": layer_num, "count": 0}
            wallet_info[addr]["layer"] = min(wallet_info[addr]["layer"], layer_num)
            wallet_info[addr]["count"] += 1

    display_wallets = [f"{addr} (L{info['layer']}, {info['count']} 筆交易)" for addr, info in wallet_info.items()]
    wallet_map = dict(zip(display_wallets, wallet_info.keys()))

    selected_display = st.selectbox("🔄 從現有錢包重新追蹤", sorted(display_wallets))
    selected_wallet = wallet_map[selected_display]

    if st.button("以選擇的錢包為起點繼續追蹤"):
        ROOT_ADDRESS = selected_wallet
        OUTPUT_FILE = f"{ROOT_ADDRESS[:6]}_erc20_trace.csv"
        st.session_state.df_trace = pd.DataFrame()
        if os.path.exists(OUTPUT_FILE):
            os.remove(OUTPUT_FILE)
        start_tracking(ROOT_ADDRESS)