"""FastAPI 入口：API → 主 Agent → Service / Tools → 資料層。"""
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from uuid import UUID

from agents.travel_agent import plan
from api.schemas import PlanRequest, PredictRequest
from database.repository import recent_plans, save_plan
from models.price_model import predict
from rag.knowledge import extract, session_knowledge
from services.llm import ai_status
from utils.config import secret

app = FastAPI(title="TravelMate AI", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/plan")
def create_plan(body: PlanRequest):
    try:
        result = plan(body.model_dump(mode="json"))
        result["plan_id"] = save_plan(body.model_dump(mode="json"), result)
        return result
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=500, detail=f"行程產生失敗：{type(exc).__name__}") from exc


@app.get("/api/ai/status")
def get_ai_status():
    return ai_status()


@app.post("/api/predict")
def price_prediction(body: PredictRequest):
    return predict(body.model_dump())


@app.get("/api/plans")
def plans():
    # 公開 API 不可列出其他訪客的行程；本機教學可自行啟用。
    if secret("ENABLE_HISTORY_API") != "1":
        raise HTTPException(status_code=403, detail="行程歷史 API 預設關閉")
    return recent_plans()


@app.post("/api/knowledge")
async def upload_knowledge(file: UploadFile = File(...), session_id: UUID = Form(...)):
    # 限制傳輸大小並避免顯示伺服器路徑；公開展示站不建議開放任意上傳。
    if file.content_type not in ("text/plain", "text/csv", "application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="不支援的檔案類型")
    try:
        content = await file.read(5 * 1024 * 1024 + 1)
        text = extract(file.filename or "", content)
        base = session_knowledge(str(session_id))
        count = base.add((file.filename or "筆記").split("/")[-1].split("\\")[-1], text)
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()
    return {"chunks": count, "message": "已加入暫存知識庫；後端重啟後會消失"}
