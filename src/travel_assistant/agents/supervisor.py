"""Supervisor（行程总监）：意图提取 + 最终天级聚合。

P3：桩实现（无外部依赖，验证拓扑）。P4 起替换为 LLM + 真实工具 + L2/L3 兜底。
"""

from __future__ import annotations

from travel_assistant.agents.common import itinerary_dates, record_run, trace_node
from travel_assistant.domain.models import Hotel, Itinerary, Location, POI, Weather
from travel_assistant.fallback.greedy_planner import greedy_plan
from travel_assistant.observability.logging import get_logger

logger = get_logger(__name__)


def _stub_state_update() -> dict:
    return {
        "city": "成都",
        "adcode": "510100",
        "days": 2,
        "preferences": ["熊猫"],
        "center": Location(name="成都", adcode="510100", lng=104.066301, lat=30.572961),
        "degraded_level": 0,
        "warnings": [],
    }


@trace_node("supervisor_extract")
async def supervisor_extract(state: dict) -> dict:
    # P3 桩；P4：LLM 意图提取 -> 高德 geocode 校验真实城市
    return _stub_state_update()


@trace_node("supervisor_aggregate")
async def supervisor_aggregate(state: dict) -> dict:
    # Barrier 就绪门：LangGraph 多入边会按分支完成顺序多次调度本节点，
    # 必须等 weather 与 hotel 两路数据全部到齐，且真实编排只执行一次。
    if state.get("aggregated"):
        return {}
    if "weathers" not in state or "hotels" not in state:
        logger.info("aggregate_wait_barrier", present=[k for k in ("weathers", "hotels") if k in state])
        return {}
    record_run("supervisor_aggregate")

    # P3 桩：用贪心切分证明 fan-in 后状态完整；P4：先 LLM 编排，>3 次失败再贪心
    days = state.get("days", 1)
    center = state.get("center")
    groups = greedy_plan(center, state.get("pois", []), days)
    weathers = state.get("weathers", [])
    hotels = state.get("hotels", [])
    restaurants = state.get("restaurants", [])
    dates = itinerary_dates(days)

    itineraries: list[Itinerary] = []
    for i, d in enumerate(dates):
        itineraries.append(
            Itinerary(
                date=d,
                weather=weathers[i] if i < len(weathers) else Weather.unavailable(d),
                hotel=hotels[0] if hotels else None,
                pois=groups[i],
                restaurants=restaurants if i == 0 else [],
            )
        )
    return {"itineraries": itineraries, "aggregated": True}
