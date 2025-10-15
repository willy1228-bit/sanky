# -*- coding: utf-8 -*-
import requests
import time
import pandas as pd
from datetime import datetime, timezone
from typing import Set, Optional, Tuple
import os
import streamlit as st
import plotly.graph_objects as go
import locale
from io import BytesIO
import uuid
from pathlib import Path
import re
import calendar
import heapq  # ✅ 最小堆用於 Top-N 過濾（抓取階段）

# ======== 設定中文星期（容錯） ========
try:
    locale.setlocale(locale.LC_TIME, 'zh_TW.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_TIME, 'Chinese_Taiwan')
    except:
        pass

# ======== 基本設定 ========
API_KEY = "39MHHNXSEHSAQBTQY1MYA9AZBEXNYRHF7J"
BASE_URL = "https://api.etherscan.io/v2/api?chainid=1"

st.set_page_config(page_title="ETH 金流追蹤", layout="wide")
st.title("🔍 ETH 金流追蹤與桑基圖可視化")

# ---- 保底初始化 session_state ----
def ensure_state():
    if "df_trace" not in st.session_state:
        st.session_state.df_trace = pd.DataFrame()
    if "output_file_base" not in st.session_state:
        st.session_state.output_file_base = ""
    if "in_layer" not in st.session_state:
        st.session_state.in_layer = 0
    if "out_layer" not in st.session_state:
        st.session_state.out_layer = 0
    now = datetime.now()
    if "start_year" not in st.session_state:
        st.session_state.start_year = now.year
    if "start_month" not in st.session_state:
        st.session_state.start_month = 1
    if "end_year" not in st.session_state:
        st.session_state.end_year = now.year
    if "end_month" not in st.session_state:
        st.session_state.end_month = now.month
    if "range_autofilled_for" not in st.session_state:
        st.session_state.range_autofilled_for = None

ensure_state()

# ======== 互動輸入（已去重，並加上唯一 key） ========
ROOT_ADDRESS = st.text_input("請輸入追蹤起始錢包地址", key="root_address_input").strip()
MAX_DEPTH = st.number_input("最多追蹤層級", min_value=1, max_value=10, value=3, step=1, key="max_depth_input")

# ✅ 固定使用『全部』模式，不顯示任何選單
DIRECTION_MODE = "all"

# ✅ 開始日期可空 → 抓全部歷史
USE_FULL_HISTORY = st.checkbox("從最早開始（忽略開始年月）", value=True, key="use_full_history")

# ======== 工具：資料夾/檔名規則 ========
def wallet6(addr: str) -> str:
    return (addr or "trace")[:6]

def current_folder_name(addr: str) -> str:
    now = datetime.now()
    return f"{wallet6(addr)}_{now.year}_{now.month:02d}"

def ensure_current_folder(addr: str) -> Path:
    p = Path(current_folder_name(addr)).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

# 解析檔名中的年月（錢包6碼_YYYY-MM_YYYY-MM）
FILE_RANGE_RE = re.compile(r"_(\d{4})-(\d{2})_(\d{4})-(\d{2})$", re.IGNORECASE)

def extract_range_from_filename(path: Path) -> Optional[Tuple[int,int,int,int]]:
    m = FILE_RANGE_RE.search(path.stem)
    if not m:
        return None
    sy, sm, ey, em = map(int, m.groups())
    return sy, sm, ey, em

# 從 DataFrame 的「時間」欄推算實際起訖（取到月份）
def df_time_range(df: pd.DataFrame) -> Tuple[Optional[datetime], Optional[datetime]]:
    if df is None or df.empty or "時間" not in df.columns:
        return None, None
    t = pd.to_datetime(df["時間"], errors="coerce", utc=True).dropna()
    if t.empty:
        return None, None
    s, e = t.min().to_pydatetime(), t.max().to_pydatetime()
    s_dt = datetime(s.year, s.month, 1)
    e_dt = datetime(e.year, e.month, 1)
    return s_dt, e_dt


def fname_from_df(addr: str, df: pd.DataFrame, default_start: datetime, default_end: datetime) -> str:
    s_dt, e_dt = df_time_range(df)
    if s_dt is None or e_dt is None:
        s_dt, e_dt = default_start, default_end
    return f"{wallet6(addr)}_{s_dt.strftime('%Y-%m')}_{e_dt.strftime('%Y-%m')}"


def find_latest_file_and_range(addr: str) -> Optional[Tuple[Path, Tuple[int,int,int,int]]]:
    if not addr:
        return None
    base = wallet6(addr)
    files = []
    cur_dir = ensure_current_folder(addr)
    files += list(cur_dir.glob(f"{base}_*.xlsx"))
    files += list(cur_dir.glob(f"{base}_*.csv"))
    dir_pat = re.compile(rf"^{re.escape(base)}_\\d{{4}}_\\d{{2}}$", re.IGNORECASE)
    for entry in Path(".").iterdir():
        if entry.is_dir() and dir_pat.match(entry.name):
            files += list(entry.glob(f"{base}_*.xlsx"))
            files += list(entry.glob(f"{base}_*.csv"))
    files = sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files:
        rng = extract_range_from_filename(p)
        if rng:
            return p, rng
    return None

# ======== 錢包變更 → 自動帶入年月 ========
if ROOT_ADDRESS and st.session_state.range_autofilled_for != ROOT_ADDRESS:
    found = find_latest_file_and_range(ROOT_ADDRESS)
    if found:
        _, (sy, sm, ey, em) = found
        st.session_state.start_year = sy
        st.session_state.start_month = sm
        st.session_state.end_year = ey
        st.session_state.end_month = em
    st.session_state.range_autofilled_for = ROOT_ADDRESS

# ======== 年月輸入（只需年+月） ========
this_year = datetime.now().year
this_month = datetime.now().month
col1, col2, col3, col4 = st.columns(4)
start_year  = col1.number_input("開始年份", min_value=2015, max_value=this_year, value=int(st.session_state.start_year), key="start_year", disabled=USE_FULL_HISTORY)
start_month = col2.number_input("開始月份", min_value=1, max_value=12, value=int(st.session_state.start_month), key="start_month", disabled=USE_FULL_HISTORY)
end_year    = col3.number_input("結束年份", min_value=2015, max_value=this_year, value=int(st.session_state.end_year), key="end_year")
end_month   = col4.number_input("結束月份", min_value=1, max_value=12, value=int(st.session_state.end_month), key="end_month")

# 轉成月份範圍（UTC）
if USE_FULL_HISTORY:
    start_date_input = datetime(2015, 7, 1)  # 供檔名 fallback
else:
    start_date_input = datetime(int(start_year), int(start_month), 1)

end_day = calendar.monthrange(int(end_year), int(end_month))[1]
end_date_input = datetime(int(end_year), int(end_month), end_day, 23, 59, 59)

st.write("開始年月: " + ("全部歷史" if USE_FULL_HISTORY else start_date_input.strftime("%Y-%m")))
st.write(f"結束年月: {end_date_input.strftime('%Y-%m')}")

# ✅ 抓取階段依金額保留 Top-N（每地址），0=不限制
top_n_fetch = st.number_input("抓取階段：每地址依金額保留前 N 筆（0 = 不限制）", min_value=0, max_value=1000, value=10, step=1, key="top_n_fetch")

# ======== 區塊高度查詢（支援「開始為空→全部歷史」） ========
def get_block_number_by_timestamp(timestamp: int) -> int:
    params = {
        "module": "block",
        "action": "getblocknobytime",
        "timestamp": timestamp,
        "closest": "before",
        "apikey": API_KEY
    }
    try:
        data = requests.get(BASE_URL, params=params, timeout=30).json()
        return int(data.get("result") or 0)
    except Exception:
        return 0

END_TS = int(end_date_input.replace(tzinfo=timezone.utc).timestamp())
END_BLOCK = get_block_number_by_timestamp(END_TS)
if USE_FULL_HISTORY:
    START_BLOCK = 0
else:
    START_TS = int(start_date_input.replace(tzinfo=timezone.utc).timestamp())
    START_BLOCK = get_block_number_by_timestamp(START_TS)

# 防呆：避免 end < start
if END_BLOCK and START_BLOCK and END_BLOCK < START_BLOCK:
    START_BLOCK, END_BLOCK = END_BLOCK, START_BLOCK

# ======== 靜默抑制某些 Etherscan 訊息 ========
SUPPRESS_PATTERNS = (
    "結果視窗太大",            # 中文訊息
    "PageNo x Offset",       # 英文關鍵字
    "window too large",      # 其他可能翻譯
    "page x offset"          # 變形寫法
)

def _should_suppress_message(msg: Optional[str]) -> bool:
    if not msg:
        return False
    low = msg.lower()
    return any(p.lower() in low for p in SUPPRESS_PATTERNS)

# ======== 尋找/存取資料 ========
def find_existing_trace(addr: str) -> Optional[pd.DataFrame]:
    if not addr:
        return None
    base = wallet6(addr)
    files = []
    cur_dir = ensure_current_folder(addr)
    files += list(cur_dir.glob(f"{base}_*.xlsx"))
    files += list(cur_dir.glob(f"{base}_*.csv"))
    dir_pat = re.compile(rf"^{re.escape(base)}_\\d{{4}}_\\d{{2}}$", re.IGNORECASE)
    for entry in Path(".").iterdir():
        if entry.is_dir() and dir_pat.match(entry.name):
            files += list(entry.glob(f"{base}_*.xlsx"))
            files += list(entry.glob(f"{base}_*.csv"))
    files = sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files:
        try:
            if p.suffix.lower() in (".xlsx", ".xls"):
                return pd.read_excel(p)
            else:
                return pd.read_csv(p, encoding="utf-8-sig")
        except Exception:
            continue
    return None


def save_trace_files(df: pd.DataFrame, addr: str):
    data_dir = ensure_current_folder(addr)
    fname = fname_from_df(addr, df, start_date_input, end_date_input)
    csv_path = data_dir / f"{fname}.csv"
    xlsx_path = data_dir / f"{fname}.xlsx"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="交易資料")
    st.session_state.output_file_base = str(csv_path)
    st.success(f"檔案已存至：{os.path.dirname(csv_path)}")

