# TravelMate AI

旅遊規劃示範站：Streamlit 前端 → FastAPI → 單一主 Agent → 地點／Booking／預算／RAG／天氣／匯率工具 → 可選 OpenAI 建議。前端不直接持有 API 金鑰。

## 目前功能與資料可信度

- 行程與住宿名稱：使用者搜尋時向 OpenStreetMap 查詢，顯示地圖來源連結；不保證開放、可訂或適合特定日期。公開地點搜尋採一小時快取與每秒至多一次呼叫；若暫時失敗，頁面顯示錯誤，不產生虛構地點。國名輸入以首都周邊代表，並明示範圍。
- 景點活動：依地點類型提出「參觀展覽／觀景」等建議；不是已核實的預約活動。門票僅當 OSM 明確標示免門票才列 0 元，其餘待查。
- 住宿價格：只有設定 Booking.com Demand API 官方 `BOOKING_API_KEY` 和 `BOOKING_AFFILIATE_ID` 後，才可取得最多 40 筆查詢日期房源與價格。沒有憑證時只顯示真實住宿名稱和 Booking 搜尋入口，房價待查。預訂前須核對稅費、房型、可訂性。公開地圖名稱與 Booking 搜尋結果不保證逐筆一致。
- 預算：餐食每人每日 900 元、當地交通 350 元為明示估算。缺房價或門票時只顯示已知／估算小計，不宣稱完整總額或剩餘預算。Booking 搜尋價為整團房數的每晚價，不再重複乘房數。不含機票及跨城交通。
- AI 建議：Render 設定 `OPENAI_API_KEY` 後使用 OpenAI Responses API；行程結果會標明 `connected`。未設定或請求失敗時明示「規則式備援（非 AI）」。私人上傳筆記不送至 OpenAI。
- 旅遊知識庫：PDF／TXT／CSV 上傳後暫存在後端記憶體，供 RAG 檢索；重啟後消失，請勿上傳敏感資料。
- 價格模型：以合成教學資料訓練 RandomForest，與真實 Booking 價格完全分離，不能用來查實際房價。
- NLP 評論分析程式保留作離線教學，但示範評論並非上述真實飯店的住客評論，因此不在即時行程中呈現。
- 已移除重複且會顯示合成住宿的「資料分析」頁與 `/api/analytics`。Pandas／NumPy 分析程式保留供模型教學，不進入訂房推薦。

## 資料流

目的地／日期／預算 → `frontend/app.py` → `main.py` → `agents/travel_agent.py` → `tools/travel_tools.py` → `services/places.py`、`services/booking.py`、`rag/knowledge.py` → `services/llm.py` → 回傳 Streamlit。

## Windows + VS Code 本機啟動

建議 Python 3.12。在專案根目錄：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn main:app --reload --port 8000
```

另一個終端機執行 `py -m streamlit run frontend/app.py`（若已啟用虛擬環境，也可 `python -m streamlit run frontend/app.py`）。

測試：`python -m pytest -q`。離線測試不需要任何 API 金鑰；本機已驗證台北與肯亞即時地點查詢。

## Render + Streamlit Community Cloud

1. 將程式提交至 GitHub。`.env`、資料庫、模型輸出及 `.venv` 不可上傳；`.env.example` 可以上傳。
2. Render Web Service：Python 3.12，build `pip install -r requirements.txt`，start `uvicorn main:app --host 0.0.0.0 --port $PORT`。本 repo 亦提供 `render.yaml`。在 Render Environment 設 `OPENAI_API_KEY`；若有 Booking 官方合作憑證再設 `BOOKING_API_KEY` 和 `BOOKING_AFFILIATE_ID`。重新部署後用 `/api/ai/status` 檢查 `configured`，再產生一次行程確認實際 `connected`。
3. Streamlit Community Cloud：入口 `frontend/app.py`，Python 3.12；Secrets 設 `TRAVELMATE_API_URL = "https://你的-Render-網址.onrender.com"`。**不要**把後端金鑰放 Streamlit Secrets 或 GitHub。
4. 部署檢查：`/health` 為 `ok`、`/api/ai/status` 狀態符合設定；台北及肯亞行程可顯示地點來源；未知價格是「待查」；Booking 查價連結有效；知識庫及模型頁可操作。

## 外部服務限制

本專案使用 [OpenStreetMap Nominatim 公開服務](https://operations.osmfoundation.org/policies/nominatim/) 做低流量、使用者觸發的地點查詢，需顯示來源並受用量限制；流量增長時應改為自架或正式商用地點 API。Booking 即時價格需要 [Booking.com Demand API 官方權限](https://developers.booking.com/demand/docs/development-guide/authentication)。AI 呼叫使用 [OpenAI Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)。
