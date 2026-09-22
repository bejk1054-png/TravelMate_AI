"""離線煙霧測試；不依賴即時網路或 LLM 金鑰。"""
from fastapi.testclient import TestClient
from uuid import uuid4

from main import app
from rag.knowledge import chunks, extract, knowledge, session_knowledge
from services.analytics import hotels, spending, sqm_to_ping, summary
from services import booking, external, llm, location
from services import places
from tools.travel_tools import budget_tool
from services.location import city_search_name, destination_currency, resolve_country_code, split_city_country
from utils.location import destination_candidates

client = TestClient(app)


def _fake_places(destination, preference=""):
    return {"area": destination, "capital_fallback": False,
            "spot_source": "OpenStreetMap", "spot_message": "無 Google 評分",
            "hotels": [{"name": "實際測試飯店", "price": None, "currency": None,
                        "map_url": "https://www.openstreetmap.org/node/1"}],
            "spots": [{"name": "實際測試景點", "activity": "參觀", "cost_twd_per_person": None,
                       "fee_note": "待查", "map_url": "https://www.openstreetmap.org/node/2"}]}


def test_health_and_plan(monkeypatch):
    monkeypatch.setattr(places, "places", _fake_places)
    monkeypatch.setattr(__import__("agents.travel_agent", fromlist=["places"]), "places", _fake_places)
    monkeypatch.setattr(__import__("tools.travel_tools", fromlist=["places"]), "places", _fake_places)
    assert client.get("/health").json() == {"status": "ok"}
    response = client.post("/api/plan", json={"destination": "台北", "start_date": "2026-10-01",
        "days": 3, "people": 2, "budget_twd": 30000, "preference": "文化"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["itinerary"]) == 3
    assert body["hotels"] and body["plan_id"] > 0
    assert body["tool_trace"] == ["booking_tool", "spot_tool", "hotel_tool", "budget_tool", "rag_tool"]
    assert body["spending"]["total"] is None
    assert body["advice"]["status"] == "unconfigured"
    assert "reviews" not in body  # 教學評論不可冒稱為真實住宿評論
    assert body["booking_search_url"].startswith("https://www.booking.com/")
    assert client.get("/api/plans").status_code == 403


def test_all_supported_destinations_and_tight_budget_fallback(monkeypatch):
    monkeypatch.setattr(__import__("agents.travel_agent", fromlist=["places"]), "places", _fake_places)
    monkeypatch.setattr(__import__("tools.travel_tools", fromlist=["places"]), "places", _fake_places)
    for destination in ("台北", "台中", "高雄", "東京", "京都", "大阪", "札幌", "首爾", "釜山", "新加坡"):
        response = client.post("/api/plan", json={"destination": destination,
            "start_date": "2026-10-01", "days": 2, "people": 1,
            "budget_twd": 1000, "preference": "文化"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["destination"] == destination
        assert body["hotels"]
        assert body["hotels"][0]["price"] is None
        assert destination in body["advice"]["text"]
    paris = client.post("/api/plan", json={"destination": "巴黎 法國", "start_date": "2026-10-01",
        "days": 2, "people": 1, "budget_twd": 10000, "preference": "文化"})
    assert paris.status_code == 200
    paris_body = paris.json()
    assert paris_body["hotels"]
    assert all(item["price"] is None for item in paris_body["hotels"])
    assert "ss=%E5%B7%B4%E9%BB%8E+%E6%B3%95%E5%9C%8B" in paris_body["booking_search_url"]


def test_analytics_prediction_and_validation():
    assert len(hotels()) >= 25
    assert summary()["count"] >= 25
    assert summary()["total_count"] == 40
    prediction = client.post("/api/predict", json={"rating": 4.2, "distance": 1.0,
        "room_size": 25, "stars": 3, "season": 2})
    assert prediction.status_code == 200, prediction.text
    assert prediction.json()["predicted_price_twd"] > 0
    assert client.get("/api/analytics").status_code == 404
    assert sqm_to_ping(25) == 7.6
    assert client.get("/api/ai/status").status_code == 200
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
    assert knowledge.retrieve("肯亞 文化") == []
    assert all("首爾" not in item["text"] for item in knowledge.retrieve("東京 文化"))


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
    """城市加國家應帶 ISO 國碼查地名，不應錯誤退回其他國家的同名城市。"""
    location.country_capital.cache_clear()

    def fake_location_get(url, params):
        if "geocoding" in url:
            assert params["name"] == "巴黎"
            assert params["countryCode"] == "FR"
            return {"results": [{"name": "巴黎", "latitude": 48.86, "longitude": 2.35}]}
        raise AssertionError("城市查詢不應呼叫首都 API")

    def fake_weather_get(url, params):
        return {"daily": {"time": ["2026-10-01"], "temperature_2m_max": [20],
                           "temperature_2m_min": [12], "precipitation_probability_max": [30]}}

    monkeypatch.setattr(location, "_get_json", fake_location_get)
    monkeypatch.setattr(external, "_get", fake_weather_get)
    result = external.weather("巴黎 法國", "2026-10-01")
    assert result["available"] is True
    assert split_city_country("New York United States") == ("New York", "US")
    assert city_search_name("紐約") == "New York City"
    assert destination_candidates("New York, United States") == [
        "New York United States", "New York"
    ]


def test_country_only_uses_capital_and_standard_currency(monkeypatch):
    """只輸入肯亞時，使用首都代表天氣並解析 KES，不可回傳空白匯率。"""
    location.country_capital.cache_clear()
    monkeypatch.setattr(location, "_get_json", lambda url, params: [
        {"page": 1}, [{"capitalCity": "Nairobi", "latitude": "-1.2864",
                       "longitude": "36.8172"}]
    ])
    monkeypatch.setattr(external, "_get", lambda url, params: {
        "daily": {"time": ["2026-10-01"], "temperature_2m_max": [27],
                  "temperature_2m_min": [14], "precipitation_probability_max": [10]}
    })
    weather = external.weather("肯亞", "2026-10-01")
    assert weather["available"] is True
    assert weather["location"] == "Nairobi（以首都代表）"
    assert resolve_country_code("肯亞") == "KE"
    assert resolve_country_code("肯尼亚") == "KE"
    assert destination_currency("肯亞") == "KES"


def test_currency_and_personalized_fallback(monkeypatch):
    monkeypatch.setattr(external, "_get", lambda url, params: {
        "result": "success", "rates": {"JPY": 4.9}, "time_last_update_utc": "today"})
    assert external.currency("TWD", "JPY")["rate"] == 4.9
    monkeypatch.setattr(llm, "secret", lambda name, default="": "")
    result = llm.advice({"destination": "台北", "days": 4, "preference": "美食",
        "hotel": {"name": "測試旅館", "price": 2000}, "external": {},
        "spending": {"components": {"住宿": 16000, "景點": 3000}, "total": 19000,
                     "remaining": -4000, "daily": 4750, "within_budget": False}})
    assert "超出預算" in result["text"] and "4,000 元" in result["text"]
    assert "測試旅館" in result["text"]


def test_destination_data_is_complete():
    supported = {"台北", "台中", "高雄", "東京", "京都", "大阪", "札幌", "首爾", "釜山", "新加坡"}
    frame = hotels()
    assert set(frame["destination"]) == supported
    assert frame.groupby("destination").size().eq(4).all()
    assert set(external.DESTINATION_COORDINATES) == supported


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


def test_unknown_costs_and_booking_group_price():
    unknown = budget_tool(3, 2, {"name": "真實旅館", "price": None},
                          [{"cost_twd_per_person": None}], 30000)
    assert unknown["total"] is None and unknown["remaining"] is None
    assert set(unknown["unknown_costs"]) == {"住宿", "景點／活動"}
    known = budget_tool(3, 4, {"name": "Booking 旅館", "price": 5000},
                        [{"cost_twd_per_person": 0}], 30000)
    assert known["components"]["住宿"] == 10000  # API 團體價不再重複乘房間數


def test_place_service_is_real_data_only(monkeypatch):
    monkeypatch.setattr(places, "_search", lambda query: [
        {"name": "真實旅館", "type": "hotel", "osm_type": "N", "osm_id": 1}
    ] if query.startswith("hotel") else [
        {"name": "真實博物館", "type": "museum", "osm_type": "W", "osm_id": 2,
         "extratags": {"fee": "no"}}])
    result = places._cached_places("台北", "文化", -1)
    assert result["hotels"][0]["price"] is None
    assert result["spots"][0]["cost_twd_per_person"] == 0
    assert result["spots"][0]["map_url"].endswith("/way/2")
