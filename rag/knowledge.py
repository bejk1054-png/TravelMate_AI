"""檔案 → 文字切塊 → TF-IDF 稀疏向量 → cosine 檢索。

TF-IDF 是本機可執行的 embedding 基線；正式語意檢索可替換為向量服務。
"""
import csv
import io
import re
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from utils.config import KNOWLEDGE_PATH

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
BUILTIN_DESTINATIONS = {"台北", "台中", "高雄", "東京", "京都", "大阪", "札幌", "首爾", "釜山", "新加坡"}


def extract(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("檔案不可超過 5 MB")
    if suffix == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > 50:
                raise ValueError("PDF 不可超過 50 頁")
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("PDF 無法解析；掃描圖片 PDF 需要先 OCR") from exc
    if suffix == ".txt":
        return content.decode("utf-8-sig")
    if suffix == ".csv":
        rows = csv.reader(io.StringIO(content.decode("utf-8-sig")))
        return "\n".join("；".join(row) for index, row in enumerate(rows) if index < 1000)
    raise ValueError("只支援 PDF、TXT、CSV")


def chunks(text: str, size: int = 400, overlap: int = 60) -> list[str]:
    # 優先依段落／句子切分，避免不同城市的筆記全部混進同一個檢索片段。
    sentences = [item.strip() for item in re.split(r"(?<=[。！？])\s*|[\r\n]+", text) if item.strip()]
    result = []
    for sentence in sentences:
        if len(sentence) <= size:
            result.append(sentence)
        else:
            result.extend(sentence[index:index + size]
                          for index in range(0, len(sentence), size - overlap) if sentence[index:index + size])
    return result


class KnowledgeBase:
    def __init__(self):
        self.documents: list[dict] = []
        self.vectorizer = None
        self.matrix = None
        self.add("內建旅遊筆記", KNOWLEDGE_PATH.read_text(encoding="utf-8"))

    def add(self, source: str, text: str) -> int:
        # 上傳內容只保留在此後端程序記憶體；重啟後需重新上傳。
        parts = chunks(text)
        if not parts:
            raise ValueError("文件沒有可讀的文字")
        if len(parts) > 200:
            raise ValueError("文件切塊不可超過 200 個")
        if len(self.documents) + len(parts) > 220:
            raise ValueError("此工作階段的知識庫已達上限，請重新整理頁面")
        self.documents.extend({"source": source, "text": part} for part in parts)
        self.vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 3), max_features=20000)
        self.matrix = self.vectorizer.fit_transform([item["text"] for item in self.documents])
        return len(parts)

    def retrieve(self, query: str, k: int = 3) -> list[dict]:
        if not query.strip():
            return []
        scores = cosine_similarity(self.vectorizer.transform([query]), self.matrix).ravel()
        results = []
        for index in scores.argsort()[::-1]:
            if scores[index] <= 0:
                continue
            document = self.documents[index]
            # 內建筆記以「城市：」開頭；不可只因偏好詞相同就把東京內容給肯亞。
            label = document["text"].split("：", 1)[0].strip()
            if (document["source"] == "內建旅遊筆記" and label in BUILTIN_DESTINATIONS
                    and label not in query):
                continue
            results.append({**document, "score": round(float(scores[index]), 3)})
            if len(results) >= k:
                break
        return results


knowledge = KnowledgeBase()


@lru_cache(maxsize=128)
def session_knowledge(session_id: str) -> KnowledgeBase:
    # UUID 是前端每個瀏覽器工作階段隨機產生的不可猜測識別碼；快取限制總記憶體。
    UUID(session_id)
    return KnowledgeBase()


def retrieve(query: str, session_id: str | None = None) -> list[dict]:
    base = session_knowledge(session_id) if session_id else knowledge
    return base.retrieve(query)
