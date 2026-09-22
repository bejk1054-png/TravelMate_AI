"""單一主 Agent：選擇工具並整合具來源的行程，不把未知價格冒充為零。"""
from datetime import date, timedelta

from services.llm import advice
from services.places import PlaceServiceError, places
from tools.travel_tools import (booking_tool, budget_tool, currency_tool, hotel_tool,
                                rag_tool, spot_tool, weather_tool)


def plan(request: dict) -> dict:
    destination = request["destination"]
    days, people, budget = request["days"], request["people"], request["budget_twd"]
    booking = booking_tool(destination, request["start_date"], days, people)
    warnings = []
    try:
        place_data = places(destination, request["preference"])
        selected_spots = spot_tool(destination, request["preference"], place_data)
        map_hotels = hotel_tool(destination, request["preference"], place_data)
    except PlaceServiceError as exc:
        selected_spots, map_hotels = [], []
        place_data = {"area": destination, "capital_fallback": False,
                      "spot_source": "unavailable", "spot_message": str(exc)}
        warnings.append(str(exc))
    if place_data["capital_fallback"]:
        warnings.append(f"「{destination}」是國家；以下地點以首都 {place_data['area']} 周邊代表，並非全國行程。")
    # Booking 查得價格時才可列入預算；OSM 只提供真實名稱。
    priced = [item for item in booking["hotels"] if item.get("price") is not None
              and item.get("currency") == "TWD"]
    hotels = sorted(priced, key=lambda item: item["price"])[:5] if priced else map_hotels[:5]
    chosen = hotels[0] if hotels else None
    itinerary = []
    start = date.fromisoformat(request["start_date"])
    for day in range(days):
        # 不重複使用同一景點；資料不足時保留空白並明示待規劃。
        spot = selected_spots[day] if day < len(selected_spots) else None
        itinerary.append({"day": day + 1, "date": (start + timedelta(days=day)).isoformat(),
                          "spot": spot["name"] if spot else "待安排",
                          "activity": spot["activity"] if spot else "當地景點資料不足，請自行查詢",
                          "cost_twd_per_person": spot["cost_twd_per_person"] if spot else None,
                          "fee_note": spot["fee_note"] if spot else "費用待查",
                          "map_url": spot["map_url"] if spot else None,
                          "rating": spot.get("rating") if spot else None,
                          "rating_count": spot.get("rating_count") if spot else None})
    spending = budget_tool(days, people, chosen, itinerary, budget)
    notes = rag_tool(destination + " " + request["preference"], request.get("session_id"))
    external = {}
    if request.get("use_live_api", False):
        for name, call in {"weather": lambda: weather_tool(destination, request["start_date"]),
                           "currency": lambda: currency_tool(destination)}.items():
            try:
                external[name] = call()
            except (RuntimeError, ValueError, KeyError) as exc:
                external[name] = {"available": False, "message": str(exc)}
    # Google 地點內容只用於即時顯示；不送入第三方 LLM。
    facts = {"destination": destination, "days": days, "preference": request["preference"],
             "spending": spending, "hotel": chosen,
             "spots": [] if place_data["spot_source"] == "Google Maps" else itinerary,
             "external": external, "notes": notes, "booking_available": bool(priced)}
    notice = ("住宿名稱來自 Booking.com；價格為查詢日期的 API 回傳值，稅費、房型與可訂性以訂房頁為準。"
              if priced else "住宿名稱來自 OpenStreetMap；沒有 Booking 官方憑證或查無房價，住宿費用待查。")
    notice += (" 景點與評分來自 Google Maps；門票／活動費待查，開放時間請向景點確認。"
               if place_data["spot_source"] == "Google Maps" else
               " 景點名稱來自 OpenStreetMap，無 Google 評分；門票與活動費未標示者待查。")
    return {"destination": destination, "area": place_data["area"], "itinerary": itinerary,
            "hotels": hotels, "spots": selected_spots[:10], "spending": spending,
            "spot_source": place_data["spot_source"], "spot_message": place_data["spot_message"],
            "rag_sources": notes, "external": external,
            "advice": advice(facts), "booking": booking,
            "booking_search_url": booking["search_url"], "data_notice": notice,
            "warnings": warnings,
            "tool_trace": ["booking_tool", "spot_tool", "hotel_tool", "budget_tool", "rag_tool"] +
                          (["weather_tool", "currency_tool"] if request.get("use_live_api") else [])}
