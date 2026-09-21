"""Streamlit 前端：僅以 HTTP 呼叫後端，不直接讀取資料庫與金鑰。"""
import os
from datetime import date

import httpx
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
st.set_page_config(page_title="TravelMate AI", page_icon="🧭", layout="wide")
st.title("🧭 TravelMate AI｜旅遊、住宿與消費決策助理")
st.caption("示範資料與估算工具，並非即時訂房或保證報價。")


def api_url():
    # Community Cloud 在 Secrets 設 TRAVELMATE_API_URL；本機可使用 .env。
    try:
        configured = st.secrets.get("TRAVELMATE_API_URL", "")
    except (FileNotFoundError, KeyError):
        configured = ""
    return str(configured or os.getenv("TRAVELMATE_API_URL", "http://127.0.0.1:8000")).rstrip("/")


def request(method: str, route: str, **kwargs):
    try:
        with httpx.Client(timeout=30) as client:
            response = client.request(method, api_url() + route, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        st.error(f"後端回應錯誤 {exc.response.status_code}：{exc.response.text[:300]}")
    except (httpx.RequestError, ValueError) as exc:
        st.error(f"無法連線後端：{exc}。請先啟動 FastAPI 或設定後端網址。")
    return None


with st.sidebar:
    st.subheader("後端狀態")
    health = request("GET", "/health")
    st.success("已連線") if health else st.warning("尚未連線")
    st.caption(api_url())

tab_plan, tab_data, tab_knowledge, tab_model = st.tabs(["行程規劃", "資料分析", "旅遊知識庫", "價格模型"])
with tab_plan:
    with st.form("plan"):
        col1, col2, col3 = st.columns(3)
        destination = col1.selectbox("目的地", ["台北", "東京", "京都", "首爾"])
        start_date = col2.date_input("出發日期", value=date.today())
        days = col3.number_input("旅遊天數", min_value=1, max_value=14, value=3)
        people = col1.number_input("人數", min_value=1, max_value=20, value=2)
        budget = col2.number_input("總預算（新台幣）", min_value=1, max_value=10_000_000, value=30000, step=1000)
        preference = col3.selectbox("旅遊偏好", ["文化", "自然", "美食", "地標"])
        live = st.checkbox("取得即時天氣與匯率（需網路）", value=False)
        submitted = st.form_submit_button("產生行程", type="primary")
    if submitted:
        result = request("POST", "/api/plan", json={"destination": destination,
            "start_date": start_date.isoformat(), "days": days, "people": people,
            "budget_twd": budget, "preference": preference, "use_live_api": live})
        if result:
            st.session_state["plan_result"] = result
    if "plan_result" in st.session_state:
        result = st.session_state["plan_result"]
        st.info(result["data_notice"])
        st.subheader("每日行程")
        st.dataframe(pd.DataFrame(result["itinerary"]), hide_index=True, use_container_width=True)
        left, right = st.columns(2)
        with left:
            st.subheader("住宿推薦")
            st.dataframe(pd.DataFrame(result["hotels"]), hide_index=True, use_container_width=True)
            st.subheader("景點推薦")
            st.dataframe(pd.DataFrame(result["spots"]), hide_index=True, use_container_width=True)
        with right:
            spending = result["spending"]
            st.subheader("每日預算與消費分析")
            st.metric("每日估算（TWD）", f"{spending['daily']:,.0f}")
            st.metric("總額 / 剩餘（TWD）", f"{spending['total']:,.0f} / {spending['remaining']:,.0f}")
            st.bar_chart(pd.Series(spending["components"], name="TWD"))
            st.caption(spending["assumptions"])
            st.subheader("AI 建議")
            st.write(result["advice"]["text"])
            st.caption(result["advice"]["source"])
            st.write("評論摘要：", result["reviews"]["summary"])
            if result["external"]:
                st.json(result["external"])
        with st.expander("查看 Agent 工具與 RAG 來源"):
            st.write("工具：", " → ".join(result["tool_trace"]))
            st.json(result["rag_sources"])

with tab_data:
    if st.button("載入住宿統計"):
        data = request("GET", "/api/analytics")
        if data:
            st.metric("資料筆數", data["count"])
            st.dataframe(pd.DataFrame(data["prices"]), hide_index=True)
            st.bar_chart(pd.DataFrame(data["by_room_type"]).set_index("room_type")["mean_price"])
            with st.expander("describe / groupby / corr"):
                st.write("describe", data["describe"])
                st.write("groupby", data["by_room_type"])
                st.write("corr", data["correlation"])

with tab_knowledge:
    st.write("上傳 PDF、TXT、CSV 或個人旅遊筆記；僅保留在後端記憶體，請勿上傳敏感個資。")
    file = st.file_uploader("選擇檔案（最多 5 MB）", type=["pdf", "txt", "csv"])
    if file and st.button("加入知識庫"):
        if file.size > 5 * 1024 * 1024:
            st.error("檔案不可超過 5 MB")
        else:
            response = request("POST", "/api/knowledge", files={"file": (file.name, file.getvalue(), file.type)})
            if response:
                st.success(response["message"] + f"（{response['chunks']} 個片段）")

with tab_model:
    st.caption("少量示範住宿資料建立的 RandomForest 模型，僅供學習，不能作為真實房價。")
    with st.form("model"):
        rating = st.slider("評分", 0.0, 5.0, 4.3)
        distance = st.number_input("距離市中心（公里）", 0.0, 100.0, 1.0)
        room_size = st.number_input("房間大小（平方公尺）", 1.0, 1000.0, 25.0)
        stars = st.slider("星級", 1, 5, 3)
        season = st.selectbox("季節價格級別", [1, 2, 3])
        predict_clicked = st.form_submit_button("預測示範價格")
    if predict_clicked:
        prediction = request("POST", "/api/predict", json={"rating": rating, "distance": distance,
            "room_size": room_size, "stars": stars, "season": season})
        if prediction:
            st.metric("預測房價（TWD / 晚）", f"{prediction['predicted_price_twd']:,.0f}")
            st.write("MAE / RMSE：", prediction["metrics"]["mae"], "/", prediction["metrics"]["rmse"])
