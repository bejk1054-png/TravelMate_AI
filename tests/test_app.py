"""離線煙霧測試；不依賴即時網路或 LLM 金鑰。"""
from fastapi.testclient import TestClient
from uuid import uuid4

from main import app
from rag.knowledge import chunks, extract, knowledge, session_knowledge
from services.analytics import hotels, spending, sqm_to_ping, summary
from services import external, llm

client = TestClient(app)


def test_health_and_plan():
    assert client.get("/health").json() == {"status": "ok"}
    response = client.post("/api/plan", json={"destination": "台北", "start_date": "2026-10-01",
        "days": 3, "people": 2, "budget_twd": 30000, "preference": "文化"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["itinerary"]) == 3
    assert body["hotels"] and body["plan_id"] > 0
    assert body["tool_trace"] == ["hotel_tool", "budget_tool", "rag_tool"]
    assert client.get("/api/plans").status_code == 403


def test_all_supported_destinations_and_tight_budget_fallback():
    for destination in ("台北", "台中", "高雄", "東京", "京都", "大阪", "札幌", "首爾", "釜山", "新加坡"):
        response = client.post("/api/plan", json={"destination": destination,
            "start_date": "2026-10-01", "days": 2, "people": 1,
            "budget_twd": 1000, "preference": "文化"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["destination"] == destination
        assert body["hotels"]
        assert body["hotels"][0]["price"] == min(item["price"] for item in body["hotels"])
        assert destination in body["advice"]["text"]
    assert client.post("/api/plan", json={"destination": "巴黎", "start_date": "2026-10-01",
        "days": 2, "people": 1, "budget_twd": 10000, "preference": "文化"}).status_code == 422


def test_analytics_prediction_and_validation():
    assert len(hotels()) >= 25
    assert summary()["count"] >= 25
    assert summary()["total_count"] == 40
    prediction = client.post("/api/predict", json={"rating": 4.2, "distance": 1.0,
        "room_size": 25, "stars": 3, "season": 2})
    assert prediction.status_code == 200, prediction.text
    assert prediction.json()["predicted_price_twd"] > 0
    taipei = client.get("/api/analytics", params={"destination": "台北"}).json()
    assert taipei["count"] == 4
    assert taipei["total_count"] == 40
    assert {item["destination"] for item in taipei["prices"]} == {"台北"}
    assert all("room_size" in item and "room_size_ping" in item for item in taipei["prices"])
    assert sqm_to_ping(25) == 7.6
    assert spending(4, 2, 2000, [0, 0, 0, 0], 30000)["components"]["住宿"] == 6000
    assert client.post("/api/plan", json={"destination": " ", "start_date": "2026-10-01",
        "days": 0, "people": 2, "budget_twd": 30000}).status_code == 422


def test_knowledge_upload():
    assert chunks("旅遊筆記")
    assert extract("note.txt", "台北捷運方便".encode()) == "台北捷運方便"
    session_id = str(uuid4())
    response = client.post("/api/knowledge", data={"session_id": session_id},
        files={"file": ("note.txt", "台北捷運方便".encode(), "text/plain")})
    assert response.status_code == 200, response.text
    assert session_knowledge(session_id).retrieve("台北捷運")
    assert all(item["source"] != "note.txt" for item in session_knowledge(str(uuid4())).retrieve("台北捷運"))
    assert "台北" in knowledge.retrieve("台北 美食", k=1)[0]["text"]


def test_weather_uses_supported_city_coordinates(monkeypatch):
    # 中文目的地應直接轉成固定座標，不再依賴外部地名解析。
    def fake_get(url, params):
        assert "forecast" in url
        assert params["latitude"] == 25.0330
        return {"daily": {"time": ["2026-09-21"], "temperature_2m_max": [30],
            "temperature_2m_min": [24], "precipitation_probability_max": [40]}}

    monkeypatch.setattr(external, "_get", fake_get)
    result = external.weather("台北", "2026-09-21")
    assert result == {"available": True, "date": "2026-09-21", "location": "台北",
        "max_c": 30, "min_c": 24, "rain_probability": 40}


def test_currency_and_personalized_fallback(monkeypatch):
    monkeypatch.setattr(external, "_get", lambda url, params: {
        "result": "success", "rates": {"JPY": 4.9}, "time_last_update_utc": "today"})
    assert external.currency("TWD", "JPY")["rate"] == 4.9
    monkeypatch.setattr(llm, "secret", lambda name, default="": "")
    result = llm.advice({"destination": "台北", "days": 4, "preference": "美食",
        "hotel": {"name": "測試旅館", "price": 2000}, "external": {},
        "spending": {"components": {"住宿": 16000, "景點": 3000}, "total": 19000,
                     "remaining": -4000, "daily": 4750, "within_budget": False}})
    assert "超出預算 4,000 元" in result["text"]
    assert "測試旅館" in result["text"]


def test_destination_data_is_complete():
    supported = {"台北", "台中", "高雄", "東京", "京都", "大阪", "札幌", "首爾", "釜山", "新加坡"}
    frame = hotels()
    assert set(frame["destination"]) == supported
    assert frame.groupby("destination").size().eq(4).all()
    assert set(external.DESTINATION_COORDINATES) == supported
