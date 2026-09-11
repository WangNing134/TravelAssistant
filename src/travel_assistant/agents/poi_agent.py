"""POIAgent（景点专员）：城市 + 偏好 -> 高德关键字搜索 -> 真实 POI 经纬度列表。"""

from __future__ import annotations

from travel_assistant.agents.common import circuit_breaker, trace_node
from travel_assistant.tools.poi_tool import search_attractions


@trace_node("poi_agent")
@circuit_breaker("poi_agent", {"pois": []}, timeout_attr="poi_node_timeout")
async def poi_agent(state: dict) -> dict:
    adcode = state.get("adcode", "")
    days = state.get("days", 1)
    preferences = state.get("preferences", [])
    pois = await search_attractions(
        adcode, preferences, days, center=state.get("center"), city=state.get("city")
    )
    return {"pois": pois}
