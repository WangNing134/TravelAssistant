"""WeatherAgent（气象专员）：只接收城市/adcode，输出逐日天气。

P3 桩；P4 调用高德天气 API（超预报窗口置 unavailable）。
"""

from __future__ import annotations

import asyncio

from travel_assistant.agents.common import itinerary_dates, trace_node
from travel_assistant.domain.models import Weather


@trace_node("weather_agent")
async def weather_agent(state: dict) -> dict:
    await asyncio.sleep(0.05)  # P3 桩延迟：用于验证并行
    days = state.get("days", 1)
    dates = itinerary_dates(days)
    return {
        "weathers": [
            Weather(date=d, condition="晴(桩)", temperature="18~26℃(桩)") for d in dates
        ]
    }
