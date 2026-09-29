"""以使用者觸發的 OSM 地點搜尋取得真實名稱；遵守快取與速率限制。"""
from functools import lru_cache
from threading import Lock
import time
from urllib.parse import urlencode

import httpx

from services.location import (LocationServiceError, city_search_name, country_capital,
                               split_city_country)
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
        try:
            with httpx.Client(timeout=12) as client:
                response = None
                for attempt in range(2):
                    delay = 1.1 - (time.monotonic() - _last_request)
                    if delay > 0:
                        time.sleep(delay)
                    _last_request = time.monotonic()
                    response = client.get(NOMINATIM_URL, params={
                        "q": query, "format": "jsonv2", "limit": 10, "extratags": 1},
                        headers={"User-Agent": USER_AGENT})
                    if response.status_code not in {429, 502, 503, 504} or attempt == 1:
                        break
                    # 免費服務限流時短暫退避；上限避免單一行程等待過久。
                    try:
                        retry_after = min(max(float(response.headers.get("Retry-After", 2)), 2), 5)
                    except (TypeError, ValueError):
                        retry_after = 2
                    time.sleep(retry_after)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise PlaceServiceError(f"OpenStreetMap 地點查詢暫時失敗：{type(exc).__name__}") from exc


def _link(item: dict) -> str:
    kind = {"N": "node", "W": "way", "R": "relation"}.get(item.get("osm_type"), "node")
    return f"https://www.openstreetmap.org/{kind}/{item['osm_id']}"


def _google_maps_link(name: str, destination: str) -> str:
    """Google Maps 網址不需 API 金鑰；只開啟官方頁面讓使用者自行核對評分。"""
    return "https://www.google.com/maps/search/?" + urlencode({
        "api": 1, "query": f"{name}, {destination}"
    })


def _recommendation_score(category: str, preference: str, position: int) -> int:
    """免費資料沒有評論星等，因此只顯示透明的 TravelMate 排序分數。"""
    preferred_by_word = {
        "文化": {"museum", "gallery", "monument", "memorial", "castle"},
        "自然": {"park", "viewpoint", "zoo"},
        "美食": {"restaurant", "marketplace"},
        "地標": {"attraction", "viewpoint", "monument", "memorial", "castle"},
    }
    preferred = set().union(*(
        categories for word, categories in preferred_by_word.items() if word in preference
    )) if preference else set()
    # 分數只反映偏好、資料完整度與搜尋順位，不冒稱群眾評分。
    return max(55, min(95, 70 + (15 if category in preferred else 0) - position))


def _spot_queries(search_area: str, preference: str) -> list[str]:
    """用明確類型搜尋，避免免費文字搜尋只回傳低品質的一般 attraction。"""
    terms = []
    if "自然" in preference or "動物" in preference:
        terms.extend(("zoos", "parks"))
    if "文化" in preference:
        terms.extend(("museums", "monuments"))
    if "美食" in preference:
        terms.append("markets")
    if "地標" in preference:
        terms.append("monuments")
    # 博物館通常有較完整的公開資料；一般景點只作最後補充。
    terms.extend(("museums", "attractions"))
    return [f"{term} in {search_area}" for term in dict.fromkeys(terms)]


def _spot_quality(item: dict) -> float:
    """以可核對的公開欄位排序，不把這個分數冒稱為使用者評分。"""
    tags = item.get("extratags") or {}
    category = str(item.get("type") or "")
    name = str(item.get("name") or "").strip()
    type_weight = {
        "museum": 25, "zoo": 24, "castle": 23, "monument": 22,
        "memorial": 21, "gallery": 20, "viewpoint": 18, "marketplace": 17,
        "park": 15, "restaurant": 12, "attraction": 5,
    }.get(category, 0)
    verifiable = (35 if tags.get("wikidata") or tags.get("wikipedia") else 0)
    verifiable += 12 if tags.get("website") else 0
    verifiable += 6 if tags.get("opening_hours") else 0
    # 常見誤標名稱只降權，不武斷刪除；資料不足時仍可顯示並要求使用者核對。
    suspicious = ("hotel", "hostel", "apartment", "residence", "heights", "person")
    penalty = 45 if any(word in name.casefold() for word in suspicious) else 0
    if category == "attraction" and not verifiable:
        penalty += 18
    importance = float(item.get("importance") or 0)
    return type_weight + verifiable + importance * 10 - penalty


