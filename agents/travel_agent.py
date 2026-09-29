"""單一主 Agent：選擇工具並整合具來源的行程，不把未知價格冒充為零。"""
from datetime import date, timedelta
from math import asin, ceil, cos, radians, sin, sqrt

from services.llm import advice
from services.places import PlaceServiceError, places
from tools.travel_tools import (booking_tool, budget_tool, currency_tool, hotel_tool,
                                rag_tool, spot_tool, weather_tool)


TIME_SLOTS = ("09:00", "13:30", "17:00")


def _coordinates(spot: dict) -> tuple[float, float] | None:
    try:
        return float(spot["latitude"]), float(spot["longitude"])
    except (KeyError, TypeError, ValueError):
        return None


def _distance_km(left: dict, right: dict) -> float | None:
    """使用公開座標估算兩景點直線距離；不冒充即時道路導航。"""
    a, b = _coordinates(left), _coordinates(right)
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    value = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return round(6371 * 2 * asin(sqrt(value)), 1)


def _nearby_order(spots: list[dict]) -> list[dict]:
    """以最近鄰近似排列；缺座標時保持原本推薦順位。"""
    if len(spots) < 2 or not _coordinates(spots[0]):
        return spots
    remaining, ordered = list(spots[1:]), [spots[0]]
    while remaining:
        current = ordered[-1]
        next_index = min(range(len(remaining)), key=lambda index:
                         _distance_km(current, remaining[index])
                         if _distance_km(current, remaining[index]) is not None else 1_000_000 + index)
        ordered.append(remaining.pop(next_index))
    return ordered


def _build_itinerary(spots: list[dict], start: date, days: int) -> list[dict]:
    """每天最多三個真實景點；資料不足時明確留白，不重複或捏造地點。"""
    ordered = _nearby_order(spots)
    per_day = min(3, max(1, ceil(len(ordered) / days))) if ordered else 1
    rows, cursor = [], 0
    for day in range(days):
        daily = ordered[cursor:cursor + per_day]
        cursor += len(daily)
        if not daily:
            daily = [None]
        previous = None
        for slot, spot in zip(TIME_SLOTS, daily):
            distance = _distance_km(previous, spot) if previous and spot else None
            travel_minutes = max(15, round(distance / 25 * 60)) if distance is not None else None
            rows.append({
                "day": day + 1, "date": (start + timedelta(days=day)).isoformat(),
                "time": slot, "spot": spot["name"] if spot else "待安排",
                "activity": spot["activity"] if spot else "目前真實景點資料不足，請調整目的地或偏好",
                "category": spot.get("category") if spot else None,
                "cost_twd_per_person": spot["cost_twd_per_person"] if spot else None,
                "fee_note": spot["fee_note"] if spot else "費用待查",
                "map_url": spot["map_url"] if spot else None,
                "google_maps_url": spot.get("google_maps_url") if spot else None,
                "rating": spot.get("rating") if spot else None,
                "rating_count": spot.get("rating_count") if spot else None,
                "recommendation_score": spot.get("recommendation_score") if spot else None,
                "travel_distance_km": distance, "travel_minutes_estimate": travel_minutes,
                "travel_note": ("景點間直線距離推估，請以 Google Maps 即時路線為準"
                                if distance is not None else "首站或缺少座標，未估算移動時間"),
            })
            previous = spot
    return rows


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
    if place_data.get("area_note"):
        warnings.append(place_data["area_note"])
    # Booking 查得價格時才可列入預算；OSM 只提供真實名稱。
    priced = [item for item in booking["hotels"] if item.get("price") is not None
              and item.get("currency") == "TWD"]
    hotels = sorted(priced, key=lambda item: item["price"])[:5] if priced else map_hotels[:5]
    chosen = hotels[0] if hotels else None
    start = date.fromisoformat(request["start_date"])
    itinerary = _build_itinerary(selected_spots, start, days)
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
