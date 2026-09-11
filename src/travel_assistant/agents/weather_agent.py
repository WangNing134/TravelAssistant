"""WeatherAgent（气象专员）：只接收城市/adcode，调用高德天气 API 输出逐日天气。"""

from __future__ import annotations

from travel_assistant.agents.common import trace_node
from travel_assistant.tools.weather_tool import get_daily_weather


@trace_node("weather_agent")
async def weather_agent(state: dict) -> dict:
    adcode = state.get("adcode", "")
    days = state.get("days", 1)
    weathers = await get_daily_weather(adcode, days)
    return {"weathers": weathers}
