"""Pandas / NumPy 清理、分析與推薦。所有金額為新台幣示範資料。"""
import numpy as np
import pandas as pd

from utils.config import DATA_DIR

FEATURES = ["rating", "distance", "room_size", "stars", "season"]
SQM_PER_PING = 3.305785


def sqm_to_ping(square_metres: float) -> float:
    """將平方公尺轉為台灣常用的坪數，僅用於顯示且保留一位小數。"""
    return round(float(square_metres) / SQM_PER_PING, 1)


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
    total_count = len(frame)
    if destination:
        frame = frame.loc[frame.destination.eq(destination)]
    if frame.empty:
        return {"count": 0, "total_count": total_count, "describe": {}, "by_room_type": [],
                "correlation": {}, "prices": [], "source": "TravelMate AI 教學示範資料"}
    numeric = frame[["price", "rating", "distance", "room_size", "stars", "season"]]
    prices = frame[["name", "destination", "room_type", "price", "rating", "distance", "room_size"]].copy()
    prices["room_size_ping"] = prices["room_size"].map(sqm_to_ping)
    return {
        "count": len(frame),
        "total_count": total_count,
        "describe": numeric.describe().round(2).fillna(0).to_dict(),
        "by_room_type": frame.groupby("room_type", as_index=False).agg(
            count=("price", "size"), mean_price=("price", "mean"), mean_rating=("rating", "mean")
        ).round(2).to_dict("records"),
        "correlation": numeric.corr().round(3).fillna(0).to_dict(),
        "prices": prices.to_dict("records"),
        "price_median": float(np.median(frame.price.to_numpy())),
        "source": "TravelMate AI 教學示範資料",
    }


def summary_from_records(records: list[dict], source: str) -> dict:
    """分析 Booking API 回傳的單一目的地住宿，不填造缺少欄位。"""
    frame = pd.DataFrame(records)
    if frame.empty:
        return {"count": 0, "total_count": 0, "describe": {}, "by_room_type": [],
                "correlation": {}, "prices": [], "source": source}
    for column in ("price", "price_total", "rating", "distance", "room_size", "room_size_ping"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    priced = frame.dropna(subset=["price"]).copy()
    numeric_columns = [column for column in (
        "price", "price_total", "rating", "distance", "room_size", "stars", "season"
    )
                       if column in priced and priced[column].notna().any()]
    numeric = priced[numeric_columns]
    by_room = []
    if not priced.empty and "room_type" in priced:
        aggregations = {"count": ("price", "size"), "mean_price": ("price", "mean")}
        if "rating" in priced and priced["rating"].notna().any():
            aggregations["mean_rating"] = ("rating", "mean")
        by_room = priced.groupby("room_type", as_index=False).agg(**aggregations).round(2).to_dict("records")
    output_columns = [column for column in (
        "name", "destination", "room_type", "price", "price_total", "currency", "rating",
        "distance", "room_size", "room_size_ping", "stars", "season", "price_source", "booking_url"
    ) if column in frame]
    prices = frame[output_columns].replace({np.nan: None}).to_dict("records")
    return {
        "count": len(frame), "total_count": len(frame),
        "describe": numeric.describe().round(2).fillna(0).to_dict() if not numeric.empty else {},
        "by_room_type": by_room,
        "correlation": numeric.corr().round(3).fillna(0).to_dict() if len(numeric_columns) > 1 else {},
        "prices": prices,
        "price_median": float(np.median(priced.price.to_numpy())) if not priced.empty else None,
        "source": source,
    }


def demo_destination_records(destination: str, count: int = 40) -> list[dict]:
    """建立單一目的地的教學分析樣本，不冒充真實旅館或 Booking 價格。"""
    base = hotels().reset_index(drop=True)
    if base.empty or not destination.strip():
        return []
    # 以目的地字串產生穩定的調整係數，讓同一輸入每次結果一致。
    factor = 0.85 + (sum(destination.encode("utf-8")) % 31) / 100
    output = []
    for index in range(max(int(count), 0)):
        source = base.iloc[index % len(base)]
        room_size = float(source["room_size"])
        output.append({
            "name": f"{destination.strip()} 教學住宿 {index + 1:02d}",
            "destination": destination.strip(), "room_type": source["room_type"],
            "price": round(float(source["price"]) * factor / 10) * 10,
            "rating": float(source["rating"]), "distance": float(source["distance"]),
            "room_size": room_size, "room_size_ping": sqm_to_ping(room_size),
            "stars": float(source["stars"]), "season": float(source["season"]),
            "price_source": "TravelMate AI 教學延伸樣本（非 Booking 即時價）",
        })
    return output


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
