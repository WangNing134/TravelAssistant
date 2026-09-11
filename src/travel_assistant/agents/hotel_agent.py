"""HotelAgent（食宿专员）：依赖 POI 过滤结果。

取前 3 核心景点计算地理均值坐标作为中心点，
高德周边搜索检索酒店(radius=3000/types=010000/sortrule=weight)与餐饮，
再由 LLM 根据用户偏好从 5 家酒店中精选 1 家。
POI 为空或上游熔断时直接短路，由 L3 经典路线兜底。
"""

from __future__ import annotations

import asyncio

from travel_assistant.agents.common import circuit_breaker, trace_node
from travel_assistant.observability.logging import get_logger
from travel_assistant.tools.around_tool import search_hotels, search_restaurants
from travel_assistant.llm.hotel_selection import select_hotel_by_llm

logger = get_logger(__name__)

_EMPTY = {"hotels": [], "restaurants": []}


@trace_node("hotel_agent")
@circuit_breaker("hotel_agent", _EMPTY)
async def hotel_agent(state: dict) -> dict:
    pois = state.get("pois", [])
    preferences = state.get("preferences", [])
    if not pois:
        logger.warning("hotel_skipped_no_poi")
        return {
            "hotels": [],
            "restaurants": [],
            "warnings": ["无核心 POI 坐标，食宿检索跳过"],
        }

    # 1. 取前 3 核心景点（已按权重排序）
    top3 = pois[:3]

    # 2. 计算地理均值坐标
    center_lng = sum(p.lng for p in top3) / len(top3)
    center_lat = sum(p.lat for p in top3) / len(top3)
    logger.info("hotel_center_geometric_mean", top3=[p.name for p in top3], lng=center_lng, lat=center_lat)

    # 3. 高德周边搜索（radius=3000, types=010000, sortrule=weight, top5）
    hotels, restaurants = await asyncio.gather(
        search_hotels(center_lng, center_lat, limit=5, radius=3000),
        search_restaurants(center_lng, center_lat, limit=6, radius=3000),
    )

    # 4. LLM 从 5 家中精选 1 家（按用户偏好）
    if hotels and preferences:
        selected = await select_hotel_by_llm(hotels, preferences)
        if selected:
            hotels = [selected] + [h for h in hotels if h.name != selected.name]
            logger.info("hotel_llm_selected", hotel=selected.name)
        else:
            logger.info("hotel_llm_failed_use_default")
    elif hotels:
        logger.info("hotel_no_preferences_use_default")

    return {"hotels": hotels, "restaurants": restaurants}
