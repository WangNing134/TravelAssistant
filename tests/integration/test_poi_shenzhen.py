"""真实联调：完整流程测试 POI Agent，从自然语言到景点列表。

模拟 supervisor_extract → poi_agent 的真实链路：
LLM 提取意图 → 高德 geocode 查 adcode → search_attractions 检索景点
"""

import pytest

from travel_assistant.tools.amap_client import get_amap_client
from travel_assistant.tools.geocode_tool import geocode_city
from travel_assistant.tools.poi_tool import search_attractions


@pytest.mark.live
@pytest.mark.asyncio
async def test_poi_full_pipeline_shenzhen():
    """完整链路：自然语言 -> LLM 意图 -> geocode -> POI 检索 -> 真实景点列表。"""

    # 1. LLM 意图提取（与 supervisor_extract 完全一致）
    from travel_assistant.llm.intents import extract_trip_intent
    draft = await extract_trip_intent("在北京市区游玩2天，想去景点和博物馆")
    assert draft is not None, "LLM 意图提取失败"
    assert draft.city, "城市为空"
    print(f"\n  LLM 提取: city={draft.city}  days={draft.days}  preferences={draft.preferences}")

    # 2. 高德 geocode 查 adcode（与 supervisor_extract 完全一致）
    center = await geocode_city(draft.city)
    assert center is not None, f"geocode 失败: {draft.city}"
    print(f"  定位: {center.name}  adcode={center.adcode}  center=({center.lng},{center.lat})")

    # 3. POI 检索（与 poi_agent 完全一致）
    pois = await search_attractions(
        adcode=center.adcode,
        preferences=draft.preferences,
        days=draft.days,
        center=center,
        city=draft.city,
    )
    assert len(pois) > 0, f"应返回景点，实际 {len(pois)}"

    print(f"\n  共返回 {len(pois)} 个景点：")
    for i, p in enumerate(pois, 1):
        print(f"  {i}. {p.name}  ({p.lng},{p.lat})  类型:{p.type_code}  时长:{p.duration}h")

    # 清理
    await get_amap_client().aclose()
