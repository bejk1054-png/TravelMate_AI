"""全球目的地解析：國名、城市＋國家、首都座標與法定貨幣。"""
from functools import lru_cache
import re

from babel import Locale
from babel.numbers import get_territory_currencies
import httpx

from utils.location import destination_candidates

CITY_ALIASES = {
    # Open-Meteo 的繁中別名並不完整，將常見台灣譯名轉成較穩定的國際名稱。
    "紐約": "New York City", "纽约": "New York City", "洛杉磯": "Los Angeles",
    "舊金山": "San Francisco", "倫敦": "London", "羅馬": "Rome", "柏林": "Berlin",
    "馬德里": "Madrid", "里斯本": "Lisbon", "阿姆斯特丹": "Amsterdam",
    "布魯塞爾": "Brussels", "維也納": "Vienna", "布拉格": "Prague", "雅典": "Athens",
    "開羅": "Cairo", "內羅畢": "Nairobi", "開普敦": "Cape Town",
    "約翰尼斯堡": "Johannesburg", "里約熱內盧": "Rio de Janeiro",
    "聖保羅": "Sao Paulo", "布宜諾斯艾利斯": "Buenos Aires",
    "墨西哥城": "Mexico City", "溫哥華": "Vancouver", "多倫多": "Toronto",
    "雪梨": "Sydney", "墨爾本": "Melbourne", "奧克蘭": "Auckland",
    "吉隆坡": "Kuala Lumpur", "雅加達": "Jakarta", "河內": "Hanoi",
    "胡志明市": "Ho Chi Minh City", "馬尼拉": "Manila", "新德里": "New Delhi",
    "孟買": "Mumbai", "杜拜": "Dubai", "迪拜": "Dubai",
}


class LocationServiceError(RuntimeError):
    """地名或國家資料服務無法完成查詢。"""


def _normalize(value: str) -> str:
    return re.sub(r"[\s,，、./_-]+", "", value).casefold()


@lru_cache(maxsize=1)
def _country_aliases() -> dict[str, str]:
    """以 CLDR 建立繁中、簡中與英文國名到 ISO2 的索引。"""
    aliases = {}
    for locale_name in ("zh_Hant", "zh_Hans", "en"):
        locale = Locale.parse(locale_name)
        for code, name in locale.territories.items():
            if len(code) == 2 and code.isalpha() and name:
                aliases[_normalize(str(name))] = code.upper()
    # 補上台灣常見簡稱與不同譯名。
    aliases.update({_normalize(name): code for name, code in {
        "南韓": "KR", "韓國": "KR", "北韓": "KP", "俄羅斯": "RU",
        "寮國": "LA", "老撾": "LA", "象牙海岸": "CI", "科特迪瓦": "CI",
        "捷克": "CZ", "台灣": "TW", "臺灣": "TW",
    }.items()})
    return aliases


def resolve_country_code(value: str) -> str | None:
    """接受繁中、簡中、英文國名或 ISO2 國碼。"""
    text = value.strip()
    if len(text) == 2 and text.isascii() and text.isalpha():
        return text.upper()
    return _country_aliases().get(_normalize(text))


def split_city_country(destination: str) -> tuple[str, str | None]:
    """從「城市 國家」或「城市, 國家」取出城市與 ISO2 國碼。"""
    text = destination.strip()
    if resolve_country_code(text):
        return "", resolve_country_code(text)
    parts = [item.strip() for item in re.split(r"[,，、/]+", text) if item.strip()]
    if len(parts) > 1:
        code = resolve_country_code(parts[-1])
        if code:
            return " ".join(parts[:-1]), code
    words = text.split()
    for start in range(1, len(words)):
        code = resolve_country_code(" ".join(words[start:]))
        if code:
            return " ".join(words[:start]), code
    return text, None


def city_search_name(city: str) -> str:
    return CITY_ALIASES.get(city.strip(), city.strip())


def territory_currency(country_code: str) -> str | None:
    currencies = get_territory_currencies(country_code.upper(), tender=True)
    return currencies[0] if currencies else None


def _get_json(url: str, params: dict) -> object:
    try:
        with httpx.Client(timeout=8, follow_redirects=False) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise LocationServiceError(f"地名服務暫時無法使用：{type(exc).__name__}") from exc


@lru_cache(maxsize=128)
def country_capital(country_code: str) -> dict:
    """透過世界銀行 Country API 取得首都與座標。"""
    data = _get_json(f"https://api.worldbank.org/v2/country/{country_code.lower()}",
                     {"format": "json"})
    try:
        record = data[1][0]
        return {"name": record["capitalCity"], "latitude": float(record["latitude"]),
                "longitude": float(record["longitude"]), "country_code": country_code.upper(),
                "fallback_to_capital": True}
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise LocationServiceError("此國家目前沒有可用的首都座標") from exc


def geocode_destination(destination: str) -> dict:
    """解析全球城市；僅輸入國家或城市查不到時，明確退回該國首都。"""
    city, country_code = split_city_country(destination)
    if not city and country_code:
        return country_capital(country_code)

    last_error = None
    for candidate in destination_candidates(city_search_name(city or destination)):
        try:
            params = {"name": candidate, "count": 10, "language": "zh", "format": "json"}
            if country_code:
                params["countryCode"] = country_code
            data = _get_json("https://geocoding-api.open-meteo.com/v1/search", params)
            results = data.get("results") or [] if isinstance(data, dict) else []
        except LocationServiceError as exc:
            last_error = exc
            continue
        if results:
            # 同名地點優先選人口較多者，避免「紐約」落到其他州的小聚落。
            item = max(results, key=lambda result: result.get("population") or 0)
            return {"name": item.get("name", city or destination),
                    "latitude": item["latitude"], "longitude": item["longitude"],
                    "country_code": (item.get("country_code") or country_code or "").upper(),
                    "fallback_to_capital": False}
    if country_code:
        return country_capital(country_code)
    if last_error is not None:
        raise last_error
    raise LocationServiceError(f"找不到目的地：{destination}；建議輸入「城市 國家」")


def destination_currency(destination: str) -> str:
    """由國名或地名解析當地現行法定貨幣。"""
    _, country_code = split_city_country(destination)
    if not country_code:
        country_code = geocode_destination(destination).get("country_code")
    currency_code = territory_currency(country_code) if country_code else None
    if not currency_code:
        raise LocationServiceError(f"找不到 {destination} 的法定幣別")
    return currency_code
