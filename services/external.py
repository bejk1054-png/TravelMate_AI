"""外部 API 的界線；失敗時回報原因，不捏造即時資料。"""
import httpx


def _get(url: str, params: dict) -> dict:
    try:
        with httpx.Client(timeout=5, follow_redirects=False) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise RuntimeError(f"外部服務暫時無法使用：{type(exc).__name__}") from exc


def weather(destination: str, date: str) -> dict:
    location = _get("https://geocoding-api.open-meteo.com/v1/search", {"name": destination, "count": 1})
    matches = location.get("results") or []
    if not matches:
        raise RuntimeError("找不到目的地的天氣座標")
    point = matches[0]
    forecast = _get("https://api.open-meteo.com/v1/forecast", {
        "latitude": point["latitude"], "longitude": point["longitude"],
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto", "forecast_days": 16,
    }).get("daily", {})
    dates = forecast.get("time", [])
    if date not in dates:
        return {"available": False, "message": "選定日期不在天氣預報範圍（約未來 16 天）"}
    i = dates.index(date)
    return {"available": True, "date": date, "location": point.get("name", destination),
            "max_c": forecast["temperature_2m_max"][i], "min_c": forecast["temperature_2m_min"][i],
            "rain_probability": forecast["precipitation_probability_max"][i]}


def currency(base: str = "TWD", quote: str = "JPY") -> dict:
    base, quote = base.upper(), quote.upper()
    if not (base.isalpha() and quote.isalpha() and len(base) == len(quote) == 3):
        raise ValueError("請使用三碼幣別代碼")
    if base == quote:
        return {"base": base, "quote": quote, "rate": 1.0, "date": "相同幣別"}
    data = _get(f"https://api.frankfurter.dev/v2/rate/{base.lower()}/{quote.lower()}", {})
    rate = data.get("rate")
    if rate is None:
        raise RuntimeError("匯率服務沒有提供所選幣別")
    return {"base": base, "quote": quote, "rate": rate, "date": data.get("date")}
