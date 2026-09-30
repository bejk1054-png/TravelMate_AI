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
    "巴黎": "Paris", "東京": "Tokyo", "东京": "Tokyo", "首爾": "Seoul", "首尔": "Seoul",
    "大阪": "Osaka", "京都": "Kyoto", "札幌": "Sapporo", "釜山": "Busan",
    "舊金山": "San Francisco", "倫敦": "London", "羅馬": "Rome", "柏林": "Berlin",
    "馬德里": "Madrid", "里斯本": "Lisbon", "阿姆斯特丹": "Amsterdam",
    "布魯塞爾": "Brussels", "維也納": "Vienna", "布拉格": "Prague", "雅典": "Athens",
    "開羅": "Cairo", "內羅畢": "Nairobi", "開普敦": "Cape Town",
    "台東": "Taitung", "臺東": "Taitung", "台東市": "Taitung", "臺東市": "Taitung",
    "約翰尼斯堡": "Johannesburg", "里約熱內盧": "Rio de Janeiro",
    "聖保羅": "Sao Paulo", "布宜諾斯艾利斯": "Buenos Aires",
    "墨西哥城": "Mexico City", "溫哥華": "Vancouver", "多倫多": "Toronto",
    "雪梨": "Sydney", "墨爾本": "Melbourne", "奧克蘭": "Auckland",
    "吉隆坡": "Kuala Lumpur", "雅加達": "Jakarta", "河內": "Hanoi",
    "胡志明市": "Ho Chi Minh City", "馬尼拉": "Manila", "新德里": "New Delhi",
    "孟買": "Mumbai", "杜拜": "Dubai", "迪拜": "Dubai",
    "庫斯科": "Cusco", "庫司科": "Cusco", "斯庫科": "Cusco",
    # Open-Meteo 搜尋 New York 會誤中 York, Nebraska，必須明確指定 City。
    "New York": "New York City", "Washington DC": "Washington D.C.",
}

# 只收錄能明確判斷的常見輸入錯置；校正後仍會在畫面顯示提示，避免靜默猜測。
DESTINATION_CORRECTIONS = {
    "斯庫科": "Cusco, PE",
}

# 世界銀行沒有完整收錄下列常見目的地；使用固定且可核對的代表城市座標。
# PS 採行政中心 Ramallah，避免把具爭議的政治主張寫成產品事實。
COUNTRY_REFERENCE_OVERRIDES = {
    "TW": {"name": "Taipei", "latitude": 25.0330, "longitude": 121.5654},
    "IL": {"name": "Jerusalem", "latitude": 31.7780, "longitude": 35.2350},
    "PS": {"name": "Ramallah", "latitude": 31.9038, "longitude": 35.2034},
    "VA": {"name": "Vatican City", "latitude": 41.9027, "longitude": 12.4534},
    "XK": {"name": "Pristina", "latitude": 42.6629, "longitude": 21.1655},
    "HK": {"name": "Hong Kong", "latitude": 22.3193, "longitude": 114.1694},
    "MO": {"name": "Macau", "latitude": 22.1987, "longitude": 113.5439},
}

NON_DESTINATION_CODES = {"EU", "EZ", "QO", "UN", "XA", "XB", "ZZ"}


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
        "捷克": "CZ", "台灣": "TW", "臺灣": "TW", "香港": "HK", "澳門": "MO",
        "巴勒斯坦": "PS", "梵蒂岡": "VA", "梵蒂冈": "VA", "科索沃": "XK",
        "英國": "GB", "美国": "US", "美國": "US", "阿聯酋": "AE", "阿联酋": "AE",
        "UK": "GB", "USA": "US", "UAE": "AE",
    }.items()})
    return aliases


@lru_cache(maxsize=1)
def _valid_country_codes() -> set[str]:
    """只接受 CLDR 國家／地區碼與 Kosovo，避免把任意兩字母當作國家。"""
    codes = {code.upper() for code in Locale.parse("en").territories
             if len(code) == 2 and code.isalpha()}
    return (codes | {"XK"}) - NON_DESTINATION_CODES


