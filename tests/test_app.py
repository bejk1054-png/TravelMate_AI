"""離線煙霧測試；不依賴即時網路或 LLM 金鑰。"""
from fastapi.testclient import TestClient
from uuid import uuid4

from main import app
from rag.knowledge import chunks, extract, knowledge, session_knowledge
from services.analytics import demo_destination_records, hotels, spending, sqm_to_ping, summary
from services import booking, external, llm
from utils.location import destination_candidates

client = TestClient(app)


def test_health_and_plan():
    assert client.get("/health").json() == {"status": "ok"}
    response = client.post("/api/plan", json={"destination": "台北", "start_date": "2026-10-01",
        "days": 3, "people": 2, "budget_twd": 30000, "preference": "文化"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["itinerary"]) == 3
    assert body["hotels"] and body["plan_id"] > 0
    assert body["tool_trace"] == ["booking_tool", "hotel_tool", "budget_tool", "rag_tool"]
    assert body["booking_search_url"].startswith("https://www.booking.com/")
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
    paris = client.post("/api/plan", json={"destination": "巴黎 法國", "start_date": "2026-10-01",
        "days": 2, "people": 1, "budget_twd": 10000, "preference": "文化"})
    assert paris.status_code == 200
    paris_body = paris.json()
    assert paris_body["hotels"]
    assert all("非 Booking 即時價" in item["price_source"] for item in paris_body["hotels"])
    assert "ss=%E5%B7%B4%E9%BB%8E+%E6%B3%95%E5%9C%8B" in paris_body["booking_search_url"]


def test_analytics_prediction_and_validation():
    assert len(hotels()) >= 25
    assert summary()["count"] >= 25
    assert summary()["total_count"] == 40
    prediction = client.post("/api/predict", json={"rating": 4.2, "distance": 1.0,
        "room_size": 25, "stars": 3, "season": 2})
    assert prediction.status_code == 200, prediction.text
    assert prediction.json()["predicted_price_twd"] > 0
    taipei = client.get("/api/analytics", params={"destination": "台北"}).json()
    assert taipei["count"] == 40
    assert taipei["total_count"] == 40
    assert {item["destination"] for item in taipei["prices"]} == {"台北"}
    assert all("room_size" in item and "room_size_ping" in item for item in taipei["prices"])
    assert sqm_to_ping(25) == 7.6
    booking_fallback = client.get("/api/analytics", params={"destination": "台北",
        "checkin": "2026-10-01", "checkout": "2026-10-03", "people": 2}).json()
    assert booking_fallback["booking"]["available"] is False
    assert booking_fallback["count"] == 40
    assert "非 Booking 即時價" in booking_fallback["source"]
    assert booking_fallback["booking"]["search_url"].startswith("https://www.booking.com/")
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


def test_free_text_destination_geocoding_fallback(monkeypatch):
    """完整城市加國家查詢失敗時，應退回城市名稱，而不是讓整個行程失敗。"""
    calls = []

    def fake_get(url, params):
        if "geocoding" in url:
            calls.append(params["name"])
            if params["name"] == "巴黎 法國":
                raise RuntimeError("完整字串無法解析")
            return {"results": [{"name": "巴黎", "latitude": 48.86, "longitude": 2.35}]}
        return {"daily": {"time": ["2026-10-01"], "temperature_2m_max": [20],
                           "temperature_2m_min": [12], "precipitation_probability_max": [30]}}

    monkeypatch.setattr(external, "_get", fake_get)
    result = external.weather("巴黎 法國", "2026-10-01")
    assert calls == ["巴黎 法國", "巴黎"]
    assert result["available"] is True
    assert destination_candidates("New York, United States") == [
        "New York United States", "New York"
    ]


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
    custom = demo_destination_records("巴黎 法國", 40)
    assert len(custom) == 40
    assert {item["destination"] for item in custom} == {"巴黎 法國"}
    assert all("非 Booking 即時價" in item["price_source"] for item in custom)


def test_booking_official_search_normalization(monkeypatch):
    monkeypatch.setattr(booking, "_credentials", lambda: ("test-key", "12345"))
    monkeypatch.setattr(booking, "_geocode", lambda destination: {
        "name": destination, "latitude": 25.03, "longitude": 121.56
    })
    search_rows = [{"id": index, "currency": "TWD", "price": {"total": 6000 + index},
                    "url": f"https://www.booking.com/hotel/{index}"} for index in range(40)]

    def fake_post(path, payload):
        if path == "accommodations/search":
            assert payload["rows"] == 40
            return {"data": search_rows}
        return {"data": [{"id": index, "name": {"zh-tw": f"測試住宿 {index}"},
                           "rating": 4.5, "location": {"latitude": 25.04, "longitude": 121.57}}
                          for index in range(40)]}

    monkeypatch.setattr(booking, "_post", fake_post)
    result = booking.search_accommodations("台北", "2026-10-01", "2026-10-03", 2, 1, 40)
    assert result["available"] is True
    assert result["count"] == 40
    assert result["hotels"][0]["price_source"] == "Booking.com Demand API"
    assert result["hotels"][0]["price"] == 3000


def test_booking_v32_currency_and_price_normalization(monkeypatch):
    """確認 Demand API 3.2 的雙幣別與 display 價格不會變成物件或空值。"""
    monkeypatch.setattr(booking, "_credentials", lambda: ("test-key", "12345"))
    monkeypatch.setattr(booking, "_geocode", lambda destination: {
        "name": destination, "latitude": 25.03, "longitude": 121.56
    })
    monkeypatch.setattr(booking, "_post", lambda path, payload: {
        "data": [{"id": 1, "currency": {"accommodation": "JPY", "booker": "TWD"},
                  "price": {"display": {"booker": 7200}},
                  "url": "https://www.booking.com/hotel/test"}]
    } if path == "accommodations/search" else {"data": []})
    result = booking.search_accommodations("東京", "2026-10-01", "2026-10-03", 2, 1)
    assert result["hotels"][0]["currency"] == "TWD"
    assert result["hotels"][0]["price_total"] == 7200
    assert result["hotels"][0]["price"] == 3600
