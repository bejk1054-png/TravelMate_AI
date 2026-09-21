"""示範住宿價格模型；少量樣本僅供流程教學，不能視為真實報價。"""
import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split

from services.analytics import FEATURES, hotels
from utils.config import MODEL_PATH


def train() -> dict:
    frame = hotels()
    x_train, x_test, y_train, y_test = train_test_split(
        frame[FEATURES], frame.price, test_size=0.25, random_state=42
    )
    model = RandomForestRegressor(n_estimators=100, random_state=42, min_samples_leaf=1)
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)
    metrics = {"mae": round(float(mean_absolute_error(y_test, predictions)), 2),
               "rmse": round(float(np.sqrt(mean_squared_error(y_test, predictions))), 2),
               "train_rows": len(x_train), "test_rows": len(x_test),
               "notice": "僅以少量示範資料訓練，不能用於訂房報價。"}
    # 寫入失敗仍可線上即時訓練，不阻斷唯讀部署。
    try:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": model, "metrics": metrics}, MODEL_PATH)
    except OSError:
        pass
    return {"model": model, "metrics": metrics}


def load_or_train() -> dict:
    if MODEL_PATH.exists():
        try:
            return joblib.load(MODEL_PATH)
        except (OSError, ValueError, EOFError):
            pass
    return train()


def predict(features: dict) -> dict:
    import pandas as pd
    data = {key: float(features[key]) for key in FEATURES}
    bundle = load_or_train()
    price = float(bundle["model"].predict(pd.DataFrame([data], columns=FEATURES))[0])
    return {"predicted_price_twd": round(price), "metrics": bundle["metrics"]}
