"""可選 LLM 整合；無金鑰時返回可驗證的規則式摘要。"""
import httpx

from utils.config import secret


def advice(facts: dict) -> dict:
    budget = facts["spending"]
    fallback = ("預算內可優先選擇評分高、交通方便的住宿。" if budget["within_budget"]
                else "目前估算超過預算，建議調低住宿級距、減少付費景點或調整天數。")
    fallback += " 景點與住宿為示範資料，出發前請確認即時價格、營業時間與交通。"
    key = secret("OPENAI_API_KEY")
    if not key:
        return {"text": fallback, "source": "規則式建議（未設定 LLM 金鑰）"}
    # 只傳送必要摘要，不傳個人筆記全文或資料庫紀錄。
    payload = {"model": secret("OPENAI_MODEL", "gpt-4.1-mini"), "max_output_tokens": 250,
               "instructions": "你是繁體中文旅遊助理。僅依提供事實給兩句建議；不得捏造即時價格、天氣、來源或預訂狀態。",
               "input": str({"destination": facts["destination"], "days": facts["days"],
                             "preference": facts["preference"], "budget": budget,
                             "retrieved_notes": facts["notes"]})}
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
