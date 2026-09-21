"""離線煙霧測試；不依賴即時網路或 LLM 金鑰。"""
from fastapi.testclient import TestClient
from uuid import uuid4

from main import app
from rag.knowledge import chunks, extract, session_knowledge
from services.analytics import hotels, summary

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


def test_analytics_prediction_and_validation():
    assert len(hotels()) >= 12
    assert summary()["count"] >= 12
    prediction = client.post("/api/predict", json={"rating": 4.2, "distance": 1.0,
        "room_size": 25, "stars": 3, "season": 2})
    assert prediction.status_code == 200, prediction.text
    assert prediction.json()["predicted_price_twd"] > 0
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
