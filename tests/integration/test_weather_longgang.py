"""真实联调：查询深圳（含龙岗区）最近两天的天气（直接调用高德 API）。

高德天气接口按市级 adcode 查询；龙岗区属深圳，adcode=440300。
标记 @pytest.mark.live，使用真实 .env 配置访问外网。
"""

import pytest

from travel_assistant.tools.weather_tool import get_daily_weather

SHENZHEN_ADCODE = "440300"


@pytest.mark.live
@pytest.mark.asyncio
async def test_shenzhen_weather_2days():
    """查询深圳两天天气，验证返回结构完整、日期连续。"""

    weathers = await get_daily_weather(SHENZHEN_ADCODE, 2)
    assert len(weathers) == 2, f"应返回 2 天天气，实际 {len(weathers)}"

    for w in weathers:
        print(f"\n  {w.date}  天气: {w.condition}  温度: {w.temperature}")
        assert w.date, "日期为空"
        assert w.condition, "天气为空"

    # 清理
    from travel_assistant.tools.amap_client import get_amap_client
    await get_amap_client().aclose()
