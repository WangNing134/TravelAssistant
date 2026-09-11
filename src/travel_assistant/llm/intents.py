"""意图提取服务：LLM 优先，失败/不可信时规则兜底；城市再经高德 geocode 校验。"""

from __future__ import annotations

import re

from travel_assistant.llm.client import get_llm_client
from travel_assistant.llm.parsers import IntentDraft, parse_intent
from travel_assistant.llm.prompts import CITY_VOCAB, INTENT_SYSTEM, INTENT_USER_TEMPLATE
from travel_assistant.observability.logging import get_logger

logger = get_logger(__name__)

_DAY_PATTERNS = [
    re.compile(r"(\d+)\s*(?:天|日|晚)"),
    re.compile(r"一周|7天|七天"),
    re.compile(r"周末"),
]


async def _llm_intent(query: str) -> IntentDraft | None:
    data = await get_llm_client().chat_json(
        INTENT_SYSTEM, INTENT_USER_TEMPLATE.format(query=query)
    )
    return parse_intent(data)


def rule_based_intent(query: str) -> IntentDraft | None:
    """无 LLM 时的确定性兜底：城市词典命中 + 正则抽天数。"""
    city = next((c for c in CITY_VOCAB if c in query), "")
    if not city:
        return None

    days = 1
    if _DAY_PATTERNS[1].search(query):
        days = 7
    elif _DAY_PATTERNS[2].search(query):
        days = 2
    elif m := _DAY_PATTERNS[0].search(query):
        days = int(m.group(1))
    days = max(1, min(days, 7))

    remainder = query
    for token in (city, "市", "旅游", "旅行", "游玩", "玩", "去", "想", "计划", "天", "日"):
        remainder = remainder.replace(token, " ")
    m = re.search(r"\d+", remainder)
    if m:
        remainder = remainder.replace(m.group(0), " ")
    preferences = [p.strip() for p in re.split(r"[，,、\s]+", remainder) if len(p.strip()) >= 2]

    draft = IntentDraft(city=city, days=days, preferences=preferences[:5])
    logger.info("intent_rule_fallback", city=draft.city, days=draft.days)
    return draft


async def extract_trip_intent(query: str) -> IntentDraft | None:
    """返回可信意图；LLM 与规则都失败则 None（上层走 L4 文案）。"""
    draft = await _llm_intent(query)
    if draft is not None:
        logger.info("intent_llm_ok", city=draft.city, days=draft.days, prefs=draft.preferences)
        return draft

    logger.warning("intent_llm_unavailable_trying_rule")
    return rule_based_intent(query)
