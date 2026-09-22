"""以使用者觸發的 OSM 地點搜尋取得真實名稱；遵守快取與速率限制。"""
from functools import lru_cache
from threading import Lock
import time

import httpx

from services.location import LocationServiceError, country_capital, split_city_country

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "TravelMateAI/1.0 (travel planning; https://github.com/bejk1054-png/TravelMate_AI)"
_rate_lock = Lock()
_last_request = 0.0


class PlaceServiceError(RuntimeError):
    """公開地點服務暫時無法使用。"""


def _search(query: str) -> list[dict]:
    """同一程序最多每秒一次，結果由上層依目的地快取一小時。"""
    global _last_request
    with _rate_lock:
        delay = 1.1 - (time.monotonic() - _last_request)
        if delay > 0:
            time.sleep(delay)
        _last_request = time.monotonic()
        try:
            with httpx.Client(timeout=12) as client:
                response = client.get(NOMINATIM_URL, params={
                    "q": query, "format": "jsonv2", "limit": 10, "extratags": 1},
                    headers={"User-Agent": USER_AGENT})
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise PlaceServiceError(f"OpenStreetMap 地點查詢暫時失敗：{type(exc).__name__}") from exc


def _link(item: dict) -> str:
    kind = {"N": "node", "W": "way", "R": "relation"}.get(item.get("osm_type"), "node")
    return f"https://www.openstreetmap.org/{kind}/{item['osm_id']}"


@lru_cache(maxsize=64)
def _cached_places(destination: str, preference: str, hour: int) -> dict:
    city, country = split_city_country(destination)
    area, capital_fallback = destination, False
    if not city and country:
        try:
            area = country_capital(country)["name"] + ", " + destination
            capital_fallback = True
        except (LocationServiceError, KeyError) as exc:
            raise PlaceServiceError(str(exc)) from exc
    hotels, spots = [], []
    for item in _search(f"hotel in {area}"):
        if item.get("type") not in {"hotel", "hostel", "guest_house", "motel"}:
            continue
        name = str(item.get("name") or "").strip()
        if not name or not item.get("osm_id"):
            continue
        hotels.append({"name": name, "destination": destination, "price": None,
                       "currency": None, "price_source": "房價待查；名稱來自 OpenStreetMap",
                       "booking_url": None, "map_url": _link(item), "rating": None,
                       "room_type": "待查", "room_size": None})
    search_term = {"文化": "museums", "自然": "parks", "美食": "restaurants",
                   "地標": "attractions"}.get(preference, "attractions")
    for item in _search(f"{search_term} in {area}"):
        if item.get("type") not in {"attraction", "museum", "gallery", "viewpoint",
                                     "monument", "park", "memorial", "castle", "zoo",
                                     "restaurant", "marketplace"}:
            continue
        name = str(item.get("name") or "").strip()
        if not name or not item.get("osm_id"):
            continue
        tags = item.get("extratags") or {}
        category = item.get("type")
        activity = {"museum": "參觀展覽", "gallery": "參觀藝廊", "viewpoint": "觀景",
                    "park": "公園散步", "monument": "參觀紀念地標", "castle": "參觀古蹟",
                    "zoo": "參觀動物園", "restaurant": "品嚐餐點",
                    "marketplace": "逛市場"}.get(category, "參觀景點")
        free = tags.get("fee") == "no"
        spots.append({"name": name, "activity": activity, "category": category,
                      "cost_twd_per_person": 0 if free else None,
                      "fee_note": "OSM 標示免門票；現場確認" if free else "門票／活動費待查",
                      "map_url": _link(item)})
    return {"hotels": hotels[:10], "spots": spots[:10], "area": area,
            "capital_fallback": capital_fallback}


def places(destination: str, preference: str = "") -> dict:
    return _cached_places(destination.strip(), preference.strip(), int(time.time() // 3600))
