"""工具只做一件事，由單一 Agent 決定何時呼叫。"""
from rag.knowledge import retrieve
from services.analytics import demo_destination_records, recommend_hotels, spending
from services.booking import BookingServiceError, booking_search_url, search_accommodations, trip_dates
from services.external import currency, weather


def weather_tool(destination: str, date: str) -> dict:
    return weather(destination, date)


def hotel_tool(destination: str, max_nightly: float) -> list[dict]:
    """單一動作：推薦住宿；自訂目的地沒有內建資料時使用明確標示的教學樣本。"""
    recommended = recommend_hotels(destination, max_nightly)
    if recommended:
        return recommended
    demo = [item for item in demo_destination_records(destination, 40)
            if item["price"] <= max_nightly]
    return sorted(demo, key=lambda item: (-item["rating"], item["price"], item["distance"]))[:4]


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


def currency_tool(base: str, quote: str) -> dict:
    return currency(base, quote)


def budget_tool(days: int, people: int, hotel_price: float, spot_costs: list[float], budget: float) -> dict:
    return spending(days, people, hotel_price, spot_costs, budget)


def rag_tool(query: str, session_id: str | None = None) -> list[dict]:
    return retrieve(query, session_id)