def resolve_country_code(value: str) -> str | None:
    """接受繁中、簡中、英文國名或 ISO2 國碼。"""
    text = value.strip()
    alias = _country_aliases().get(_normalize(text))
    if alias:
        return alias
    code = text.upper()
    if len(code) == 2 and code.isascii() and code.isalpha() and code in _valid_country_codes():
        return code
    return None


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
        code = resolve_country_code(parts[0])
        if code:
            return " ".join(parts[1:]), code
    words = text.split()
    for start in range(1, len(words)):
        code = resolve_country_code(" ".join(words[start:]))
        if code:
            return " ".join(words[:start]), code
    for end in range(len(words) - 1, 0, -1):
        code = resolve_country_code(" ".join(words[:end]))
        if code:
            return " ".join(words[end:]), code
    # 支援常見中文連寫，例如「巴黎法國」、「東京日本」。
    if re.search(r"[\u3400-\u9fff]", text):
        normalized = _normalize(text)
        matches = [(alias, code) for alias, code in _country_aliases().items()
                   if len(alias) >= 2 and normalized.endswith(alias) and normalized != alias]
        if matches:
            alias, code = max(matches, key=lambda item: len(item[0]))
            city = normalized[:-len(alias)].strip()
            if city:
                return city, code
        matches = [(alias, code) for alias, code in _country_aliases().items()
                   if len(alias) >= 2 and normalized.startswith(alias) and normalized != alias]
        if matches:
            alias, code = max(matches, key=lambda item: len(item[0]))
            city = normalized[len(alias):].strip()
            if city:
                return city, code
    return text, None


def city_search_name(city: str) -> str:
    value = city.strip()
    aliases = {name.casefold(): target for name, target in CITY_ALIASES.items()}
    return aliases.get(value.casefold(), value)


def corrected_destination(destination: str) -> tuple[str, str | None]:
    """校正常見且意思明確的地名錯置，並回傳給使用者看的說明。"""
    value = destination.strip()
    corrected = DESTINATION_CORRECTIONS.get(value)
    if not corrected:
        return value, None
    return corrected, f"已將「{value}」校正為「庫斯科 Cusco（秘魯）」後查詢。"


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
    """取得國家的代表城市；世界銀行缺資料時以免費地名服務安全備援。"""
    country_code = country_code.upper()
    if country_code not in _valid_country_codes():
        raise LocationServiceError(f"無效的國家／地區代碼：{country_code}")
    if country_code in COUNTRY_REFERENCE_OVERRIDES:
        return {**COUNTRY_REFERENCE_OVERRIDES[country_code], "country_code": country_code,
                "fallback_to_capital": True, "reference_kind": "representative_city"}
    data = None
    try:
        data = _get_json(f"https://api.worldbank.org/v2/country/{country_code.lower()}",
                         {"format": "json"})
    except LocationServiceError:
        # 下方仍會嘗試不需金鑰的 Open-Meteo 地名資料。
        pass
    try:
        record = data[1][0]
        if not record.get("capitalCity") or not record.get("latitude") or not record.get("longitude"):
            raise ValueError("首都資料不完整")
        return {"name": record["capitalCity"], "latitude": float(record["latitude"]),
                "longitude": float(record["longitude"]), "country_code": country_code.upper(),
                "fallback_to_capital": True, "reference_kind": "capital"}
    except (IndexError, KeyError, TypeError, ValueError):
        pass

    english_name = str(Locale.parse("en").territories.get(country_code, country_code))
    try:
        result = _get_json("https://geocoding-api.open-meteo.com/v1/search", {
            "name": english_name, "count": 10, "language": "en", "format": "json",
            "countryCode": country_code,
        })
        rows = result.get("results") or [] if isinstance(result, dict) else []
        rows = [row for row in rows if (row.get("country_code") or "").upper() == country_code]
        if rows:
            # 首都優先；若只有國家中心仍明確標記，不冒稱首都。
            row = min(rows, key=lambda item: {
                "PPLC": 0, "PPLA": 1, "PPLA2": 2, "PCLI": 3, "PCLS": 3,
            }.get(item.get("feature_code"), 9))
            kind = "capital" if row.get("feature_code") == "PPLC" else "country_center"
            return {"name": row.get("name") or english_name,
                    "latitude": float(row["latitude"]), "longitude": float(row["longitude"]),
                    "country_code": country_code, "fallback_to_capital": kind == "capital",
                    "fallback_to_country_center": kind == "country_center",
                    "reference_kind": kind}
    except (LocationServiceError, KeyError, TypeError, ValueError):
        pass
    raise LocationServiceError(f"{english_name} 目前沒有可用的首都或代表座標")


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
