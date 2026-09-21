"""可選 LLM 整合；無金鑰時返回可驗證的規則式摘要。"""
import httpx

from utils.config import secret


def _fallback(facts: dict) -> str:
    """即使未設定 LLM，也依本次行程資料產生具體且可驗證的建議。"""
    spending = facts["spending"]
    total = spending["total"]
    budget = total + spending["remaining"]
    destination = facts["destination"]
    preference = facts["preference"]
    days = facts["days"]
    if spending["within_budget"]:
        budget_text = (f"{destination}{days}日行程預估共 {total:,.0f} 元，"
                       f"在 {budget:,.0f} 元預算內，約可保留 {spending['remaining']:,.0f} 元彈性。")
    else:
        over = abs(spending["remaining"])
        largest = max(spending["components"], key=spending["components"].get)
        budget_text = (f"{destination}{days}日行程預估共 {total:,.0f} 元，超出預算 {over:,.0f} 元；"
                       f"最大支出是{largest}，建議先從此項降低至少 {over:,.0f} 元。")

    hotel = facts.get("hotel")
    hotel_text = (f"目前住宿基準為「{hotel['name']}」每晚約 {hotel['price']:,.0f} 元。"
                  if hotel else "目前沒有符合條件的住宿資料，請另行查價。")
    preference_text = f"景點已依「{preference}」偏好優先排序。"

    weather = (facts.get("external") or {}).get("weather")
    if weather and weather.get("available"):
        weather_text = (f"出發日預報 {weather['min_c']}–{weather['max_c']}°C，"
                        f"最高降雨機率 {weather['rain_probability']}%，請依天氣準備。")
    elif weather:
        weather_text = f"天氣資訊目前不可用：{weather.get('message', '未知原因')}。"
    else:
        weather_text = "未啟用即時天氣；出發前請再次確認預報。"
    notes = facts.get("notes") or []
    rag_text = ""
    if notes:
        excerpt = str(notes[0].get("text", ""))[:120]
        rag_text = f"知識庫提示：{excerpt}"
    return " ".join(item for item in [budget_text, hotel_text, preference_text, weather_text, rag_text,
                     "住宿與景點為示範資料，預訂前請核對即時價格與營業資訊。"] if item)


def advice(facts: dict) -> dict:
    fallback = _fallback(facts)
    key = secret("OPENAI_API_KEY")
    if not key:
        return {"text": fallback, "source": "個人化規則式建議（未設定 LLM 金鑰）"}
    # 只傳送結構化行程摘要；使用者上傳的 RAG 筆記不傳給外部 LLM。
    public_notes = [item.get("text", "")[:160] for item in facts.get("notes", [])
                    if item.get("source") == "內建旅遊筆記"]
    payload = {"model": secret("OPENAI_MODEL", "gpt-4.1-mini"), "max_output_tokens": 250,
               "instructions": "你是繁體中文旅遊助理。僅依提供事實給三至五句具體建議；必須說明預算差額，不得捏造即時價格、天氣、來源或預訂狀態。",
               "input": str({"destination": facts["destination"], "days": facts["days"],
                             "preference": facts["preference"], "spending": facts["spending"],
                             "hotel": facts.get("hotel"), "external": facts.get("external"),
                             "public_rag_excerpt": public_notes})}
    try:
        with httpx.Client(timeout=12) as client:
            response = client.post("https://api.openai.com/v1/responses", json=payload,
                                   headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            data = response.json()
        parts = [part.get("text", "") for item in data.get("output", [])
                 for part in item.get("content", []) if part.get("type") == "output_text"]
        text = "\n".join(parts).strip()
        if text:
            return {"text": text, "source": "LLM"}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        pass
    return {"text": fallback, "source": "規則式備援（LLM 不可用）"}
