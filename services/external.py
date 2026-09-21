"""外部 API 的界線；失敗時回報原因，不捏造即時資料。"""
import httpx

# 系統目前支援的目的地固定，直接使用官方城市中心座標，避免地名 API 無法解析中文。
DESTINATION_COORDINATES = {
    "台北": {"name": "台北", "latitude": 25.0330, "longitude": 121.5654},
    "東京": {"name": "東京", "latitude": 35.6762, "longitude": 139.6503},
    "京都": {"name": "京都", "latitude": 35.0116, "longitude": 135.7681},
    "首爾": {"name": "首爾", "latitude": 37.5665, "longitude": 126.9780},
}


def _get(url: str, params: dict) -> dict:
    try:
        with httpx.Client(timeout=5, follow_redirects=False) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise RuntimeError(f"外部服務暫時無法使用：{type(exc).__name__}") from exc


def weather(destination: str, date: str) -> dict:
    point = DESTINATION_COORDINATES.get(destination)
    if point is None:
        raise ValueError(f"尚未支援目的地：{destination}")
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
