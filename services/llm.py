"""OpenAI Responses API；未配置或呼叫失敗時明示狀態，不冒稱 AI 已連線。"""
import json

import httpx

from utils.config import secret


def ai_status() -> dict:
    """只回報是否配置金鑰，不暴露金鑰內容。"""
    configured = bool(secret("OPENAI_API_KEY"))
    return {"configured": configured,
            "message": "已設定 AI 金鑰；實際連線結果以產生行程後為準。" if configured else
                       "尚未在 Render 設定 OPENAI_API_KEY；目前只能使用規則式建議。"}


def _fallback(facts: dict) -> str:
    spending = facts["spending"]
    hotel = facts.get("hotel")
    area = facts["destination"]
    parts = [f"{area} {facts['days']} 日行程：已列出真實地點名稱，但須核對開放時間與交通動線。"]
    if hotel:
        if hotel.get("price") is None:
            parts.append(f"「{hotel['name']}」有地圖資料，但房價待查；請到 Booking 輸入入住日期核價。")
        else:
            parts.append(f"「{hotel['name']}」查詢時每晚約 {hotel['price']:,.0f} 元；預訂前再確認稅費與房型。")
    else:
        parts.append("目前查不到可核實的住宿名稱，請先到 Booking 搜尋目的地。")
    if spending["total"] is None:
        missing = "、".join(spending["unknown_costs"])
        parts.append(f"已知與估算支出至少 {spending['known_subtotal']:,.0f} 元；{missing}待查，不能判定是否超過預算。")
    else:
        parts.append(f"完整估算 {spending['total']:,.0f} 元；"
                     f"{'預算內' if spending['within_budget'] else '超出預算'}，"
                     f"差額 {abs(spending['remaining']):,.0f} 元。")
    weather = (facts.get("external") or {}).get("weather")
    if weather and weather.get("available"):
        parts.append(f"出發日預報 {weather['min_c']}–{weather['max_c']}°C，請依天氣調整。")
    return " ".join(parts)


def advice(facts: dict) -> dict:
    fallback = _fallback(facts)
    key = secret("OPENAI_API_KEY")
    if not key:
        return {"text": fallback, "source": "規則式建議（非 AI）", "status": "unconfigured"}
    # 使用者上傳的個人筆記不送往外部模型；所有未知價格保留為 null。
    payload = {"model": secret("OPENAI_MODEL", "gpt-4.1-mini"), "max_output_tokens": 350,
               "store": False,
               "instructions": "你是繁體中文旅遊助理。只依提供資料提出三至五項可執行建議。"
                               "地點名稱不代表開放或可訂。null 表示費用未知，絕不可當零元，"
                               "也不能宣稱完整總額或預算充足。不得捏造門票、房價、交通或評論。",
               "input": json.dumps({"destination": facts["destination"], "days": facts["days"],
                                    "preference": facts["preference"], "spending": facts["spending"],
                                    "hotel": facts.get("hotel"), "spots": facts.get("spots"),
                                    "external": facts.get("external")}, ensure_ascii=False)}
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post("https://api.openai.com/v1/responses", json=payload,
                                   headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            data = response.json()
        parts = [part.get("text", "") for item in data.get("output", [])
                 for part in item.get("content", []) if part.get("type") == "output_text"]
        output = "\n".join(parts).strip()
        if output:
            return {"text": output, "source": "OpenAI AI 建議", "status": "connected"}
        reason = "AI 回傳空白內容"
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        reason = f"{type(exc).__name__}"
    return {"text": fallback, "source": "規則式備援（AI 呼叫失敗）",
            "status": "error", "message": f"AI 暫時不可用：{reason}"}
