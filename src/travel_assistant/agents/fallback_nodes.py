"""降级类图节点：L4 全局兜底（L3 经典路线节点在 P5 加入）。"""

from __future__ import annotations

from travel_assistant.agents.common import trace_node
from travel_assistant.domain.models import DegradedLevel
from travel_assistant.fallback.degrader import build_l4_message


@trace_node("global_fallback")
async def global_fallback(state: dict) -> dict:
    city = state.get("city")
    message = build_l4_message(city)
    return {
        "fatal": True,
        "degraded_level": DegradedLevel.L4_GLOBAL,
        "fallback_message": message,
        "itineraries": [],
        "aggregated": True,
    }