@lru_cache(maxsize=64)
def _cached_places(destination: str, preference: str, hour: int) -> dict:
    city, country = split_city_country(destination)
    area, search_area, capital_fallback, area_note = destination, destination, False, None
    country_reference_kind = None
    alias = TAIWAN_AREAS.get(city) if country in (None, "TW") else None
    if alias:
        search_area, area = alias
        area_note = f"「{destination}」按{area}周邊搜尋；若要其他鄉鎮請輸入完整地名。"
    elif city and country:
        # 所有外部服務共用同一個正規化城市與 ISO 國碼，避免同名城市跨國或跨州。
        search_area = f"{city_search_name(city)}, {country}"
    elif not city and country:
        try:
            reference = country_capital(country)
            area = reference["name"] + ", " + destination
            # 對外部地名服務使用 ISO 國碼，比中文國名更穩定。
            search_area = reference["name"] + ", " + country
            country_reference_kind = reference.get("reference_kind", "capital")
            capital_fallback = country_reference_kind in {"capital", "representative_city"}
        except (LocationServiceError, KeyError) as exc:
            raise PlaceServiceError(str(exc)) from exc
    hotels, spots, service_warnings = [], [], []
    try:
        hotel_rows = _search(f"hotel in {search_area}")
    except PlaceServiceError as exc:
        hotel_rows = []
        service_warnings.append(str(exc))
    for item in hotel_rows:
        if item.get("type") not in {"hotel", "hostel", "guest_house", "motel"}:
            continue
        name = str(item.get("name") or "").strip()
        if not name or not item.get("osm_id"):
            continue
        hotels.append({"name": name, "destination": destination, "price": None,
                       "currency": None, "price_source": "房價待查；名稱來自 OpenStreetMap",
                       "booking_url": None, "map_url": _link(item), "rating": None,
                       "room_type": "待查", "room_size": None})
    candidates = []
    for query in _spot_queries(search_area, preference):
        try:
            candidates.extend(_search(query))
        except PlaceServiceError as exc:
            service_warnings.append(str(exc))
            continue
        # 已有足夠候選便停止額外查詢，降低免費服務負載與限流風險。
        if len(candidates) >= 15:
            break
    candidates.sort(key=_spot_quality, reverse=True)
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
                      "map_url": _link(item),
                      "google_maps_url": _google_maps_link(name, area),
                      "rating": None, "rating_count": None, "rating_source": None,
                      "recommendation_score": _recommendation_score(
                          category, preference, len(spots)
                      ),
                      "recommendation_basis": "偏好符合度、類型多樣性、公開資料完整度",
                      "latitude": item.get("lat"), "longitude": item.get("lon")})
    return {"hotels": hotels[:10], "spots": spots[:10], "area": area,
            "search_area": search_area, "area_note": area_note,
            "capital_fallback": capital_fallback,
            "country_reference_kind": country_reference_kind,
            "service_warnings": list(dict.fromkeys(service_warnings))}


def places(destination: str, preference: str = "") -> dict:
    destination, preference = destination.strip(), preference.strip()
    result = _cached_places(destination, preference, int(time.time() // 3600)).copy()
    result["spot_source"] = "OpenStreetMap"
    result["spot_message"] = ("未設定 Google Places API 金鑰；目前景點沒有 Google 評分。"
                              if result["spots"] else
                              "公開地點服務暫時沒有回傳景點；請稍後重試或輸入更完整的城市與國家。")
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
