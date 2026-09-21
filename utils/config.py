"""集中管理路徑與環境設定。"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DATA_DIR = ROOT / "data"
MODEL_PATH = ROOT / "models" / "hotel_price.joblib"
DB_PATH = Path(os.getenv("DATABASE_PATH") or DATA_DIR / "travelmate.db")
KNOWLEDGE_PATH = DATA_DIR / "knowledge.txt"


def secret(name: str, default: str = "") -> str:
    """只從環境變數取得後端秘密。"""
    return os.getenv(name, default)