# ======== Etherscan 抓取（外部交易）【靜默處理 PageNo x Offset】 ========
def fetch_all_transactions(address: str):
    all_tx = []
    page = 1
    offset = 1000
    backoff_sec = 1.0
    while True:
        params = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": START_BLOCK,
            "endblock": END_BLOCK or 99999999,
            "page": page,
            "offset": offset,
            "sort": "asc",
            "apikey": API_KEY
        }
        try:
            resp = requests.get(BASE_URL, params=params, timeout=60)
            data = resp.json()
        except Exception:
            # 連線錯誤直接中止，但不跳警告
            break

        status = str(data.get("status", ""))
        message = (data.get("message") or "").strip()
        result = data.get("result")

        # 速率限制 → 退避重試（保留提示）
        if isinstance(result, str) and ("rate limit" in result.lower() or "max rate" in result.lower()):
            st.info(f"Etherscan 速率限制，{backoff_sec:.1f}s 後重試第 {page} 頁…")
            time.sleep(backoff_sec)
            backoff_sec = min(backoff_sec * 2, 8.0)
            continue

        # 無交易 → 結束
        if (isinstance(result, str) and "no transactions" in result.lower()) or (status == "0" and message.upper() == "NO TRANSACTIONS FOUND"):
            break

        # 其它異常：如果是「PageNo x Offset」這類訊息 → 靜默結束；否則才顯示警告
        if not isinstance(result, list):
            if _should_suppress_message(message):
                break  # 不顯示任何警告，直接停止分頁
            else:
                st.warning(f"Etherscan 回傳異常（非清單）：status={status}, message={message or 'None'}, result_type={type(result).__name__}")
                break

        if not result:
            break

        all_tx.extend(result)
        if len(result) < offset:
            break

        page += 1
        time.sleep(0.2)

    return all_tx

