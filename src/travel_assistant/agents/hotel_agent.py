"""HotelAgent（食宿专员）：必须依赖 POIAgent 结果。

以核心 POI 经纬度为中心，并行调用高德周边搜索检索酒店与餐饮；
POI 为空时直接短路（无坐标可用），由 P5 的 L3 经典路线兜底。
"""

from __future__ import annotations

import asyncio

from travel_assistant.agents.common import trace_node
from travel_assistant.observability.logging import get_logger
from travel_assistant.tools.around_tool import search_hotels, search_restaurants

logger = get_logger(__name__)


@trace_node("hotel_agent")
async def hotel_agent(state: dict) -> dict:
    pois = state.get("pois", [])
    if not pois:
        logger.warning("hotel_skipped_no_poi")
        return {
            "hotels": [],
            "restaurants": [],
            "warnings": ["无核心 POI 坐标，食宿检索跳过"],
        }

    # 以首日首个核心景点为住宿锚点
    core = pois[0]
    hotels, restaurants = await asyncio.gather(
        search_hotels(core.lng, core.lat, limit=5, radius=5000),
        search_restaurants(core.lng, core.lat, limit=6, radius=3000),
    )
    return {"hotels": hotels, "restaurants": restaurants}
