"""工具只做一件事，由單一 Agent 決定何時呼叫。"""
from rag.knowledge import knowledge
from services.analytics import recommend_hotels, spending
from services.external import currency, weather


def weather_tool(destination: str, date: str) -> dict:
    return weather(destination, date)


def hotel_tool(destination: str, max_nightly: float) -> list[dict]:
    return recommend_hotels(destination, max_nightly)


def currency_tool(base: str, quote: str) -> dict:
    return currency(base, quote)


def budget_tool(days: int, people: int, hotel_price: float, spot_costs: list[float], budget: float) -> dict:
    return spending(days, people, hotel_price, spot_costs, budget)


def rag_tool(query: str) -> list[dict]:
    return knowledge.retrieve(query)