# ======== ✅ 抓取時即依金額保留 Top-N（每地址、依方向、僅純轉帳）【靜默處理 PageNo x Offset】 ========
def fetch_top_transactions_by_amount(address: str, top_n_addr:int, mode: str):
    """
    只保留「金額(ETH)最大」的前 top_n_addr 筆交易（input == '0x' 的純轉帳）。
    依 mode 過濾：in=To 是當前地址；out=From 是當前地址；all=任一側為當前地址。
    透過 min-heap 在抓取過程中即時篩選，避免儲存全部交易。
    """
    if top_n_addr <= 0:
        return fetch_all_transactions(address)

    addr_lower = (address or "").lower()
    heap = []  # (value_wei, ts, idx, tx)
    idx = 0

    page = 1
    offset = 1000
    backoff_sec = 1.0

    while True:
        params = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": START_BLOCK,
            "endblock": END_BLOCK or 99999999,
            "page": page,
            "offset": offset,
            "sort": "asc",
            "apikey": API_KEY
        }
        try:
            resp = requests.get(BASE_URL, params=params, timeout=60)
            data = resp.json()
        except Exception:
            break

        status = str(data.get("status", ""))
        message = (data.get("message") or "").strip()
        result = data.get("result")

        if isinstance(result, str) and ("rate limit" in result.lower() or "max rate" in result.lower()):
            st.info(f"Etherscan 速率限制，{backoff_sec:.1f}s 後重試第 {page} 頁…")
            time.sleep(backoff_sec)
            backoff_sec = min(backoff_sec * 2, 8.0)
            continue

        if (isinstance(result, str) and "no transactions" in result.lower()) or (status == "0" and message.upper() == "NO TRANSACTIONS FOUND"):
            break

        if not isinstance(result, list):
            if _should_suppress_message(message):
                break  # 靜默停止，不顯示警告
            else:
                st.warning(f"Etherscan 回傳異常（非清單）：status={status}, message={message or 'None'}, result_type={type(result).__name__}")
                break

        if not result:
            break

        for tx in result:
            if not isinstance(tx, dict):
                continue

            # 僅純轉帳（與繪圖一致）
            if (tx.get("input") or "") != "0x":
                continue

            from_addr = (tx.get("from") or "").lower()
            to_addr   = (tx.get("to") or "").lower()

            if mode == "in":
                if to_addr != addr_lower:
                    continue
            elif mode == "out":
                if from_addr != addr_lower:
                    continue
            else:  # "all"
                if (to_addr != addr_lower) and (from_addr != addr_lower):
                    continue

            try:
                value_wei = int(tx.get("value") or 0)
            except Exception:
                value_wei = 0

            item = (value_wei, int(tx.get("timeStamp") or 0), idx, tx)
            idx += 1

            if len(heap) < top_n_addr:
                heapq.heappush(heap, item)
            else:
                if value_wei > heap[0][0]:
                    heapq.heapreplace(heap, item)

        if len(result) < offset:
            break

        page += 1
        time.sleep(0.2)

    top_tx = [t[-1] for t in heap]
    top_tx.sort(key=lambda x: int(x.get("value") or 0), reverse=True)
    return top_tx

