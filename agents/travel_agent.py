"""單一主 Agent：以明確規則選工具，保證無金鑰也能運作。"""
from datetime import date, timedelta

from services.analytics import spots
from services.llm import advice
from services.nlp import analyze_reviews
from tools.travel_tools import budget_tool, currency_tool, hotel_tool, rag_tool, weather_tool

CURRENCIES = {"東京": "JPY", "京都": "JPY", "台北": "TWD", "首爾": "KRW"}


def plan(request: dict) -> dict:
    destination = request["destination"]
    days, people, budget = request["days"], request["people"], request["budget_twd"]
    selected_spots = spots(destination, request["preference"])
    # 為餐食、交通與景點保留一半預算，按房間數分配住宿上限。
    max_nightly = budget * 0.5 / days / ((people + 1) // 2)
    hotels = hotel_tool(destination, max_nightly)
    if not hotels:
        hotels = hotel_tool(destination, float("inf"))
    chosen = hotels[0] if hotels else None
    itinerary = []
    start = date.fromisoformat(request["start_date"])
    for day in range(days):
        spot = selected_spots[day % len(selected_spots)] if selected_spots else None
        itinerary.append({"day": day + 1, "date": (start + timedelta(days=day)).isoformat(),
                          "spot": spot["name"] if spot else "自由探索",
                          "activity": spot["description"] if spot else "自行安排",
                          "cost_twd_per_person": spot["cost_twd"] if spot else 0})
    costs = [day["cost_twd_per_person"] for day in itinerary]
    spending = budget_tool(days, people, chosen["price"] if chosen else 0, costs, budget)
    notes = rag_tool(destination + " " + request["preference"])
    # 天氣與匯率為可選外部呼叫；失敗要明示，不影響核心規劃。
    external = {}
    if request.get("use_live_api", False):
        for name, call in {
            "weather": lambda: weather_tool(destination, request["start_date"]),
            "currency": lambda: currency_tool("TWD", CURRENCIES.get(destination, "TWD")),
        }.items():
            try:
                external[name] = call()
            except (RuntimeError, ValueError, KeyError) as exc:
                external[name] = {"available": False, "message": str(exc)}
    facts = {"destination": destination, "days": days, "preference": request["preference"],
             "spending": spending, "notes": notes}
    return {"destination": destination, "itinerary": itinerary, "hotels": hotels,
            "spots": selected_spots, "spending": spending, "reviews": analyze_reviews(destination),
            "rag_sources": notes, "external": external, "advice": advice(facts),
            "data_notice": "住宿、景點與評論為示範資料；價格均為新台幣估算，非即時房價或訂房服務。",
            "tool_trace": ["hotel_tool", "budget_tool", "rag_tool"] +
                          (["weather_tool", "currency_tool"] if request.get("use_live_api") else [])}
