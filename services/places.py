"""以使用者觸發的 OSM 地點搜尋取得真實名稱；遵守快取與速率限制。"""
from functools import lru_cache
from threading import Lock
import time

import httpx

from services.location import LocationServiceError, country_capital, split_city_country
from services.google_places import GooglePlacesError, configured, search_spots

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "TravelMateAI/1.0 (travel planning; https://github.com/bejk1054-png/TravelMate_AI)"
TAIWAN_AREAS = {
    "台東": ("Taitung City, Taiwan", "台東市（台灣）"),
    "臺東": ("Taitung City, Taiwan", "臺東市（台灣）"),
    "台東市": ("Taitung City, Taiwan", "台東市（台灣）"),
    "臺東市": ("Taitung City, Taiwan", "臺東市（台灣）"),
    "台北": ("Taipei, Taiwan", "台北市（台灣）"),
    "臺北": ("Taipei, Taiwan", "臺北市（台灣）"),
    "台中": ("Taichung, Taiwan", "台中市（台灣）"),
    "臺中": ("Taichung, Taiwan", "臺中市（台灣）"),
    "台南": ("Tainan, Taiwan", "台南市（台灣）"),
    "臺南": ("Tainan, Taiwan", "臺南市（台灣）"),
    "高雄": ("Kaohsiung, Taiwan", "高雄市（台灣）"),
    "花蓮": ("Hualien, Taiwan", "花蓮市（台灣）"),
    "宜蘭": ("Yilan, Taiwan", "宜蘭市（台灣）"),
}
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
    area, search_area, capital_fallback, area_note = destination, destination, False, None
    alias = TAIWAN_AREAS.get(city) if country in (None, "TW") else None
    if alias:
        search_area, area = alias
        area_note = f"「{destination}」按{area}周邊搜尋；若要其他鄉鎮請輸入完整地名。"
    elif not city and country:
        try:
            area = country_capital(country)["name"] + ", " + destination
            search_area = area
            capital_fallback = True
        except (LocationServiceError, KeyError) as exc:
            raise PlaceServiceError(str(exc)) from exc
    hotels, spots = [], []
    for item in _search(f"hotel in {search_area}"):
        if item.get("type") not in {"hotel", "hostel", "guest_house", "motel"}:
            continue
        name = str(item.get("name") or "").strip()
        if not name or not item.get("osm_id"):
            continue
        hotels.append({"name": name, "destination": destination, "price": None,
                       "currency": None, "price_source": "房價待查；名稱來自 OpenStreetMap",
                       "booking_url": None, "map_url": _link(item), "rating": None,
                       "room_type": "待查", "room_size": None})
    search_term = {"文化": "museums", "自然": "parks", "美食": "markets",
                   "地標": "landmarks"}.get(preference)
    queries = []
    if search_term:
        queries.append(f"{search_term} in {search_area}")
    queries.append(f"attractions in {search_area}")
    candidates = []
    for query in queries:
        candidates.extend(_search(query))
    category_counts, seen = {}, set()
    for item in candidates:
        if item.get("type") not in {"attraction", "museum", "gallery", "viewpoint",
                                     "monument", "park", "memorial", "castle", "zoo",
                                     "restaurant", "marketplace"}:
            continue
        name = str(item.get("name") or "").strip()
        if not name or not item.get("osm_id") or item["osm_id"] in seen:
            continue
        seen.add(item["osm_id"])
        tags = item.get("extratags") or {}
        category = item.get("type")
        if category_counts.get(category, 0) >= (2 if category == "park" else 4):
            continue
        category_counts[category] = category_counts.get(category, 0) + 1
        activity = {"museum": "參觀展覽", "gallery": "參觀藝廊", "viewpoint": "觀景",
                    "park": "公園散步", "monument": "參觀紀念地標", "castle": "參觀古蹟",
                    "zoo": "參觀動物園", "restaurant": "品嚐餐點",
                    "marketplace": "逛市場"}.get(category, "參觀景點")
        free = tags.get("fee") == "no"
        spots.append({"name": name, "activity": activity, "category": category,
                      "cost_twd_per_person": 0 if free else None,
                      "fee_note": "OSM 標示免門票；現場確認" if free else "門票／活動費待查",
                      "map_url": _link(item), "rating": None, "rating_count": None,
                      "rating_source": None})
    return {"hotels": hotels[:10], "spots": spots[:10], "area": area,
            "search_area": search_area, "area_note": area_note,
            "capital_fallback": capital_fallback}


def places(destination: str, preference: str = "") -> dict:
    destination, preference = destination.strip(), preference.strip()
    result = _cached_places(destination, preference, int(time.time() // 3600)).copy()
    result["spot_source"] = "OpenStreetMap"
    result["spot_message"] = "未設定 Google Places API 金鑰；目前景點沒有 Google 評分。"
    if configured():
        try:
            google_spots = search_spots(result.get("search_area", result["area"]), preference)
            if google_spots:
                result["spots"] = google_spots
                result["spot_source"] = "Google Maps"
                result["spot_message"] = "依 Google Maps 星等與評論數排序；自然／公園類最多兩筆。"
            else:
                result["spot_message"] = "Google 查無有評分的景點；改用無 Google 評分的 OpenStreetMap 地點。"
        except GooglePlacesError as exc:
            result["spot_message"] = f"{exc}；改用無 Google 評分的 OpenStreetMap 地點。"
    return result
