# -*- coding: utf-8 -*-
import requests
import time
import pandas as pd
from datetime import datetime, timezone
from typing import Set, Optional, Tuple
import streamlit as st
import plotly.graph_objects as go
from io import BytesIO
import locale
import re
import calendar
import heapq

# ===== 介面設定 =====
st.set_page_config(page_title="ETH 金流追蹤", layout="wide")
st.title("🔍 ETH 金流追蹤與桑基圖可視化")

# ===== 語系（容錯） =====
try:
    locale.setlocale(locale.LC_TIME, 'zh_TW.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_TIME, 'Chinese_Taiwan')
    except:
        pass

# ===== 秘密金鑰與 API Base（可在側邊欄覆寫） =====
DEFAULT_API_KEY = st.secrets.get("ETHERSCAN_KEY", "")
DEFAULT_BASE_URL = st.secrets.get("ETHERSCAN_BASE", "https://api.etherscan.io/v2/api?chainid=1")

with st.sidebar:
    st.header("⚙️ 設定")
    API_KEY = st.text_input("Etherscan API Key", value=DEFAULT_API_KEY, type="password")
    BASE_URL = st.text_input("API Base（可自架 proxy）", value=DEFAULT_BASE_URL)
    st.caption("預設使用 Etherscan v2： https://api.etherscan.io/v2/api?chainid=1")

# ===== session_state 安全初始化 =====
def ensure_state():
    ss = st.session_state
    ss.setdefault("df_trace", pd.DataFrame())
    ss.setdefault("in_layer", 0)
    ss.setdefault("out_layer", 0)
ensure_state()

# ===== 使用者輸入區 =====
col = st.columns([6,2,2,2])
with col[0]:
    ROOT_ADDRESS = st.text_input("請輸入追蹤起始錢包地址", placeholder="0x...").strip()
with col[1]:
    MAX_DEPTH = st.number_input("最多追蹤層級", 1, 10, 3, 1)
with col[2]:
    top_n_fetch = st.number_input("抓取 Top-N（每地址）", 0, 1000, 10, 1, help="0 = 不限制；僅純轉帳")
with col[3]:
    DIRECTION_MODE = st.selectbox("方向", ["all","in","out"], index=0, help="全部＝先上游再下游")

col2 = st.columns(4)
this_year = datetime.now().year
this_month = datetime.now().month
USE_FULL_HISTORY = col2[0].checkbox("從最早開始（忽略開始年月）", value=True)
start_year  = col2[1].number_input("開始年份", 2015, this_year, this_year, disabled=USE_FULL_HISTORY)
start_month = col2[2].number_input("開始月份", 1, 12, 1, disabled=USE_FULL_HISTORY)
end_year    = col2[3].number_input("結束年份", 2015, this_year, this_year)
end_month   = st.number_input("結束月份", 1, 12, this_month)

# ===== 時間 → 區塊 =====
if USE_FULL_HISTORY:
    start_date_input = datetime(2015, 7, 1)
else:
    start_date_input = datetime(int(start_year), int(start_month), 1)
end_day = calendar.monthrange(int(end_year), int(end_month))[1]
end_date_input = datetime(int(end_year), int(end_month), end_day, 23, 59, 59)

st.caption("開始年月: " + ("全部歷史" if USE_FULL_HISTORY else start_date_input.strftime("%Y-%m")))
st.caption(f"結束年月: {end_date_input.strftime('%Y-%m')}")

# ===== 共用小工具 =====
SUPPRESS_PATTERNS = ("結果視窗太大","PageNo x Offset","window too large","page x offset")

def _should_suppress_message(msg: Optional[str]) -> bool:
    if not msg:
        return False
    low = msg.lower()
    return any(p.lower() in low for p in SUPPRESS_PATTERNS)

@st.cache_data(show_spinner=False)
def get_block_number_by_timestamp(ts: int, api_key: str, base_url: str) -> int:
    try:
        data = requests.get(base_url, params={
            "module":"block","action":"getblocknobytime","timestamp":ts,
            "closest":"before","apikey":api_key
        }, timeout=30).json()
        return int(data.get("result") or 0)
    except Exception:
        return 0

END_TS = int(end_date_input.replace(tzinfo=timezone.utc).timestamp())
END_BLOCK = get_block_number_by_timestamp(END_TS, API_KEY, BASE_URL)
if USE_FULL_HISTORY:
    START_BLOCK = 0
else:
    START_TS = int(start_date_input.replace(tzinfo=timezone.utc).timestamp())
    START_BLOCK = get_block_number_by_timestamp(START_TS, API_KEY, BASE_URL)
if END_BLOCK and START_BLOCK and END_BLOCK < START_BLOCK:
    START_BLOCK, END_BLOCK = END_BLOCK, START_BLOCK

# ===== 抓取交易（外部、純轉帳 input=="0x"） =====
@st.cache_data(show_spinner=False)
def fetch_page(address: str, page: int, offset: int, api_key: str, base_url: str, start_block: int, end_block: int):
    try:
        resp = requests.get(base_url, params={
            "module":"account","action":"txlist","address":address,
            "startblock":start_block,"endblock":end_block or 99999999,
            "page":page,"offset":offset,"sort":"asc","apikey":api_key
        }, timeout=60)
        return resp.json()
    except Exception:
        return {"status":"0","message":"EXCEPTION","result":[]}

def fetch_all_transactions(address: str, api_key: str, base_url: str):
    all_tx, page, offset, backoff = [], 1, 1000, 1.0
    while True:
        data = fetch_page(address, page, offset, api_key, base_url, START_BLOCK, END_BLOCK)
        status = str(data.get("status", ""))
        msg = (data.get("message") or "").strip()
        result = data.get("result")

        if isinstance(result, str) and ("rate limit" in result.lower() or "max rate" in result.lower()):
            st.info(f"Etherscan 速率限制，{backoff:.1f}s 後重試第 {page} 頁…")
            time.sleep(backoff); backoff = min(backoff*2, 8.0); continue
        if (isinstance(result, str) and "no transactions" in result.lower()) or (status=="0" and msg.upper()=="NO TRANSACTIONS FOUND"):
            break
        if not isinstance(result, list):
            if _should_suppress_message(msg):
                break
            else:
                st.warning(f"Etherscan 回傳異常：status={status}, message={msg or 'None'}"); break
        if not result: break
        all_tx.extend(result)
        if len(result) < offset: break
        page += 1; time.sleep(0.2)
    return all_tx

def fetch_top_transactions_by_amount(address: str, top_n_addr:int, mode: str, api_key: str, base_url: str):
    if top_n_addr <= 0:
        return fetch_all_transactions(address, api_key, base_url)
    addr_lower = (address or "").lower()
    heap, idx, page, offset, backoff = [], 0, 1, 1000, 1.0
    while True:
        data = fetch_page(address, page, offset, api_key, base_url, START_BLOCK, END_BLOCK)
        status = str(data.get("status", ""))
        msg = (data.get("message") or "").strip()
        result = data.get("result")
        if isinstance(result, str) and ("rate limit" in result.lower() or "max rate" in result.lower()):
            st.info(f"Etherscan 速率限制，{backoff:.1f}s 後重試第 {page} 頁…")
            time.sleep(backoff); backoff = min(backoff*2, 8.0); continue
        if (isinstance(result, str) and "no transactions" in result.lower()) or (status=="0" and msg.upper()=="NO TRANSACTIONS FOUND"):
            break
        if not isinstance(result, list):
            if _should_suppress_message(msg): break
            else: st.warning(f"Etherscan 回傳異常：status={status}, message={msg or 'None'}"); break
        if not result: break
        for tx in result:
            if not isinstance(tx, dict):
                continue
            if (tx.get("input") or "") != "0x":
                continue
            f = (tx.get("from") or "").lower(); t = (tx.get("to") or "").lower()
            if mode == "in" and t != addr_lower: continue
            if mode == "out" and f != addr_lower: continue
            if mode == "all" and not (t == addr_lower or f == addr_lower): continue
            try: value_wei = int(tx.get("value") or 0)
            except: value_wei = 0
            item = (value_wei, int(tx.get("timeStamp") or 0), idx, tx); idx += 1
            if len(heap) < top_n_addr: heapq.heappush(heap, item)
            else:
                if value_wei > heap[0][0]: heapq.heapreplace(heap, item)
        if len(result) < offset: break
        page += 1; time.sleep(0.2)
    top_tx = [t[-1] for t in heap]
    top_tx.sort(key=lambda x: int(x.get("value") or 0), reverse=True)
    return top_tx

# ===== 解析 & 過濾 =====
def filter_and_parse_transactions(txs, current_address, depth, from_address, mode: str):
    parsed, current_lower = [], (current_address or "").lower()
    for tx in txs:
        if not isinstance(tx, dict):
            continue
        f = (tx.get("from") or "").lower(); t = (tx.get("to") or "").lower(); inp = tx.get("input") or ""
        if inp != "0x":
            continue
        if mode == "in":
            if t != current_lower: continue
            direction = "轉入"
        elif mode == "out":
            if f != current_lower: continue
            direction = "轉出"
        else:
            if   t == current_lower: direction = "轉入"
            elif f == current_lower: direction = "轉出"
            else: continue
        try: ts = int(tx.get("timeStamp") or 0)
        except: ts = 0
        try: value_eth = round(int(tx.get("value") or 0) / 1e18, 8)
        except: value_eth = 0.0
        try:
            gas_price = int(tx.get("gasPrice") or 0); gas_used = int(tx.get("gasUsed") or 0)
            fee_eth = round(gas_price * gas_used / 1e18, 8)
        except:
            fee_eth = 0.0
        parsed.append({
            "層級": f"L{depth}",
            "追蹤來源": from_address,
            "地址": current_address,
            "交易哈希": tx.get("hash", "") or "",
            "方法": "轉移",
            "區塊": tx.get("blockNumber", "") or "",
            "時間": datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S') if ts else "",
            "From": tx.get("from", "") or "",
            "To": tx.get("to", "") or "",
            "方向": direction,
            "金額 (ETH)": value_eth,
            "交易費 (ETH)": fee_eth,
        })
    return parsed

# ===== 單向 BFS =====
def traverse_one_direction(root_address, mode: str):
    df_trace = st.session_state.get("df_trace", pd.DataFrame()).copy()
    ph = st.empty(); bar = st.progress(0)
    q = [(root_address, 1, "ROOT")]; seen:set[str] = set(); tot = 1; done = 0
    while q:
        cur, depth, src = q.pop(0)
        low = (cur or "").lower()
        if not low: continue
        if low in seen or depth > MAX_DEPTH: continue
        seen.add(low)
        # 取資料
        if top_n_fetch and int(top_n_fetch) > 0:
            txs = fetch_top_transactions_by_amount(cur, int(top_n_fetch), mode, API_KEY, BASE_URL)
        else:
            txs = fetch_all_transactions(cur, API_KEY, BASE_URL)
        if not isinstance(txs, list) or not txs:
            done += 1; ph.text(f"[{mode}] 抓取 {done}/{tot}: {cur}（無交易）"); bar.progress(min(1.0, done/max(1, tot))); continue
        parsed = filter_and_parse_transactions(txs, cur, depth, src, mode)
        for tx in parsed:
            df_trace = pd.concat([df_trace, pd.DataFrame([tx])], ignore_index=True)
            counterparty = tx["From"] if mode == "in" else tx["To"]
            cp = (counterparty or "").lower()
            if cp and cp != low and cp not in seen:
                q.append((counterparty, depth+1, f"L{depth}")); tot += 1
        done += 1; ph.text(f"[{mode}] 抓取 {done}/{tot}: {cur}"); bar.progress(min(1.0, done/max(1, tot)))
    ph.text(f"[{mode}] 抓取完成 ✅"); bar.empty()
    st.session_state.df_trace = df_trace
    st.dataframe(df_trace)

# ===== 匯入/匯出 =====
with st.sidebar:
    st.subheader("📥 匯入既有資料（CSV 或 Excel）")
    up = st.file_uploader("上傳 CSV/XLSX 直接畫圖", type=["csv","xlsx","xls"])
    if st.button("載入上傳檔案") and up is not None:
        try:
            if up.name.lower().endswith(('.xlsx','.xls')):
                st.session_state.df_trace = pd.read_excel(up)
            else:
                st.session_state.df_trace = pd.read_csv(up, encoding="utf-8-sig")
            st.success("已載入資料，直接在下方畫圖 ✨")
        except Exception as e:
            st.error(f"讀檔失敗：{e}")

    st.subheader("📤 下載")
    if not st.session_state.df_trace.empty:
        df = st.session_state.df_trace
        csv_data = df.to_csv(index=False, encoding="utf-8-sig")
        excel_buffer = BytesIO(); df.to_excel(excel_buffer, index=False, sheet_name="交易資料"); excel_buffer.seek(0)
        fname = (ROOT_ADDRESS[:6] if ROOT_ADDRESS else "trace") + \
                "_" + ("all" if USE_FULL_HISTORY else start_date_input.strftime('%Y-%m')) + \
                "_" + end_date_input.strftime('%Y-%m')
        st.download_button("下載 CSV", csv_data, f"{fname}.csv", "text/csv")
        st.download_button("下載 Excel", excel_buffer, f"{fname}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ===== 入口：開始爬 or 直接畫 =====
if st.button("開始（沒上傳就爬）"):
    if not ROOT_ADDRESS:
        st.warning("請輸入有效的錢包地址")
    else:
        if DIRECTION_MODE in ("in","out"):
            traverse_one_direction(ROOT_ADDRESS, DIRECTION_MODE)
        else:
            st.info("全部模式：先『只轉入(上游)』，再『只轉出(下游)』")
            traverse_one_direction(ROOT_ADDRESS, "in")
            traverse_one_direction(ROOT_ADDRESS, "out")
        st.success(f"✅ 完成，共 {len(st.session_state.df_trace)} 筆交易")

# ===== 畫桑基圖 =====
df_for_plot = st.session_state.get("df_trace", pd.DataFrame()).copy()
if df_for_plot.empty:
    st.info("目前沒有可繪圖的資料。先上傳檔案或開始爬取。")
else:
    # 整理層級/節點
    df_for_plot["Layer"] = df_for_plot["層級"].str.extract(r'L(\\d+)').astype(int)
    address_depth = {}
    for _, row in df_for_plot.iterrows():
        for addr in [row["From"], row["To"]]:
            if addr not in address_depth or row["Layer"] < address_depth[addr]:
                address_depth[addr] = row["Layer"]
    all_labels = sorted(set(df_for_plot["From"]) | set(df_for_plot["To"]), key=lambda x: address_depth.get(x, 99))
    label_map = {label:i for i,label in enumerate(all_labels)}
    df_for_plot["source"] = df_for_plot["From"].map(label_map)
    df_for_plot["target"] = df_for_plot["To"].map(label_map)

    in_layer, out_layer = st.columns(2)
    with in_layer:
        if st.button("轉入 +1 層"):
            st.session_state.in_layer += 1
        if st.button("轉入 -1 層") and st.session_state.in_layer > 0:
            st.session_state.in_layer -= 1
    with out_layer:
        if st.button("轉出 +1 層"):
            st.session_state.out_layer += 1
        if st.button("轉出 -1 層") and st.session_state.out_layer > 0:
            st.session_state.out_layer -= 1

    max_layer = int(df_for_plot["Layer"].max()) if not df_for_plot.empty else 0
    st.session_state.in_layer = min(st.session_state.in_layer, max_layer)
    st.session_state.out_layer = min(st.session_state.out_layer, max_layer)

    layer_base_colors = [
        "rgba(44,160,44,0.4)", "rgba(31,119,180,0.4)", "rgba(255,127,14,0.4)",
        "rgba(214,39,40,0.4)", "rgba(148,103,189,0.4)", "rgba(140,86,75,0.4)"
    ]
    layer_colors = {layer: layer_base_colors[(layer - 1) % len(layer_base_colors)] for layer in range(1, max_layer + 1)}
    node_colors = [layer_colors.get(address_depth.get(lbl, 1), "lightblue") for lbl in all_labels]

    def make_trace(data):
        if data is None or data.empty:
            return dict(source=[], target=[], value=[], color=[])
        return dict(
            source=data["source"].tolist(),
            target=data["target"].tolist(),
            value=data["金額 (ETH)"].tolist(),
            color=[layer_colors.get(l, "rgba(128,128,128,0.4)") for l in data["Layer"]]
        )

    source, target, value, color = [], [], [], []
    for i in range(1, st.session_state.in_layer + 1):
        sub = df_for_plot[(df_for_plot["Layer"] == i) & (df_for_plot["方向"] == "轉入")]
        tr = make_trace(sub); source += tr["source"]; target += tr["target"]; value += tr["value"]; color += tr["color"]
    for i in range(1, st.session_state.out_layer + 1):
        sub = df_for_plot[(df_for_plot["Layer"] == i) & (df_for_plot["方向"] == "轉出")]
        tr = make_trace(sub); source += tr["source"]; target += tr["target"]; value += tr["value"]; color += tr["color"]

    fig = go.Figure(data=[go.Sankey(
        node=dict(pad=15, thickness=20, line=dict(color="black", width=0.5), label=all_labels, color=node_colors),
        link=dict(source=source, target=target, value=value, color=color)
    )])
    fig.update_layout(title_text=f"ETH 流向圖（轉入 L{st.session_state.in_layer}，轉出 L{st.session_state.out_layer}）", font_size=10)
    st.plotly_chart(fig, use_container_width=True)
