"""Google Places 解析、排名、多樣性與不儲存 Google 內容的離線測試。"""
from database import repository
from services import google_places, places
from fastapi.testclient import TestClient
from main import app


def _item(index: int, rating: float, count: int, category: str) -> dict:
    return {"id": str(index), "displayName": {"text": f"景點 {index}"},
            "rating": rating, "userRatingCount": count, "primaryType": category,
            "businessStatus": "OPERATIONAL", "googleMapsUri": f"https://maps.google.com/?cid={index}"}


def test_google_rating_and_diversity(monkeypatch):
    monkeypatch.setattr(google_places, "secret", lambda name: "test-key")
    rows = [_item(1, 5.0, 2, "museum"), _item(2, 4.7, 2000, "museum")]
    rows += [_item(i, 4.9, 300, "city_park") for i in range(3, 8)]
    rows += [_item(8, 4.8, 500, "historical_place")]
    monkeypatch.setattr(google_places, "_search", lambda query, key: rows)
    output = google_places.search_spots("台北", "文化")
    assert output[0]["name"] != "景點 1"  # 兩則評論的五星不應排首位
    assert sum(item["category"] == "自然" for item in output) == 2
    assert output[0]["rating_source"] == "Google Maps"
    assert output[0]["cost_twd_per_person"] is None


def test_google_request_uses_key_and_required_fields(monkeypatch):
    seen = {}
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"places": []}
    class Client:
        def __init__(self, timeout):
            assert timeout == 15
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, json, headers):
            seen.update(url=url, payload=json, headers=headers)
            return Response()
    monkeypatch.setattr(google_places.httpx, "Client", Client)
    assert google_places._search("attractions in 台北", "test-key") == []
    assert seen["headers"]["X-Goog-Api-Key"] == "test-key"
    assert "places.rating" in seen["headers"]["X-Goog-FieldMask"]
    assert seen["payload"]["maxResultCount"] == 20


def test_fallback_never_claims_google_rating(monkeypatch):
    monkeypatch.setattr(places, "_cached_places", lambda destination, preference, hour: {
        "area": destination, "capital_fallback": False, "hotels": [],
        "spots": [{"name": "公園", "rating": None}]})
    monkeypatch.setattr(places, "configured", lambda: False)
    result = places.places("台北", "自然")
    assert result["spot_source"] == "OpenStreetMap"
    assert result["spots"][0]["rating"] is None
    monkeypatch.setattr(places, "configured", lambda: True)
    monkeypatch.setattr(places, "search_spots", lambda destination, preference: [
        {"name": "博物館", "rating": 4.8, "rating_count": 400}])
    assert places.places("台北", "文化")["spot_source"] == "Google Maps"


def test_google_results_are_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(repository, "DB_PATH", tmp_path / "plans.db")
    repository.save_plan({"destination": "台北"}, {
        "spot_source": "Google Maps", "spots": [{"name": "Google 景點", "rating": 4.9}],
        "itinerary": [{"spot": "Google 景點"}]})
    saved = repository.recent_plans(1)[0]
    assert "Google 景點" not in str(saved)
    assert saved["result"]["spot_source"] == "Google Maps"


def test_google_spots_flow_through_plan_without_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(repository, "DB_PATH", tmp_path / "plans.db")
    monkeypatch.setattr(places, "_cached_places", lambda destination, preference, hour: {
        "area": destination, "capital_fallback": False,
        "hotels": [{"name": "旅館", "price": None}], "spots": []})
    monkeypatch.setattr(places, "configured", lambda: True)
    monkeypatch.setattr(places, "search_spots", lambda destination, preference: [{
        "name": "Google 測試博物館", "activity": "參觀展覽", "category": "文化",
        "rating": 4.7, "rating_count": 320, "rating_source": "Google Maps",
        "cost_twd_per_person": None, "fee_note": "待查",
        "map_url": "https://maps.google.com/?cid=1", "attributions": []}])
    response = TestClient(app).post("/api/plan", json={"destination": "台北",
        "start_date": "2026-10-01", "days": 2, "people": 1,
        "budget_twd": 10000, "preference": "文化"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["spot_source"] == "Google Maps"
    assert body["itinerary"][0]["rating"] == 4.7
    assert "Google 測試博物館" not in str(repository.recent_plans(1))


def test_taitung_is_disambiguated_from_tokyo_taito(monkeypatch):
    queries = []
    def fake_search(query):
        queries.append(query)
        return []
    monkeypatch.setattr(places, "_search", fake_search)
    result = places._cached_places("台東", "自然", -100)
    assert result["search_area"] == "Taitung City, Taiwan"
    assert result["area_note"]
    assert all("Taitung City, Taiwan" in query for query in queries)
    assert not any("parks in 台東" in query for query in queries)
