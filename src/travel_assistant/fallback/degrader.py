"""降级决策与文案（P5 补齐 L3 经典路线库后此处统一收口）。"""

from __future__ import annotations

from travel_assistant.domain.models import DegradedLevel

# PRD Level 4 原文案模板
L4_MESSAGE_TEMPLATE = "系统正在维护，建议您在{city}核心商圈自由探索。"


def build_l4_message(city: str | None) -> str:
    return L4_MESSAGE_TEMPLATE.format(city=city or "当前城市")


def escalate(current: DegradedLevel | int, target: DegradedLevel | int) -> int:
    """降级级别只升不降。"""
    return max(int(current), int(target))
