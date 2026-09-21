"""API 資料驗證。"""
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class PlanRequest(BaseModel):
    destination: Literal["台北", "台中", "高雄", "東京", "京都", "大阪", "札幌", "首爾", "釜山", "新加坡"]
    start_date: date
    days: int = Field(ge=1, le=14)
    people: int = Field(ge=1, le=20)
    budget_twd: float = Field(gt=0, le=10_000_000)
    preference: str = Field(default="文化", max_length=100)
    use_live_api: bool = False
    session_id: UUID | None = None

    @field_validator("destination", mode="before")
    @classmethod
    def strip_destination(cls, value):
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("目的地不可空白")
        return value


class PredictRequest(BaseModel):
    rating: float = Field(ge=0, le=5)
    distance: float = Field(ge=0, le=100)
    room_size: float = Field(gt=0, le=1000)
    stars: float = Field(ge=1, le=5)
    season: float = Field(ge=1, le=3)
