"""SQLite 行程紀錄；正式環境需將檔案放在持久化儲存。"""
import json
import sqlite3
from datetime import datetime, timezone

from utils.config import DB_PATH


def connect():
    # 每次請求獨立連線，避免跨執行緒共用連線。
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("""CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        destination TEXT NOT NULL,
        request_json TEXT NOT NULL,
        result_json TEXT NOT NULL
    )""")
    return connection


def save_plan(request: dict, result: dict) -> int:
    with connect() as connection:
        cursor = connection.execute(
            "INSERT INTO plans(created_at,destination,request_json,result_json) VALUES (?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), request["destination"],
             json.dumps(request, ensure_ascii=False), json.dumps(result, ensure_ascii=False)),
        )
        return int(cursor.lastrowid)


def recent_plans(limit: int = 10) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT id,created_at,destination,request_json,result_json FROM plans ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 50)),),
        ).fetchall()
    return [{"id": row[0], "created_at": row[1], "destination": row[2],
             "request": json.loads(row[3]), "result": json.loads(row[4])} for row in rows]
