"""天级路线 LLM 编排（L2 主战场）。

成功：返回按天分组的 POI（名称全部来自真实清单，恰好各用一次）。
失败：连续 max_attempts 次输出不可信（含幻觉/遗漏/组数错）时返回 None，
      由调用方切换贪心算法，并标记 degraded_level=2。
"""

from __future__ import annotations

from travel_assistant.config import get_settings
from travel_assistant.domain.models import POI
from travel_assistant.llm.client import get_llm_client
from travel_assistant.llm.parsers import parse_arrangement
from travel_assistant.llm.prompts import ARRANGE_SYSTEM, ARRANGE_USER_TEMPLATE
from travel_assistant.observability.logging import get_logger

logger = get_logger(__name__)


def _build_user(city: str, days: int, preferences: list[str], pois: list[POI]) -> str:
    lines = "\n".join(
        f"- {p.name} | {p.lng},{p.lat} | {p.duration}h" for p in pois
    )
    return ARRANGE_USER_TEMPLATE.format(
        city=city,
        days=days,
        preferences="、".join(preferences) if preferences else "无特定偏好",
        poi_lines=lines,
    )


async def arrange_pois_by_llm(
    city: str, days: int, preferences: list[str], pois: list[POI]
) -> list[list[POI]] | None:
    if not pois:
        return None

    allowed = {p.name for p in pois}
    by_name = {p.name: p for p in pois}
    max_attempts = get_settings().llm_arrange_max_attempts
    user_prompt = _build_user(city, days, preferences, pois)

    for attempt in range(1, max_attempts + 1):
        data = await get_llm_client().chat_json(
            ARRANGE_SYSTEM, user_prompt, max_tokens=1200, temperature=0.3
        )
        draft = parse_arrangement(data, days=days, allowed_names=allowed)
        if draft is not None:
            logger.info("arrange_llm_ok", attempts=attempt)
            return [[by_name[name] for name in group] for group in draft.day_groups]
        logger.warning("arrange_llm_invalid", attempt=attempt, max_attempts=max_attempts)

    logger.error("arrange_llm_exhausted_L2", max_attempts=max_attempts)
    return None
