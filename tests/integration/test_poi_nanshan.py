"""真实联调：单独测试 POI Agent，查询深圳南山区可游玩景点。"""

import pytest

from travel_assistant.domain.models import Location
from travel_assistant.tools.amap_client import get_amap_client
from travel_assistant.tools.poi_tool import search_attractions

# 深圳南山区 adcode + 中心坐标（高德 geocode 核验过）
NANSHAN = Location(
    name="广东省深圳市南山区",
    adcode="440305",
    lng=113.930478,
    lat=22.533191,
)


@pytest.mark.live
@pytest.mark.asyncio
async def test_poi_search_nanshan_shenzhen():
    """查询深圳南山区景点，验证返回真实 POI 列表。"""

    # 直接调用 POI 检索（模拟 poi_agent 的行为）
    pois = await search_attractions(
        adcode=NANSHAN.adcode,
        preferences=["海边"],
        days=2,
        center=NANSHAN,
        city="深圳",
    )
    assert len(pois) > 0, f"南山区应返回景点，实际 {len(pois)}"

    print(f"\n  共返回 {len(pois)} 个景点：")
    for i, p in enumerate(pois, 1):
        print(f"  {i}. {p.name}  ({p.lng},{p.lat})  类型:{p.type_code}  时长:{p.duration}h")

    # 清理
    await get_amap_client().aclose()
