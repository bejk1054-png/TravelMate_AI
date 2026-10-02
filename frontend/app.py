"""Streamlit 前端：僅以 HTTP 呼叫後端，不直接讀取資料庫與金鑰。"""
import os
from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pathlib import Path
from presentation import setup_style, render_plan

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
st.set_page_config(page_title="TravelMate AI · 你的下一趟旅程", page_icon="🧭", layout="wide", initial_sidebar_state="collapsed")
setup_style()
SQM_PER_PING = 3.305785
if "rag_session_id" not in st.session_state:
    st.session_state["rag_session_id"] = str(uuid4())


def api_url():
    # Community Cloud 在 Secrets 設 TRAVELMATE_API_URL；本機可使用 .env。
    try:
        configured = st.secrets.get("TRAVELMATE_API_URL", "")
    except (FileNotFoundError, KeyError):
        configured = ""
    return str(configured or os.getenv("TRAVELMATE_API_URL", "http://127.0.0.1:8000")).rstrip("/")


def request(method: str, route: str, quiet: bool = False, timeout: int = 90, **kwargs):
    try:
        # Render 免費服務休眠後重新啟動可能超過 50 秒，避免首個請求過早失敗。
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, api_url() + route, **kwargs)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("回應格式不正確")
            return data
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", "未知錯誤")
        except (ValueError, AttributeError):
            detail = exc.response.text[:300]
        if not quiet:
            if isinstance(detail, list):
                st.error("輸入內容未通過檢查，請確認目的地、日期、人數與預算。")
            else:
                st.error(f"服務暫時無法完成請求（{exc.response.status_code}）。請稍後重試。")
    except (httpx.RequestError, ValueError):
        if not quiet:
            st.error("服務連線逾時或回應異常。免費服務可能正在啟動，請稍後重新按下查詢。")
    return None


@st.cache_data(ttl=60, show_spinner=False)
def service_status(base_url):
    """短暫快取狀態，避免每次操作都等待免費後端；與結果查詢分開。"""
    health = request("GET", "/health/details", quiet=True, timeout=10)
    ai = request("GET", "/api/ai/status", quiet=True, timeout=10) if health else None
    return health, ai


def hotel_table(rows: list[dict]) -> pd.DataFrame:
    """將後端住宿欄位轉成中文顯示，並加入平方公尺對應的約略坪數。"""
    frame = pd.DataFrame(rows)
    if "room_size" in frame.columns:
        numeric_size = pd.to_numeric(frame["room_size"], errors="coerce")
        frame["room_size_ping"] = (numeric_size / SQM_PER_PING).round(1)
    return frame.rename(columns={
        "name": "住宿名稱", "destination": "目的地", "room_type": "房型",
        "price": "每晚價格（TWD）", "rating": "評分", "distance": "距離（公里）",
        "price_total": "入住期間總價", "currency": "幣別", "price_source": "價格來源",
        "room_size": "房間大小（平方公尺）", "room_size_ping": "約合坪數",
        "stars": "星級", "season": "季節級別",
        "booking_url": "Booking.com 訂房連結", "booking_id": "Booking ID",
        "map_url": "地圖來源",
    })


def show_hotel_table(rows: list[dict]) -> None:
    """顯示住宿表格；有 Booking 網址時直接提供可點擊的訂房按鈕。"""
    frame = hotel_table(rows)
    column_config = {}
    if "Booking.com 訂房連結" in frame.columns:
        column_config["Booking.com 訂房連結"] = st.column_config.LinkColumn(
            "Booking.com 訂房連結", display_text="前往訂房"
        )
    if "地圖來源" in frame.columns:
        column_config["地圖來源"] = st.column_config.LinkColumn("地圖來源", display_text="查看地點")
    st.dataframe(frame, hide_index=True, use_container_width=True,
                 column_config=column_config)


with st.sidebar:
    st.subheader("TravelMate AI")
    st.caption("旅遊、住宿與預算，一起規劃。")
    health, ai = service_status(api_url())
    if health and health.get("status") == "ok":
        st.success("已連線")
    elif health:
        st.warning("服務部分異常")
    else:
        st.warning("尚未連線")
    if ai:
        st.caption("AI 已設定，實際連線以查詢結果為準" if ai.get("configured") else "目前提供規則式旅遊建議")
    if st.button("重新檢查連線"):
        service_status.clear()
        st.rerun()
    if health and health.get("services"):
        with st.expander("查看服務狀態"):
            st.json(health["services"])
    st.markdown("[使用條款](https://github.com/bejk1054-png/TravelMate_AI/blob/main/TERMS.md) · "
                "[隱私說明](https://github.com/bejk1054-png/TravelMate_AI/blob/main/PRIVACY.md)")

