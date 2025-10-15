# ETH 金流追蹤與桑基圖（Streamlit）

## 部署到 Streamlit Cloud
1. 建一個 GitHub repo（例如 `eth-trace-streamlit`）。
2. 把 `app.py`, `requirements.txt` 放進去（`.streamlit/secrets.toml` 不要 commit 到 GitHub）。
3. 在 streamlit.io → Deploy an app → 指向 `app.py`。
4. 在 App 的 Settings → Secrets 貼上：
```
ETHERSCAN_KEY = "你的 Etherscan API Key"
# 可選
# ETHERSCAN_BASE = "https://your-proxy.example.com"
```

## 本地執行
```bash
pip install -r requirements.txt
streamlit run app.py
```
