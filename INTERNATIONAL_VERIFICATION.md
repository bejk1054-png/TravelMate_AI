# 國際城市查詢驗收（2026-10-03，台灣時間）

實際呼叫公開地圖服務，非測試替身。數量為 Service 取得的候選，不是已驗證可訂住宿數量；Agent 最多顯示五間住宿。資料會變動。

| 輸入 | 景點候選 | 住宿候選 | 景點例子 |
|---|---:|---:|---|
| 東京 日本 | 7 | 5 | Tokyo Station Gallery |
| 巴黎 法國 | 8 | 10 | Treasury of Notre Dame |
| 倫敦 英國 | 8 | 9 | Benjamin Franklin House |
| 奈洛比 肯亞 | 8 | 10 | Nairobi National Museum |
| 雪梨 澳洲 | 8 | 9 | Australian Museum |
| 紐約 美國 | 8 | 10 | South Street Seaport Museum |

## 修正

- 奈洛比中文別名補齊；新增曼谷等常見城市譯名。
- 倫敦允許英國 Greater London 地址段，不能套用到其他國家同名城市。
- 請求結構化地址並核對國碼，避免跨國同名；重音 São/Sao 正規化。
- 缺地址的資料不再為了舊測試而直接放行；測試替身補上合理地址。
- 明確標示全時關閉／停用的景點排除；不把週一公休誤當永久關閉。
- 只有酒吧標記、沒有房間佐證的住宿候選排除。這不是所有誤標資料的完備識別器。
- 住宿卡補上來源地址與網站（來源有提供時），方便核對是否同一間。

## 獨立來源抽查

- 東京車站藝廊官方介紹：https://www.ejrcf.or.jp/gallery/english/institution.html
- 奈洛比 Serena 官方住宿介紹：https://www.serenahotels.com/nairobi
- Booking 實際住宿頁：https://www.booking.com/hotel/ke/nairobi-serena.html
- Booking 東京車站飯店：https://www.booking.com/hotel/jp/tokyo-station.html

以上網頁確認地點或住宿有收錄，不以搜尋引擎摘要當作即時房價／營業確認。

## 邊界與後續

45 項離線回歸測試通過。六城市網路抽查並非全球完整驗證；地圖可能過期或誤標，需持續查證官方營業狀態。來源未標示關閉的地方仍可能已停業；地址譯名不同也可能漏資料。Booking 無正式 API 憑證時只提供具名查詢，不承諾可訂或顯示虛構房價。不以 LLM 補造景點或湊滿筆數。
