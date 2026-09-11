"""酒店 LLM 精选：从高德返回的 Top5 酒店中根据用户偏好选 1 家。

成功：返回选中的 Hotel 对象。
失败：返回 None，上层用原始排序首位兜底。
"""

from __future__ import annotations

from travel_assistant.domain.models import Hotel
from travel_assistant.llm.client import get_llm_client
from travel_assistant.llm.parsers import parse_hotel_select
from travel_assistant.llm.prompts import HOTEL_SELECT_SYSTEM, HOTEL_SELECT_USER
from travel_assistant.observability.logging import get_logger

logger = get_logger(__name__)


def _build_user(hotels: list[Hotel], preferences: list[str]) -> str:
    lines = "\n".join(
        f"- {h.name} | 地址：{h.address or '未知'} | 距核心景点：{h.distance}米"
        for h in hotels
    )
    prefs = "、".join(preferences) if preferences else "无特定偏好"
    return HOTEL_SELECT_USER.format(preferences=prefs, hotel_lines=lines)


async def select_hotel_by_llm(
    hotels: list[Hotel], preferences: list[str]
) -> Hotel | None:
    """LLM 从候选酒店中精选 1 家；失败返回 None。"""
    if not hotels:
        return None

    allowed = {h.name for h in hotels}
    by_name = {h.name: h for h in hotels}
    user_prompt = _build_user(hotels, preferences)

    data = await get_llm_client().chat_json(
        HOTEL_SELECT_SYSTEM, user_prompt, max_tokens=512, temperature=0.2
    )
    name = parse_hotel_select(data, allowed)
    if name is None:
        logger.warning("hotel_select_llm_failed")
        return None

    logger.info("hotel_select_ok", selected=name)
    return by_name[name]
