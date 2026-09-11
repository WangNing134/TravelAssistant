"""POI 天气过滤节点（barrier）。

等待 weather_agent 与 poi_agent 双路就绪后：
- 若天气良好，直接放行；
- 若有坏天气日，调 LLM 分类景点室内外，移除纯户外景点。
"""

from __future__ import annotations

from travel_assistant.agents.common import circuit_breaker, trace_node
from travel_assistant.observability.logging import get_logger
from travel_assistant.llm.poi_filter import filter_outdoor_pois
from travel_assistant.tools.weather_tool import is_bad_weather

logger = get_logger(__name__)


@trace_node("poi_filter")
@circuit_breaker("poi_filter", {"poi_filtered": True})
async def poi_filter(state: dict) -> dict:
    # barrier 就绪门：多入边会多次调度本节点，双路到齐且只执行一次
    if state.get("poi_filtered"):
        return {}
    if "weathers" not in state or "pois" not in state:
        return {}

    pois = state.get("pois", [])
    weathers = state.get("weathers", [])

    # 无景点或天气不可用，直接放行
    if not pois or not weathers:
        logger.info("poi_filter_skip", reason="no_pois_or_weather")
        return {"poi_filtered": True}

    # 判断是否有坏天气日
    bad_days = [w for w in weathers if is_bad_weather(w.condition)]
    if not bad_days:
        logger.info("poi_filter_skip", reason="weather_ok")
        return {"poi_filtered": True}

    logger.info("poi_filter_bad_weather", bad_days=len(bad_days), total_pois=len(pois))

    # LLM 分类室内外，移除纯户外景点
    filtered = await filter_outdoor_pois(pois)
    return {"pois": filtered, "poi_filtered": True}
