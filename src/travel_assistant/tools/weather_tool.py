"""天气：adcode -> 逐日天气预报。

高德预报通常仅覆盖未来约 4 天；超出部分置 unavailable，严禁编造。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from travel_assistant.domain.models import Weather
from travel_assistant.observability.logging import get_logger
from travel_assistant.tools.amap_client import get_amap_client

logger = get_logger(__name__)


async def get_daily_weather(adcode: str, days: int) -> list[Weather]:
    """返回长度恰为 days 的逐日天气；API 失败或不足天数用 unavailable 补齐。"""
    data = await get_amap_client().get_json(
        "/weather/weatherInfo", {"city": adcode, "extensions": "all"}
    )

    casts: list[dict] = []
    try:
        casts = data["forecasts"][0]["casts"]
    except (KeyError, IndexError, TypeError):
        logger.warning("weather_unavailable_L1", adcode=adcode, days=days)

    base_date = date.today()
    if casts:
        try:
            base_date = datetime.strptime(casts[0]["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError, TypeError):
            pass

    result: list[Weather] = []
    for i in range(days):
        day = (base_date + timedelta(days=i)).isoformat()
        if i < len(casts):
            c = casts[i]
            result.append(
                Weather(
                    date=day,
                    condition=str(c.get("dayweather") or "unknown"),
                    temperature=f'{c.get("nighttemp", "?")}~{c.get("daytemp", "?")}℃',
                )
            )
        else:
            # 超过高德预报窗口：标记不可用，绝不编造
            result.append(Weather.unavailable(day))
    return result
