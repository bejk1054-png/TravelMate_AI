"""目的地文字正規化工具，供天氣與 Booking 服務共用。"""
import re


def destination_candidates(destination: str) -> list[str]:
    """由完整地名逐步移除尾端國家/地區，避免地名 API 拒絕多詞查詢。"""
    raw = destination.strip()
    separated = [item.strip() for item in re.split(r"[,，、/]+", raw) if item.strip()]
    normalized = " ".join(separated)
    if len(separated) > 1:
        # 有明確逗號時，優先保留逗號前可能含空格的完整城市名（例如 New York）。
        return list(dict.fromkeys([normalized, separated[0]]))
    parts = normalized.split()
    candidates = [" ".join(parts[:length]) for length in range(len(parts), 0, -1)]
    # 保留順序並排除重複字串。
    return list(dict.fromkeys(item for item in candidates if item))