tab_plan, tab_knowledge, tab_model = st.tabs(["行程規劃", "旅遊知識庫", "價格模型"])
with tab_plan:
    st.subheader("想去哪裡走走？")
    st.caption("輸入城市與國家，讓查詢更準確。")
    with st.form("plan"):
        col1, col2, col3 = st.columns(3)
        destination = col1.text_input("目的地", value="台北", max_chars=80,
                                      placeholder="例如：台北、巴黎 法國")
        # 雲端通常使用 UTC；以台灣日期避免凌晨預設為昨天。
        start_date = col2.date_input("出發日期", value=datetime.now(ZoneInfo('Asia/Taipei')).date())
        days = col3.number_input("旅遊天數", min_value=1, max_value=14, value=3)
        people = col1.number_input("人數", min_value=1, max_value=20, value=2)
        budget = col2.number_input("總預算（新台幣）", min_value=1, max_value=10_000_000, value=30000, step=1000)
        preference = col3.selectbox("旅遊偏好", ["文化", "自然", "美食", "地標"])
        live = st.checkbox("取得即時天氣與匯率（需網路）", value=False)
        submitted = st.form_submit_button("開始規劃旅程", type="primary", use_container_width=True)
    if submitted:
        # 新查詢開始時先移除舊結果；後端失敗不可繼續顯示上一筆行程。
        st.session_state.pop("plan_result", None)
        st.session_state.pop("plan_query", None)
        query = {"destination": destination.strip(), "start_date": start_date.isoformat(),
                 "days": days, "people": people, "budget_twd": budget,
                 "preference": preference, "use_live_api": live}
        result = None
        if not query['destination']:
            st.error("請先輸入目的地，例如「台北」或「巴黎 法國」。")
        else:
            with st.spinner("正在搜尋景點與住宿，整理你的旅程…"):
                result = request("POST", "/api/plan", json={**query,
                    "session_id": st.session_state["rag_session_id"]})
        # 檢查必要欄位，避免前後端更新不同步造成使用者看到程式錯誤。
        if result and not {'destination', 'itinerary', 'hotels', 'spots', 'spending',
                           'advice', 'data_notice', 'tool_trace', 'rag_sources'}.issubset(result):
            st.error("服務正在更新，回應資料尚未完整。請稍後重新查詢。")
            result = None
        if result:
            st.session_state["plan_result"] = result
            st.session_state["plan_query"] = query
    if "plan_result" in st.session_state:
        result = st.session_state["plan_result"]
        query = st.session_state.get("plan_query", {})
        if query and any(query.get(k) != v for k, v in {
            'destination': destination.strip(), 'start_date': start_date.isoformat(),
            'days': days, 'people': people, 'budget_twd': budget,
            'preference': preference, 'use_live_api': live}.items()):
            st.info("下方為上一次查詢結果；請按「開始規劃旅程」套用修改後的條件。")
        render_plan(result)
    else:
        st.markdown('<div class="tm-empty">你的旅程從這裡開始。填好目的地與偏好，即可查看行程、住宿和預算。</div>', unsafe_allow_html=True)

with tab_knowledge:
    st.write("上傳 PDF、TXT、CSV 或個人旅遊筆記，系統會切分內容並建立暫存 RAG 檢索索引。")
    st.info("加入後請回到「行程規劃」重新產生行程；相關片段會顯示在「相關旅遊筆記與處理資訊」。")
    st.caption("內容只保留在目前後端記憶體，服務重啟後消失；請勿上傳敏感個資。")
    file = st.file_uploader("選擇檔案（最多 5 MB）", type=["pdf", "txt", "csv"])
    if file and st.button("加入知識庫"):
        if file.size > 5 * 1024 * 1024:
            st.error("檔案不可超過 5 MB")
        else:
            response = request("POST", "/api/knowledge",
                data={"session_id": st.session_state["rag_session_id"]},
                files={"file": (file.name, file.getvalue(), file.type)})
            if response:
                st.success(response["message"] + f"（{response['chunks']} 個片段）")

with tab_model:
    st.caption("少量示範住宿資料建立的 RandomForest 模型，僅供學習，不能作為真實房價。")
    with st.form("model"):
        rating = st.slider("評分", 0.0, 5.0, 4.3)
        distance = st.number_input("距離市中心（公里）", 0.0, 100.0, 1.0)
        room_size = st.number_input("房間大小（平方公尺）", 1.0, 1000.0, 25.0,
                                    help="1 坪約等於 3.3058 平方公尺")
        st.caption(f"目前輸入約 {room_size / SQM_PER_PING:.1f} 坪（1 坪約 3.3058 平方公尺）")
        stars = st.slider("星級", 1, 5, 3)
        season = st.selectbox("季節價格級別", [1, 2, 3])
        predict_clicked = st.form_submit_button("預測示範價格")
    if predict_clicked:
        prediction = request("POST", "/api/predict", json={"rating": rating, "distance": distance,
            "room_size": room_size, "stars": stars, "season": season})
        if prediction:
            st.metric("預測房價（TWD / 晚）", f"{prediction['predicted_price_twd']:,.0f}")
            st.write("MAE / RMSE：", prediction["metrics"]["mae"], "/", prediction["metrics"]["rmse"])
