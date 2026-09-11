"""POIAgent（景点专员）：城市 + 偏好 -> 必去景点经纬度列表。

P3 桩；P4 调用高德关键字搜索。
"""

from __future__ import annotations

import asyncio

from travel_assistant.agents.common import trace_node
from travel_assistant.domain.models import POI


@trace_node("poi_agent")
async def poi_agent(state: dict) -> dict:
    await asyncio.sleep(0.2)  # P3 桩延迟（慢于 weather）：验证 fan-out 与串行依赖
    base = state.get("center")
    lng0 = base.lng if base else 104.06
    lat0 = base.lat if base else 30.57
    return {
        "pois": [
            POI(name=f"桩景点{i}", lng=lng0 + i * 0.01, lat=lat0 + i * 0.01)
            for i in range(4)
        ]
    }