# ======== 解析（只處理 dict） ========
def filter_and_parse_transactions(txs, current_address, depth, from_address, mode: str):
    parsed = []
    current_lower = (current_address or "").lower()

    for tx in txs:
        if not isinstance(tx, dict):
            continue

        from_addr = (tx.get("from") or "").lower()
        to_addr   = (tx.get("to")   or "").lower()
        inp       = tx.get("input") or ""

        if inp != "0x":
            continue

        if mode == "in":
            if to_addr != current_lower:
                continue
            direction = "轉入"
        elif mode == "out":
            if from_addr != current_lower:
                continue
            direction = "轉出"
        else:
            if to_addr == current_lower:
                direction = "轉入"
            elif from_addr == current_lower:
                direction = "轉出"
            else:
                continue

        try:
            ts = int(tx.get("timeStamp") or 0)
        except Exception:
            ts = 0
        try:
            value_eth = round(int(tx.get("value") or 0) / 1e18, 8)
        except Exception:
            value_eth = 0.0
        try:
            gas_price = int(tx.get("gasPrice") or 0)
            gas_used  = int(tx.get("gasUsed") or 0)
            fee_eth   = round(gas_price * gas_used / 1e18, 8)
        except Exception:
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


def append_single_tx_to_csv(tx_dict, csv_path: str):
    df_tmp = pd.DataFrame([tx_dict])
    if not os.path.exists(csv_path):
        df_tmp.to_csv(csv_path, index=False, mode='w', encoding='utf-8-sig')
    else:
        df_tmp.to_csv(csv_path, index=False, mode='a', header=False, encoding='utf-8-sig')

