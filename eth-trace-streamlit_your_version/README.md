# ETH 金流追蹤與桑基圖（Streamlit 版本）

## 📦 功能說明
- 透過 Etherscan API 追蹤錢包金流
- 可設定 Top-N 過濾金額、層級深度、自動避開「PageNo x Offset」錯誤
- 自動儲存追蹤結果（CSV/XLSX），下次開啟可直接繪圖
- 使用桑基圖視覺化資金流（上游/下游分層）

## 🚀 本地執行方式
```bash
pip install -r requirements.txt
streamlit run app.py
```

## ☁️ 部署到 Streamlit Cloud
1. 將 `app.py` 和 `requirements.txt`（還有這個 `README.md`）上傳到 GitHub。
2. 登入 [https://streamlit.io](https://streamlit.io) → Deploy an app。
3. 選擇 repo 與 branch，指向 `app.py`。
4. 點擊「Deploy」。

（⚠️ 這個版本的 API Key 寫在 `app.py` 內，如要保密，建議改用 `st.secrets` 機制）

## 📂 檔案結構
```
.
├── app.py                # Streamlit 主程式
├── requirements.txt      # 套件清單
└── README.md             # 說明文件
```

## 🛡️ 提醒
- 此版本僅支援「外部交易」（normal tx），不含 internal tx 或 ERC-20。
- 若 Etherscan API 出現 rate limit，系統會自動退避重試。
- 所有下載資料預設存於執行目錄下。

---
📌 作者：你  
📅 自訂版本：不改動原始功能
