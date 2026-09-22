"""工具只做一件事，由單一 Agent 決定何時呼叫。"""
from rag.knowledge import retrieve
from services.places import places
from services.booking import BookingServiceError, booking_search_url, search_accommodations, trip_dates
from services.external import currency, destination_exchange, weather


def weather_tool(destination: str, date: str) -> dict:
    return weather(destination, date)


def hotel_tool(destination: str, preference: str = "", place_data: dict | None = None) -> list[dict]:
    """單一動作：從公開地圖取得真實住宿名稱，價格一律待查。"""
    return (place_data or places(destination, preference))["hotels"]


def spot_tool(destination: str, preference: str = "", place_data: dict | None = None) -> list[dict]:
    """單一動作：從公開地圖取得真實景點名稱與門票標記。"""
    return (place_data or places(destination, preference))["spots"]


def booking_tool(destination: str, start_date: str, days: int, people: int) -> dict:
    """單一動作：透過 Booking 官方 API 取得最多 40 筆房源。"""
    checkin, checkout = trip_dates(start_date, days)
    rooms = (people + 1) // 2
    try:
        return search_accommodations(destination, checkin, checkout, people, rooms, limit=40)
    except BookingServiceError as exc:
        return {"available": False, "hotels": [], "count": 0,
                "search_url": booking_search_url(destination, checkin, checkout, people, rooms),
                "source": "Booking.com 公開查價頁面", "message": str(exc)}


def currency_tool(destination_or_base: str, quote: str | None = None) -> dict:
    """單一動作：可依目的地自動判斷幣別，也保留直接輸入幣別的教學介面。"""
    if quote is not None:
        return currency(destination_or_base, quote)
    return destination_exchange(destination_or_base)


def budget_tool(days: int, people: int, hotel: dict | None,
                itinerary: list[dict], budget: float) -> dict:
    """已知金額與估算分開；缺住宿／門票時不宣稱完整總額。"""
    nights = max(days - 1, 1)
    rooms = (people + 1) // 2
    lodging = (float(hotel["price"]) * nights if hotel and hotel.get("price") is not None else None)
    # Booking 搜尋價格已依全團房數取得，不可再次乘房數。
    known_fees = sum(float(day["cost_twd_per_person"]) * people for day in itinerary
                     if day.get("cost_twd_per_person") is not None)
    unknown_fees = sum(day.get("cost_twd_per_person") is None for day in itinerary)
    meals, transport = 900 * days * people, 350 * days * people
    subtotal = meals + transport + known_fees + (lodging or 0)
    complete = lodging is not None and unknown_fees == 0
    return {"components": {"住宿": lodging, "景點已知費用": known_fees,
                            "餐食估算": meals, "市內交通估算": transport},
            "known_subtotal": subtotal, "total": subtotal if complete else None,
            "remaining": round(budget - subtotal, 2) if complete else None,
            "daily": round(subtotal / days, 2) if complete else None,
            "within_budget": subtotal <= budget if complete else None,
            "unknown_costs": [item for item, missing in (("住宿", lodging is None),
                               ("景點／活動", unknown_fees > 0)) if missing],
            "assumptions": f"新台幣；{days} 天按 {nights} 晚、{rooms} 間房；每人每日餐食估算 900 元、"
                           "市內交通估算 350 元；不含機票、跨城交通。未查得費用不當作 0 元。"}


def rag_tool(query: str, session_id: str | None = None) -> list[dict]:
    return retrieve(query, session_id)
