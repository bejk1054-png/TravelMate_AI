# TravelMate AI｜旅遊、住宿與消費決策助理

可在無 API Key、無網路情況下執行核心行程規劃；CSV 住宿、景點與評論均為**示範資料**，金額為新台幣估算，沒有訂房與即時房價能力。目前支援台北、台中、高雄、東京、京都、大阪、札幌、首爾、釜山、新加坡共 10 個目的地，內建 40 筆住宿與 40 筆景點示範資料。

住宿推薦與資料分析同時顯示房間的平方公尺與約合坪數，換算使用 `1 坪 ≈ 3.3058 平方公尺`。資料分析預設只顯示目前選定目的地，也可手動切換「全部目的地」檢視 40 筆住宿。

## 架構與資料流

```text
使用者 → frontend/app.py (Streamlit)
       → main.py / api/schemas.py (FastAPI 驗證)
       → agents/travel_agent.py (唯一主 Agent，規則式選工具)
       → tools/travel_tools.py (單一動作)
       → services/analytics.py、nlp.py、external.py、llm.py (商業邏輯)
       → data/*.csv、models/price_model.py、rag/knowledge.py、database/repository.py
       → LLM（可選，失敗回規則式建議）→ FastAPI JSON → Streamlit
```

| 功能 | 資料從哪裡進來 → 經過什麼 → 哪個檔案處理 → 最後送到哪裡 |
|---|---|
| MVP 行程 | 網頁表單 → API 驗證、Agent 排程 → `frontend/app.py`、`main.py`、`agents/travel_agent.py` → 網頁行程表 |
| Pandas / NumPy | CSV → 清理、篩選、排序、describe/groupby/corr、費用加總 → `services/analytics.py` → 網頁圖表與預算 |
| ML | CSV 特徵 → train/test、RandomForest、MAE/RMSE、joblib → `models/price_model.py` → `/api/predict` 與網頁 |
| NLP | 住宿示範評論 → 詞典情緒、優缺點摘要 → `services/nlp.py` → 網頁評論摘要 |
| RAG | TXT/PDF/CSV/筆記 → 切塊、字元 TF-IDF embedding、cosine retriever → `rag/knowledge.py` → Agent 的有來源內容與 LLM |
| Agent / Tools | 表單 → 主 Agent 決定工具 → `agents/travel_agent.py`、`tools/travel_tools.py` → 預算、住宿、知識與外部資料 |
| 外部 API | 目的地與日期 → Open-Meteo、Frankfurter 並處理錯誤 → `services/external.py` → 網頁即時資訊或不可用提示 |
| Database | 規劃結果 → SQLite 寫入與查詢 → `database/repository.py` → `/api/plans` |

MCP 概念：`tools/travel_tools.py` 是穩定的工具介面，Agent 呼叫它們；若日後換成真正 MCP server/client，應在工具邊界加入 MCP adapter。本版本**沒有宣稱已實作 MCP 協定或 MCP server**。

## Windows + VS Code 本機啟動

請在 `TravelMate_AI` 目錄開啟 VS Code 終端機，建議 Python 3.12：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

若 `py` 不存在，改用 `python -m venv .venv`、`python -m pip ...` 和 `python -m streamlit ...`。先開終端機 A：

```powershell
py -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

再開終端機 B（務必從 `TravelMate_AI` 根目錄執行）：

```powershell
py -m streamlit run frontend/app.py
```

預設後端為 `http://127.0.0.1:8000`；瀏覽 `http://127.0.0.1:8000/docs` 查看 API。測試：`py -m pytest -q`。首次預測會訓練模型並建立被忽略的 `models/hotel_price.joblib`；首次規劃建立 `data/travelmate.db`。

複製 `.env.example` 為 `.env`，可填 `OPENAI_API_KEY`；不填時仍可執行。勾選即時資料才呼叫外部天氣與匯率 API。日期若超出預報範圍會顯示不可用，不會捏造天氣。LLM 失敗會顯示規則式備援。上傳知識庫按隨機工作階段識別碼隔離，存在後端記憶體並於重啟或快取淘汰後消失；這不是登入機制，**仍勿上傳敏感筆記**。公開 API 的行程歷史查詢預設關閉；若在可信本機環境要開啟，設定 `ENABLE_HISTORY_API=1`。

## Git / GitHub

`.env`、SQLite 和訓練模型已由 `.gitignore` 排除；`.env.example`、CSV 與內建知識文件需提交。自行建立 GitHub 空 repo 後，從 `TravelMate_AI` 執行：

```powershell
git init
git add .
git status --short
git commit -m "Build TravelMate AI MVP"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/TravelMate_AI.git
git push -u origin main
```

推送前請檢查 `git status` 和 `git ls-files`，確認沒有 `.env` 或個人資料。

## 雲端部署

建議後端部署 Render，前端部署 Streamlit Community Cloud，兩者指向同一 GitHub repo：

1. Render 建立 Python Web Service，root directory 留空（若上層目錄才是 repo 根則設 `TravelMate_AI`）；build `pip install -r requirements.txt`；start `uvicorn main:app --host 0.0.0.0 --port $PORT`；Python 設為 3.12。也可使用 `render.yaml` blueprint，其 `rootDir: .` 假設本目錄為 repo 根。選用 LLM 時在 Render Secrets/Environment 設 `OPENAI_API_KEY`。
2. Streamlit Community Cloud 的 main file path 設 `TravelMate_AI/frontend/app.py`（若 repo 根是此目錄則 `frontend/app.py`）；Advanced settings 選 Python 3.12，Secrets 加入 `TRAVELMATE_API_URL = "https://你的後端.onrender.com"`。Streamlit 會尋找專案根 `requirements.txt`，若建立 repo 根在上層，建議改讓本目錄做 repo 根。前端與後端同時安裝完整依賴是較簡單、但較重的部署方式。
3. 上線後測試 `/health`、表單、分析、模型與知識上傳。Render 免費服務閒置後會休眠，前端允許 90 秒等待首次喚醒。免費/無持久化磁碟的 SQLite、joblib 和上傳索引可能在重啟後消失；正式資料應改用託管資料庫及持久化儲存。不要在前端 Secrets 放後端的 LLM 金鑰。

部署前檢查：從根目錄執行 import 與 pytest；確認 `requirements.txt`（含 `python-multipart`）、Python 3.12、`frontend/app.py` 路徑、`data/*.csv` 與 `data/knowledge.txt` 已提交、`models/*.joblib` 可在啟動時產生、`.env` 未提交、後端環境變數與 Streamlit 的後端 URL 正確。若 repo 根改為上層，需同步修改 `render.yaml` 的 `rootDir`。

## 故障定位範例

- 網頁連線失敗 → 前端 `frontend/app.py` 的 `request` → 後端未啟動或 URL 不對 → 啟動 uvicorn／修正 `TRAVELMATE_API_URL`。
- 模型載入失敗 → 模型 `models/price_model.py` 的 `load_or_train` → joblib 檔與目前版本不相容 → 刪除已產生的模型快取再訓練（勿刪 CSV）。
- 空景點 → 資料層 `services/analytics.py` 的 `spots` → 目的地不在示範 CSV → 增加對應資料及 UI 選項。

此專案的 ML 與 NLP 是教學基線；稀疏 TF-IDF 不是神經語意 embedding，統計指標也不能代表真實旅宿市場表現。