# ======== 下載按鈕（名稱用「實際抓到的時間範圍」） ========
def download_buttons():
    df = st.session_state.get("df_trace", pd.DataFrame())
    if df is None or df.empty:
        st.sidebar.info("目前尚無資料可下載")
        return
    fname = fname_from_df(ROOT_ADDRESS or "trace", df, start_date_input, end_date_input)
    csv_data = df.to_csv(index=False, encoding="utf-8-sig")
    excel_buffer = BytesIO()
    df.to_excel(excel_buffer, index=False, sheet_name="交易資料")
    excel_buffer.seek(0)
    uid = str(uuid.uuid4())
    st.sidebar.download_button("下載 CSV", csv_data, f"{fname}.csv", "text/csv", key=f"download_csv_{uid}")
    st.sidebar.download_button("下載 Excel", excel_buffer, f"{fname}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key=f"download_excel_{uid}")


download_buttons()  # 先建立側邊欄（函式已做保護）

# ======== 單一路徑 BFS（上游 or 下游） ========
def _traverse_one_direction(root_address, mode: str, csv_path: str):
    df_trace = st.session_state.get("df_trace", pd.DataFrame()).copy()
    progress_text = st.empty()
    progress_bar = st.progress(0)

    addresses_to_process = [(root_address, 1, "ROOT")]
    seen: Set[str] = set()
    total_addresses = 1
    processed_addresses = 0

    while addresses_to_process:
        current_address, depth, from_address = addresses_to_process.pop(0)
        addr_lower = (current_address or "").lower()
        if not addr_lower:
            continue
        if addr_lower in seen or depth > MAX_DEPTH:
            continue
        seen.add(addr_lower)

        # ✅ 抓取階段就依金額保留 Top-N（每地址）
        if top_n_fetch and int(top_n_fetch) > 0:
            txs = fetch_top_transactions_by_amount(current_address, int(top_n_fetch), mode=mode)
        else:
            txs = fetch_all_transactions(current_address)

        # 保險：若 fetch 發生異常或空值
        if not isinstance(txs, list) or not txs:
            processed_addresses += 1
            progress_text.text(f"[{mode}] 抓取地址 {processed_addresses}/{total_addresses}: {current_address}（無交易）")
            progress_bar.progress(min(1.0, processed_addresses / max(1, total_addresses)))
            continue

        parsed = filter_and_parse_transactions(txs, current_address, depth, from_address, mode)

        for tx in parsed:
            append_single_tx_to_csv(tx, csv_path)
            df_trace = pd.concat([df_trace, pd.DataFrame([tx])], ignore_index=True)

            counterparty = tx["From"] if mode == "in" else tx["To"]
            cp_lower = (counterparty or "").lower()
            if cp_lower and cp_lower != addr_lower and cp_lower not in seen:
                addresses_to_process.append((counterparty, depth + 1, f"L{depth}"))
                total_addresses += 1

        processed_addresses += 1
        progress_text.text(f"[{mode}] 抓取地址 {processed_addresses}/{total_addresses}: {current_address}")
        progress_bar.progress(min(1.0, processed_addresses / max(1, total_addresses)))

    progress_text.text(f"[{mode}] 抓取完成 ✅")
    progress_bar.empty()

    st.session_state.df_trace = df_trace
    st.dataframe(df_trace)
    download_buttons()

# ======== 入口：開始（先找檔，否則爬） ========
def start_tracking_or_plot(root_address):
    if not root_address:
        st.warning("請輸入有效的錢包地址")
        return

    existing_df = find_existing_trace(root_address)
    if existing_df is not None and not existing_df.empty:
        st.info("✅ 找到現有資料，直接繪圖。")
        st.session_state.df_trace = existing_df.copy()
        st.dataframe(st.session_state.df_trace)
        download_buttons()
        return

    st.info("未找到現有資料，開始爬蟲…")
    data_dir = ensure_current_folder(root_address)
    temp_csv_path = str(data_dir / f"{wallet6(root_address)}_temp.csv")
    try:
        if os.path.exists(temp_csv_path):
            os.remove(temp_csv_path)
    except Exception:
        pass

    st.session_state.df_trace = pd.DataFrame()
    st.session_state.output_file_base = temp_csv_path  # fallback 載入用

    if DIRECTION_MODE in ("in", "out"):
        _traverse_one_direction(root_address, DIRECTION_MODE, temp_csv_path)
    else:
        st.info("全部模式：分別執行『只轉入(上游)』與『只轉出(下游)』兩輪。")
        _traverse_one_direction(root_address, "in", temp_csv_path)
        _traverse_one_direction(root_address, "out", temp_csv_path)

    if not st.session_state.df_trace.empty:
        save_trace_files(st.session_state.df_trace, root_address)
        try:
            if os.path.exists(temp_csv_path):
                os.remove(temp_csv_path)
        except Exception:
            pass
        st.success(f"✅ 追蹤結束，共 {len(st.session_state.df_trace)} 筆交易")
    else:
        st.warning("此條件下未抓到任何交易。若你只抓純轉帳，可考慮放寬條件（包含合約互動/內部交易）。")

if st.button("開始（先找檔，否則爬）"):
    start_tracking_or_plot(ROOT_ADDRESS)

# ======== 桑基圖資料準備 ========
@st.cache_data
def prepare_graph_data(df):
    if df.empty:
        return {}, {}, 0, [], [], {}

    df = df.copy()
    df["Layer"] = df["層級"].str.extract(r'L(\\d+)').astype(int)

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
    for l in sorted(df["Layer"].unique()):
        in_layer_data[l] = df[(df["Layer"] == l) & (df["方向"] == "轉入")].copy()
        out_layer_data[l] = df[(df["Layer"] == l) & (df["方向"] == "轉出")].copy()

    max_layer = int(df["Layer"].max()) if not df.empty else 0
    layer_base_colors = [
        "rgba(44,160,44,0.4)", "rgba(31,119,180,0.4)", "rgba(255,127,14,0.4)",
        "rgba(214,39,40,0.4)", "rgba(148,103,189,0.4)", "rgba(140,86,75,0.4)"
    ]
    layer_colors = {layer: layer_base_colors[(layer - 1) % len(layer_base_colors)] for layer in range(1, max_layer + 1)}
    node_colors = [layer_colors.get(address_depth.get(lbl, 1), "lightblue") for lbl in all_labels]

    return in_layer_data, out_layer_data, max_layer, all_labels, node_colors, layer_colors

# ======== 繪圖（依 session 或歷史檔） ========
def load_df_for_plot(root: str) -> pd.DataFrame:
    if not st.session_state.df_trace.empty:
        return st.session_state.df_trace.copy()
    df = find_existing_trace(root) if root else None
    if df is not None:
        return df.copy()
    if st.session_state.output_file_base and os.path.exists(st.session_state.output_file_base):
        try:
            return pd.read_csv(st.session_state.output_file_base, encoding="utf-8-sig")
        except Exception:
            pass
    return pd.DataFrame()


df_for_plot = load_df_for_plot(ROOT_ADDRESS)

if not df_for_plot.empty:
    in_layer_data, out_layer_data, max_layer, all_labels, node_colors, layer_colors = prepare_graph_data(df_for_plot)

    col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
    if col_btn1.button("轉入 +1 層") and st.session_state.in_layer < max_layer:
        st.session_state.in_layer += 1
    if col_btn2.button("轉入 -1 層") and st.session_state.in_layer > 0:
        st.session_state.in_layer -= 1
    if col_btn3.button("轉出 +1 層") and st.session_state.out_layer < max_layer:
        st.session_state.out_layer += 1
    if col_btn4.button("轉出 -1 層") and st.session_state.out_layer > 0:
        st.session_state.out_layer -= 1

    # ✅ 已移除「畫圖階段限制 N 筆」，顯示全部
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
        if i in in_layer_data:
            trace = make_trace(in_layer_data[i])
            source += trace["source"]; target += trace["target"]; value += trace["value"]; color += trace["color"]
    for i in range(1, st.session_state.out_layer + 1):
        if i in out_layer_data:
            trace = make_trace(out_layer_data[i])
            source += trace["source"]; target += trace["target"]; value += trace["value"]; color += trace["color"]

    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=15, thickness=20, line=dict(color="black", width=0.5),
            label=all_labels, color=node_colors
        ),
        link=dict(source=source, target=target, value=value, color=color)
    )])
    fig.update_layout(
        title_text=f"ETH 流向圖（轉入 L{st.session_state.in_layer}，轉出 L{st.session_state.out_layer}）",
        font_size=10
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("目前沒有可繪圖的資料。請先點選『開始（先找檔，否則爬）』或載入既有檔案。")
