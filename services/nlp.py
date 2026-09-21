"""可離線重現的中文詞典式情緒與評論摘要，並非大型語言模型。"""
from collections import Counter

from services.analytics import hotels

POSITIVE = ("乾淨", "方便", "親切", "安靜", "寬敞", "漂亮", "好吃", "便宜")
NEGATIVE = ("偏小", "偏貴", "隔音差", "不便", "遠", "吵", "髒")


def analyze_reviews(destination: str) -> dict:
    reviews = hotels().loc[lambda df: df.destination.eq(destination), "review"].fillna("").tolist()
    positives = Counter(word for review in reviews for word in POSITIVE if word in review)
    negatives = Counter(word for review in reviews for word in NEGATIVE if word in review)
    positive_count = sum(sum(word in review for word in POSITIVE) >= sum(word in review for word in NEGATIVE)
                         for review in reviews)
    return {"positive": positive_count, "negative": len(reviews) - positive_count,
            "advantages": [word for word, _ in positives.most_common(3)],
            "disadvantages": [word for word, _ in negatives.most_common(3)],
            "summary": f"共 {len(reviews)} 則示範評論；常見優點：{'、'.join(positives) or '無'}；常見缺點：{'、'.join(negatives) or '無'}。"}
