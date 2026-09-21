"""Booking.com Demand API 串接。沒有官方憑證時只產生安全的查價連結。"""
from datetime import date, timedelta
from math import asin, cos, radians, sin, sqrt
from urllib.parse import urlencode

import httpx

from utils.config import secret


class BookingServiceError(RuntimeError):
    """Booking 或地名服務無法回應時的可預期錯誤。"""


def booking_search_url(destination: str, checkin: str, checkout: str,
                       adults: int, rooms: int) -> str:
    """建立 Booking.com 公開查價頁面，不夾帶任何秘密。"""
    query = urlencode({
        "ss": destination.strip(), "checkin": checkin, "checkout": checkout,
        "group_adults": max(int(adults), 1), "no_rooms": max(int(rooms), 1),
        "selected_currency": "TWD",
    })
    return f"https://www.booking.com/searchresults.zh-tw.html?{query}"


def trip_dates(start_date: str, days: int) -> tuple[str, str]:
    checkin = date.fromisoformat(start_date)
    checkout = checkin + timedelta(days=max(int(days) - 1, 1))
    return checkin.isoformat(), checkout.isoformat()


def _credentials() -> tuple[str, str]:
    return secret("BOOKING_API_KEY"), secret("BOOKING_AFFILIATE_ID")


def _post(path: str, payload: dict) -> dict:
    api_key, affiliate_id = _credentials()
    if not api_key or not affiliate_id:
        raise BookingServiceError("Booking Demand API 尚未設定 API Key 與 Affiliate ID")
    base = secret("BOOKING_API_BASE", "https://demandapi.booking.com/3.2").rstrip("/")
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            response = client.post(f"{base}/{path.lstrip('/')}", json=payload, headers={
                "Authorization": f"Bearer {api_key}",
                "X-Affiliate-Id": affiliate_id,
                "Content-Type": "application/json",
            })
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise BookingServiceError(f"Booking Demand API 暫時無法使用：{type(exc).__name__}") from exc


def _geocode(destination: str) -> dict:
    """以免金鑰地名服務取得座標，再交給 Booking 進行周邊搜尋。"""
    try:
        with httpx.Client(timeout=8, follow_redirects=False) as client:
            response = client.get("https://geocoding-api.open-meteo.com/v1/search", params={
                "name": destination, "count": 1, "language": "zh", "format": "json",
            })
            response.raise_for_status()
            results = response.json().get("results") or []
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise BookingServiceError(f"目的地解析失敗：{type(exc).__name__}") from exc
    if not results:
        raise BookingServiceError("找不到該目的地，請輸入城市加國家，例如：巴黎 法國")
    return results[0]


def _name(value, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("zh-tw", "zh", "fallback", "en-gb"):
            if value.get(key):
                return str(value[key])
        for item in value.values():
            if item:
                return str(item)
    return fallback


def _number(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        # 同時相容 Demand API 3.1 與 3.2 的價格結構。
        for key in ("value", "amount", "display", "book", "booker", "accommodation"):
            converted = _number(value.get(key))
            if converted is not None:
                return converted
    return None


def _currency(value) -> str:
    """3.2 回傳 booker/accommodation 雙幣別；畫面優先使用查價者幣別。"""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        return str(value.get("booker") or value.get("accommodation") or "TWD")
    return "TWD"


def _distance_km(origin: dict, location: dict) -> float | None:
    try:
        lat1, lon1 = radians(float(origin["latitude"])), radians(float(origin["longitude"]))
        lat2 = radians(float(location.get("latitude")))
        lon2 = radians(float(location.get("longitude")))
    except (KeyError, TypeError, ValueError):
        return None
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return round(6371 * 2 * asin(sqrt(value)), 2)


def search_accommodations(destination: str, checkin: str, checkout: str,
                          adults: int, rooms: int, limit: int = 40) -> dict:
    """搜尋最多 40 筆 Booking 房源；價格以 API 回傳幣別與入住期間為準。"""
    limit = min(max(int(limit), 10), 40)
    rooms = max(int(rooms), 1)
    url = booking_search_url(destination, checkin, checkout, adults, rooms)
    api_key, affiliate_id = _credentials()
    if not api_key or not affiliate_id:
        return {"available": False, "hotels": [], "count": 0, "search_url": url,
                "source": "Booking.com 公開查價頁面",
                "message": "尚未設定 Booking Demand API 憑證；請點查價連結在 Booking.com 確認即時價格。"}

    point = _geocode(destination)
    payload = {
        "booker": {"country": "tw", "platform": "desktop"},
        "checkin": checkin, "checkout": checkout, "currency": "TWD",
        "coordinates": {"latitude": point["latitude"], "longitude": point["longitude"], "radius": 20},
        "guests": {"number_of_adults": max(int(adults), 1), "number_of_rooms": rooms},
        "rows": limit,
    }
    found = _post("accommodations/search", payload).get("data") or []
    ids = [item.get("id") for item in found if item.get("id") is not None]
    details = {}
    if ids:
        try:
            detail_data = _post("accommodations/details", {
                "accommodations": ids, "languages": ["zh-tw", "en-gb"]
            }).get("data") or []
            details = {str(item.get("id")): item for item in detail_data}
        except BookingServiceError:
            # 詳細資料失敗時仍保留搜尋端點的價格與訂房連結。
            details = {}

    nights = max((date.fromisoformat(checkout) - date.fromisoformat(checkin)).days, 1)
    hotels = []
    for item in found[:limit]:
        detail = details.get(str(item.get("id")), {})
        price = item.get("price") or {}
        total = _number(price.get("total")) if isinstance(price, dict) else _number(price)
        if total is None:
            total = _number(price.get("display")) if isinstance(price, dict) else _number(price)
        rating = _number(detail.get("rating")) or _number(item.get("rating"))
        location = detail.get("location") or item.get("location") or {}
        booking_url = item.get("url") or item.get("deep_link_url") or url
        hotels.append({
            "booking_id": item.get("id"),
            "name": _name(detail.get("name") or item.get("name"), f"Booking 住宿 {item.get('id', '')}"),
            "destination": destination, "room_type": "Booking 可訂房型",
            "price": round(total / nights, 2) if total is not None else None,
            "price_total": round(total, 2) if total is not None else None,
            "currency": _currency(item.get("currency") or
                                  (price.get("currency") if isinstance(price, dict) else None)),
            "rating": round(rating, 1) if rating is not None else None,
            "distance": _distance_km(point, location), "room_size": None,
            "room_size_ping": None, "booking_url": booking_url,
            "price_source": "Booking.com Demand API",
        })
    return {"available": True, "hotels": hotels, "count": len(hotels), "search_url": url,
            "source": "Booking.com Demand API", "message": f"已取得 {len(hotels)} 筆 Booking 即時房源。"}
