"""單一主 Agent：以明確規則選工具，保證無金鑰也能運作。"""
from datetime import date, timedelta

from services.analytics import spots
from services.llm import advice
from services.nlp import analyze_reviews
from tools.travel_tools import booking_tool, budget_tool, currency_tool, hotel_tool, rag_tool, weather_tool

def plan(request: dict) -> dict:
    destination = request["destination"]
    days, people, budget = request["days"], request["people"], request["budget_twd"]
    selected_spots = spots(destination, request["preference"])
    booking = booking_tool(destination, request["start_date"], days, people)
    # 為餐食、交通與景點保留一半預算，按房間數分配住宿上限。
    nights = max(days - 1, 1)
    max_nightly = budget * 0.5 / nights / ((people + 1) // 2)
    booking_hotels = [item for item in booking["hotels"] if item.get("price") is not None]
    hotels = [item for item in booking_hotels if item["price"] <= max_nightly][:4]
    if booking_hotels and not hotels:
        hotels = sorted(booking_hotels, key=lambda item: item["price"])[:4]
    if not hotels:
        hotels = hotel_tool(destination, max_nightly)
    if not hotels:
        # 預算內沒有資料時改以最低價格優先，避免備援反而選到最昂貴住宿。
        hotels = sorted(hotel_tool(destination, float("inf")), key=lambda item: (item["price"], -item["rating"]))
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
    notes = rag_tool(destination + " " + request["preference"], request.get("session_id"))
    # 天氣與匯率為可選外部呼叫；失敗要明示，不影響核心規劃。
    external = {}
    if request.get("use_live_api", False):
        for name, call in {
            "weather": lambda: weather_tool(destination, request["start_date"]),
            "currency": lambda: currency_tool(destination),
        }.items():
            try:
                external[name] = call()
            except (RuntimeError, ValueError, KeyError) as exc:
                external[name] = {"available": False, "message": str(exc)}
    reviews = analyze_reviews(destination)
    facts = {"destination": destination, "days": days, "preference": request["preference"],
             "spending": spending, "hotel": chosen, "external": external, "notes": notes,
             "booking_available": bool(booking["available"] and booking_hotels)}
    notice = ("住宿價格來自 Booking.com Demand API；實際總額、稅費與可訂性以 Booking 確認頁為準。"
              if booking["available"] and booking_hotels else
              "Booking API 憑證尚未設定；住宿與景點為示範資料，請使用 Booking 連結查即時價格。")
    return {"destination": destination, "itinerary": itinerary, "hotels": hotels,
            "spots": selected_spots, "spending": spending, "reviews": reviews,
            "rag_sources": notes, "external": external, "advice": advice(facts),
            "booking": booking, "booking_search_url": booking["search_url"], "data_notice": notice,
            "tool_trace": ["booking_tool", "hotel_tool", "budget_tool", "rag_tool"] +
                          (["weather_tool", "currency_tool"] if request.get("use_live_api") else [])}
