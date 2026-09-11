"""Supervisor（行程总监）：意图提取 + 最终天级编排聚合。

- 提取：LLM 意图 -> 高德 geocode 校验城市真实存在（防幻觉城市入图）；
- 聚合：LLM 天级编排，>N 次不可信则丢弃 LLM 结果，走距离贪心（L2）。
"""

from __future__ import annotations

from travel_assistant.agents.common import itinerary_dates, record_run, trace_node
from travel_assistant.domain.models import DegradedLevel, Itinerary, Weather
from travel_assistant.fallback.greedy_planner import greedy_plan
from travel_assistant.llm.arrangement import arrange_pois_by_llm
from travel_assistant.llm.intents import extract_trip_intent
from travel_assistant.observability.logging import get_logger
from travel_assistant.tools.geocode_tool import geocode_city

logger = get_logger(__name__)


@trace_node("supervisor_extract")
async def supervisor_extract(state: dict) -> dict:
    query = state.get("query", "")
    draft = await extract_trip_intent(query)
    if draft is None:
        logger.warning("extract_no_city_L4")
        return {"fatal": True, "warnings": ["无法识别出游城市"]}

    center = await geocode_city(draft.city)
    if center is None:
        logger.warning("extract_geocode_failed_L4", city=draft.city)
        return {"fatal": True, "city": draft.city, "warnings": [f"城市无法校验：{draft.city}"]}

    logger.info("extract_ok", city=center.name, adcode=center.adcode, days=draft.days)
    return {
        "city": draft.city,
        "adcode": center.adcode,
        "days": draft.days,
        "preferences": draft.preferences,
        "center": center,
        "fatal": False,
    }


@trace_node("supervisor_aggregate")
async def supervisor_aggregate(state: dict) -> dict:
    # Barrier 就绪门：多入边会多次调度本节点，必须两路到齐且只真实编排一次
    if state.get("aggregated"):
        return {}
    if "weathers" not in state or "hotels" not in state:
        return {}
    record_run("supervisor_aggregate")

    city = state.get("city", "")
    days = state.get("days", 1)
    preferences = state.get("preferences", [])
    center = state.get("center")
    pois = state.get("pois", [])
    weathers = state.get("weathers", [])
    hotels = state.get("hotels", [])
    restaurants = state.get("restaurants", [])

    warnings: list[str] = []
    degraded = DegradedLevel.NONE

    # L1 痕迹：部分真实数据缺失（工具层已吞掉异常）
    if not weathers or weathers[0].condition == "unavailable":
        degraded = max(degraded, DegradedLevel.L1_API)
        warnings.append("气象数据不可用，已置为 unavailable")
    if not hotels:
        degraded = max(degraded, DegradedLevel.L1_API)
        warnings.append("食宿检索无结果")
    if not pois:
        degraded = max(degraded, DegradedLevel.L1_API)
        warnings.append("景点检索无结果")

    # L2：先尝试 LLM 编排，多次失败再贪心兜底
    groups = None
    if pois:
        groups = await arrange_pois_by_llm(city, days, preferences, pois)
        if groups is None:
            groups = greedy_plan(center, pois, days)
            degraded = max(degraded, DegradedLevel.L2_FILTER)
            warnings.append("LLM 路线编排多次失败，已切换距离贪心算法")
    else:
        groups = [[] for _ in range(days)]

    dates = [w.date for w in weathers] if weathers else itinerary_dates(days)
    if len(dates) < days:
        dates += itinerary_dates(days)[len(dates):]

    itineraries: list[Itinerary] = []
    for i in range(days):
        d = dates[i]
        itineraries.append(
            Itinerary(
                date=d,
                weather=weathers[i] if i < len(weathers) else Weather.unavailable(d),
                # 同一酒店作为全程住宿基线（就近核心景点）；P7 可按天细化
                hotel=hotels[0] if hotels else None,
                pois=groups[i] if i < len(groups) else [],
                restaurants=restaurants if i == 0 else [],
            )
        )

    return {
        "itineraries": itineraries,
        "aggregated": True,
        "degraded_level": int(degraded),
        "warnings": warnings,
    }
