"""LLM 整合：優先使用 Gemini 免費層，亦支援 OpenAI；失敗時明示備援。"""
import json

import httpx

from utils.config import secret


def ai_status() -> dict:
    """只回報是否配置金鑰，不暴露金鑰內容。"""
    providers = []
    if secret("GEMINI_API_KEY"):
        providers.append("Gemini")
    if secret("OPENAI_API_KEY"):
        providers.append("OpenAI")
    configured = bool(providers)
    return {"configured": configured, "providers": providers,
            "preferred_provider": providers[0] if providers else None,
            "message": (f"已設定 {'、'.join(providers)}；實際連線結果以產生行程後為準。"
                        if configured else
                        "尚未設定 GEMINI_API_KEY 或 OPENAI_API_KEY；目前使用規則式建議。")}


def _fallback(facts: dict) -> str:
    spending = facts["spending"]
    hotel = facts.get("hotel")
    area = facts["destination"]
    if facts.get("has_verified_spots", bool(facts.get("spots"))):
        parts = [f"{area} {facts['days']} 日行程：已列出可核對的地點名稱，但須再確認開放時間與交通動線。"]
    else:
        parts = [f"{area}：目前沒有取得可核實的景點，請檢查目的地名稱或稍後重試；未產生景點行程。"]
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
        parts.append(f"已列項目估算 {spending['total']:,.0f} 元（不含機票與跨城交通）；"
                     f"{'預算內' if spending['within_budget'] else '超出預算'}，"
                     f"差額 {abs(spending['remaining']):,.0f} 元。")
    weather = (facts.get("external") or {}).get("weather")
    if weather and weather.get("available"):
        parts.append(f"出發日預報 {weather['min_c']}–{weather['max_c']}°C，請依天氣調整。")
    return " ".join(parts)


def _safe_facts(facts: dict) -> dict:
    """個人上傳筆記不送第三方模型；只送行程計算需要的非敏感欄位。"""
    return {"destination": facts["destination"], "days": facts["days"],
            "preference": facts["preference"], "spending": facts["spending"],
            "hotel": facts.get("hotel"), "spots": facts.get("spots"),
            "external": facts.get("external")}


def _instruction() -> str:
    return ("你是繁體中文旅遊助理。只依提供資料提出三至五項可執行建議。"
            "每項要說明理由，並區分即時資料、公開資料與估算。"
            "地點名稱不代表開放或可訂。null 表示費用未知，絕不可當零元，"
            "也不能宣稱完整總額或預算充足。不得捏造門票、房價、交通或評論。")


def _gemini_advice(facts: dict, key: str) -> str:
    model = secret("GEMINI_MODEL", "gemini-3.1-flash-lite")
    payload = {
        "systemInstruction": {"parts": [{"text": _instruction()}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(
            _safe_facts(facts), ensure_ascii=False
        )}]}],
        "generationConfig": {"maxOutputTokens": 500, "temperature": 0.3},
    }
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                json=payload, headers={"x-goog-api-key": key, "Content-Type": "application/json"})
            response.raise_for_status()
            data = response.json()
        return "\n".join(part.get("text", "")
                         for candidate in data.get("candidates", [])
                         for part in (candidate.get("content") or {}).get("parts", [])).strip()
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise RuntimeError(type(exc).__name__) from exc


def _openai_advice(facts: dict, key: str) -> str:
    payload = {"model": secret("OPENAI_MODEL", "gpt-4.1-mini"), "max_output_tokens": 500,
               "store": False, "instructions": _instruction(),
               "input": json.dumps(_safe_facts(facts), ensure_ascii=False)}
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post("https://api.openai.com/v1/responses", json=payload,
                                   headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            data = response.json()
        return "\n".join(part.get("text", "") for item in data.get("output", [])
                         for part in item.get("content", [])
                         if part.get("type") == "output_text").strip()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(type(exc).__name__) from exc


def advice(facts: dict) -> dict:
    fallback = _fallback(facts)
    configured = []
    if secret("GEMINI_API_KEY"):
        configured.append(("Gemini", _gemini_advice, secret("GEMINI_API_KEY")))
    if secret("OPENAI_API_KEY"):
        configured.append(("OpenAI", _openai_advice, secret("OPENAI_API_KEY")))
    if not configured:
        return {"text": fallback, "source": "規則式建議（非 AI）", "status": "unconfigured"}
    errors = []
    for provider, call, key in configured:
        try:
            output = call(facts, key)
            if output:
                return {"text": output, "source": f"{provider} AI 建議",
                        "provider": provider, "status": "connected"}
            errors.append(f"{provider}：空白回覆")
        except RuntimeError as exc:
            errors.append(f"{provider}：{exc}")
    return {"text": fallback, "source": "規則式備援（AI 呼叫失敗）",
            "status": "error", "message": "AI 暫時不可用（" + "；".join(errors) + "）"}
