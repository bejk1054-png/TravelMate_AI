# TravelMate AI 隱私說明

使用者輸入的目的地、日期、人數、預算與偏好會傳送至 Render 後端，以生成行程並保存基本請求與結果供教學用途；公開行程歷史查詢預設關閉。上傳的旅遊筆記僅保存在後端記憶體，服務重啟後消失，請勿上傳敏感資訊。

查詢景點時，目的地與偏好可能傳送給 Google Places API 或 OpenStreetMap 地點服務；Google Places 的地點名稱、評分及評論數不寫入本專案資料庫，也不傳給 OpenAI 模型。使用者選用即時天氣、匯率或 Booking 時，相關查詢資料亦會送至各自的服務。Google 對資料的處理適用 [Google 隱私權政策](https://policies.google.com/privacy)。

我們不收集信用卡資料，不在前端儲存 Google 或 OpenAI API 金鑰。本展示站暫不提供自助刪除個別行程紀錄，請勿在輸入欄或公開議題貼出可識別個人的資訊。
