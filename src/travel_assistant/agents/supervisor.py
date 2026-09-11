"""Supervisor（行程总监）：意图提取 + 最终天级编排聚合。

- 提取：LLM 意图 -> 高德 geocode 校验城市真实存在（防幻觉城市入图）；超时/失败走 L4；
- 聚合：LLM 天级编排，>N 次不可信走贪心（L2）；熔断或无真实 POI 时走经典路线库（L3）。
"""

from __future__ import annotations

from travel_assistant.agents.common import (
    circuit_breaker,
    itinerary_dates,
    record_run,
    trace_node,
)
from travel_assistant.domain.models import DegradedLevel, Itinerary, Weather
from travel_assistant.fallback.classic import load_classic_itineraries
from travel_assistant.fallback.greedy_planner import greedy_plan
from travel_assistant.llm.arrangement import arrange_pois_by_llm
from travel_assistant.llm.intents import extract_trip_intent
from travel_assistant.observability.logging import get_logger
from travel_assistant.tools.geocode_tool import geocode_city

logger = get_logger(__name__)


@trace_node("supervisor_extract")
@circuit_breaker("supervisor_extract", {"fatal": True})
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
@circuit_breaker(
    "supervisor_aggregate",
    {"itineraries": [], "aggregated": True},
    aggregate=True,
)
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

    # ---- L3：任一节点熔断，或景点全空（无坐标编排）-> 经典路线库 ----
    if state.get("circuit") or not pois:
        itineraries, known = load_classic_itineraries(city, days)
        # 天气是 weather_agent 已获取的真实数据，降级时保留附加（不编造）
        for i, it in enumerate(itineraries):
            if i < len(weathers):
                it.weather = weathers[i]
        logger.warning("aggregate_classic_L3", city=city, known=known, circuit=bool(state.get("circuit")))
        return {
            "itineraries": itineraries,
            "aggregated": True,
            "degraded_level": DegradedLevel.L3_CIRCUIT,
            "warnings": [
                "已切换本地经典路线库（真实核验数据）"
                if known
                else "当前城市暂无经典路线库，使用通用模板（核心商圈自由探索）"
            ],
        }

    warnings: list[str] = []
    degraded = DegradedLevel.NONE

    # L1 痕迹：部分真实数据缺失（工具层已吞掉异常）
    if not weathers or weathers[0].condition == "unavailable":
        degraded = max(degraded, DegradedLevel.L1_API)
        warnings.append("气象数据不可用，已置为 unavailable")
    if not hotels:
        degraded = max(degraded, DegradedLevel.L1_API)
        warnings.append("食宿检索无结果")

    # L2：先尝试 LLM 编排，多次失败再贪心兜底
    groups = await arrange_pois_by_llm(city, days, preferences, pois)
    if groups is None:
        groups = greedy_plan(center, pois, days)
        degraded = max(degraded, DegradedLevel.L2_FILTER)
        warnings.append("LLM 路线编排多次失败，已切换距离贪心算法")

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
