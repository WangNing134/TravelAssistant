"""HotelAgent（食宿专员）：必须依赖 POIAgent 结果，按核心 POI 经纬度周边搜索。

P3 桩；P4 调用高德周边搜索（酒店 100000 / 餐饮 050000）。
"""

from __future__ import annotations

import asyncio

from travel_assistant.agents.common import trace_node
from travel_assistant.domain.models import Hotel


@trace_node("hotel_agent")
async def hotel_agent(state: dict) -> dict:
    pois = state.get("pois", [])
    if not pois:
        return {"hotels": [], "restaurants": [], "warnings": ["无核心 POI 坐标，食宿检索跳过"]}

    await asyncio.sleep(0.15)  # P3 桩延迟：验证其在 poi 之后、aggregate 之前
    core = pois[0]
    return {
        "hotels": [
            Hotel(name="桩酒店", lng=core.lng + 0.001, lat=core.lat, distance=120, kind="hotel")
        ],
        "restaurants": [
            Hotel(name="桩餐厅", lng=core.lng, lat=core.lat + 0.001, distance=60, kind="restaurant")
        ],
    }
