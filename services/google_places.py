"""Google Places Text Search：即時取得評分，避免低評論數高分景點壟斷行程。"""
from math import isfinite

import httpx

from utils.config import secret

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ("places.id,places.displayName,places.rating,places.userRatingCount,"
              "places.googleMapsUri,places.primaryType,places.businessStatus,places.attributions")
QUERY_BY_PREFERENCE = {"文化": "museums and historic landmarks", "自然": "nature attractions",
                       "美食": "local food markets", "地標": "landmarks"}


class GooglePlacesError(RuntimeError):
    """Google Places 暫時無法回應；錯誤訊息不得包含金鑰。"""


def configured() -> bool:
    return bool(secret("GOOGLE_PLACES_API_KEY"))


def _search(query: str, key: str) -> list[dict]:
    payload = {"textQuery": query, "languageCode": "zh-TW", "maxResultCount": 20}
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(SEARCH_URL, json=payload, headers={
                "Content-Type": "application/json", "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": FIELD_MASK})
            response.raise_for_status()
            data = response.json()
        return data.get("places", [])
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        raise GooglePlacesError(f"Google Places 查詢失敗：{type(exc).__name__}") from exc


def _category(primary_type: str) -> str:
    value = primary_type or ""
    if "park" in value or value in {"hiking_area", "botanical_garden", "nature_preserve"}:
        return "自然"
    if any(word in value for word in ("museum", "gallery", "historic", "castle", "temple")):
        return "文化"
    if any(word in value for word in ("restaurant", "market", "food")):
        return "美食"
    return "地標"


def _activity(category: str) -> str:
    return {"自然": "步道／自然景觀探索", "文化": "參觀展覽或歷史景點",
            "美食": "品嚐在地餐點", "地標": "參觀與拍照"}[category]


def search_spots(destination: str, preference: str) -> list[dict]:
    """每次請求即時查詢、不快取；分數兼顧星等與評論數，並控制公園比例。"""
    key = secret("GOOGLE_PLACES_API_KEY")
    if not key:
        return []
    queries = [f"tourist attractions in {destination}"]
    second = QUERY_BY_PREFERENCE.get(preference)
    if second:
        queries.append(f"{second} in {destination}")
    candidates = {}
    for query in queries:
        for item in _search(query, key):
            place_id = item.get("id")
            if place_id and item.get("businessStatus", "OPERATIONAL") == "OPERATIONAL":
                candidates[place_id] = item
    ranked = []
    for item in candidates.values():
        name = (item.get("displayName") or {}).get("text", "").strip()
        try:
            rating = float(item["rating"])
            count = int(item.get("userRatingCount", 0))
        except (KeyError, TypeError, ValueError):
            continue
        if not name or not isfinite(rating) or not 0 <= rating <= 5 or count < 1:
            continue
        category = _category(item.get("primaryType", ""))
        # Bayesian 平滑：少量評論的 5 星不會壓過大量好評的景點。
        score = (count * rating + 100 * 4.0) / (count + 100)
        if category == preference:
            score += 0.08
        ranked.append((score, count, item, category, rating, name))
    ranked.sort(key=lambda row: (-row[0], -row[1], row[5]))
    selected, per_category = [], {}
    for _score, count, item, category, rating, name in ranked:
        limit = 2 if category == "自然" else 4
        if per_category.get(category, 0) >= limit:
            continue
        per_category[category] = per_category.get(category, 0) + 1
        selected.append({"name": name, "activity": _activity(category), "category": category,
                         "rating": rating, "rating_count": count,
                         "rating_source": "Google Maps", "cost_twd_per_person": None,
                         "fee_note": "門票／活動費待查", "map_url": item.get("googleMapsUri"),
                         "attributions": item.get("attributions") or []})
        if len(selected) >= 10:
            break
    return selected
