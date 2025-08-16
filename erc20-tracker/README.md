# 🔍 ERC20 Token 金流追蹤與桑基圖可視化

使用 Streamlit + Etherscan API 追蹤 ERC20 Token 流入/流出。功能包含：
- 多層追蹤 (最多 10 層)
- 交易方向 & 日期篩選
- 匯出 CSV / Excel
- 互動式桑基圖

## 安裝依賴
pip install -r requirements.txt

## 執行程式
streamlit run app.py

## 部署到 Streamlit Cloud
1. 建立 GitHub Repo
2. 上傳 app.py、requirements.txt、README.md
3. 前往 Streamlit Cloud，點選 New App
4. 選擇 repo → branch → app.py → Deploy

## 環境變數
建議將 API_KEY 改為環境變數：
import os
API_KEY = os.getenv("ETHERSCAN_API_KEY")

然後在 Streamlit Cloud Secrets Manager 設定：
ETHERSCAN_API_KEY="你的 API KEY"
