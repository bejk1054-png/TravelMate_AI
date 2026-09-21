"""Pandas / NumPy 清理、分析與推薦。所有金額為新台幣示範資料。"""
import numpy as np
import pandas as pd

from utils.config import DATA_DIR

FEATURES = ["rating", "distance", "room_size", "stars", "season"]


def hotels() -> pd.DataFrame:
    frame = pd.read_csv(DATA_DIR / "hotels.csv")
    for column in FEATURES + ["price"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["name", "destination", "price"])
    frame = frame.drop_duplicates(subset=["name", "destination"])
    for column in FEATURES:
        frame[column] = frame[column].fillna(frame[column].median())
    return frame.loc[frame.price.gt(0) & frame.rating.between(0, 5)].copy()


def spots(destination: str, preference: str = "") -> list[dict]:
    frame = pd.read_csv(DATA_DIR / "spots.csv")
    frame = frame.loc[frame.destination.eq(destination)].copy()
    if preference:
        # 偏好只影響排序，不丟棄其他景點。
        frame["match"] = frame.category.map(lambda item: int(item in preference))
        frame = frame.sort_values("match", ascending=False, kind="stable")
    return frame.drop(columns=["match"], errors="ignore").to_dict("records")


def recommend_hotels(destination: str, max_nightly: float) -> list[dict]:
    frame = hotels().loc[lambda df: df.destination.eq(destination) & df.price.le(max_nightly)]
    frame = frame.sort_values(["rating", "price", "distance"], ascending=[False, True, True])
    return frame.head(4).drop(columns="review").to_dict("records")


def summary(destination: str | None = None) -> dict:
    frame = hotels()
    if destination:
        frame = frame.loc[frame.destination.eq(destination)]
    if frame.empty:
        return {"count": 0, "describe": {}, "by_room_type": [], "correlation": {}, "prices": []}
    numeric = frame[["price", "rating", "distance", "room_size", "stars", "season"]]
    return {
        "count": len(frame),
        "describe": numeric.describe().round(2).fillna(0).to_dict(),
        "by_room_type": frame.groupby("room_type", as_index=False).agg(
            count=("price", "size"), mean_price=("price", "mean"), mean_rating=("rating", "mean")
        ).round(2).to_dict("records"),
        "correlation": numeric.corr().round(3).fillna(0).to_dict(),
        "prices": frame[["name", "destination", "room_type", "price", "rating", "distance"]].to_dict("records"),
        "price_median": float(np.median(frame.price.to_numpy())),
    }


def spending(days: int, people: int, hotel_price: float, spot_costs: list[float], budget: float) -> dict:
    # 住宿按房間估算，假設一間房最多兩人；其他費用按人計。
    rooms = int(np.ceil(people / 2))
    nights = max(days - 1, 0)
    lodging = float(hotel_price * nights * rooms)
    attractions = float(np.sum(spot_costs) * people)
    meals = float(900 * days * people)
    transport = float(350 * days * people)
    components = {"住宿": lodging, "景點": attractions, "餐食估算": meals, "市內交通估算": transport}
    total = float(np.sum(list(components.values())))
    return {"components": components, "total": total, "remaining": round(budget - total, 2),
            "daily": round(total / days, 2), "within_budget": total <= budget,
            "assumptions": f"新台幣；{days} 天按 {nights} 晚住宿估算；每房最多兩人；"
                           "每人每日餐食 900、交通 350；不含機票與跨城交通。"}
