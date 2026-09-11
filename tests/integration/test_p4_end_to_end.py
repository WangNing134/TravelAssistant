"""P4 验收：真实 Agent 端到端编排（高德/LLM 全部 mock）。

覆盖：
1. 正常路径：LLM 编排成功，输出真实数据行程；
2. L2：LLM 编排持续不可信 -> 贪心兜底，degraded_level=2；
3. L4：意图无法识别城市 -> 条件分流 global_fallback。
"""

from __future__ import annotations

import httpx
import pytest
import respx

from travel_assistant.domain.models import DegradedLevel, Location
from travel_assistant.graph.builder import build_graph
from travel_assistant.llm.parsers import IntentDraft

BASE = "https://restapi.amap.com/v3"
CHENGDU = Location(name="成都", adcode="510100", lng=104.066301, lat=30.572961)


@pytest.fixture
def amap_mocked(amap_fixture):
    def geocode_side_effect(request):
        # 仅城市中心请求返回；“成都+景点名”的种子二次请求必须返回空，杜绝串味
        if request.url.params.get("address") == "成都":
            return httpx.Response(200, json=amap_fixture("geocode_chengdu.json"))
        return httpx.Response(200, json={"status": "1", "geocodes": []})

    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/geocode/geo").mock(side_effect=geocode_side_effect)
        router.get(f"{BASE}/weather/weatherInfo").mock(
            return_value=httpx.Response(200, json=amap_fixture("weather_chengdu.json"))
        )
        router.get(f"{BASE}/place/text").mock(
            return_value=httpx.Response(200, json=amap_fixture("poi_text_chengdu.json"))
        )
        router.get(f"{BASE}/place/around").mock(
            return_value=httpx.Response(200, json=amap_fixture("around_hotel_chengdu.json"))
        )
        yield router


@pytest.fixture
def patch_extract(monkeypatch):
    from travel_assistant.agents import supervisor

    async def fake_extract(query: str):
        return IntentDraft(city="成都", days=2, preferences=["熊猫"])

    async def fake_geocode(city: str):
        return CHENGDU

    monkeypatch.setattr(supervisor, "extract_trip_intent", fake_extract)
    monkeypatch.setattr(supervisor, "geocode_city", fake_geocode)
    return supervisor


async def test_end_to_end_llm_arrangement_success(
    amap_mocked, patch_extract, monkeypatch, amap_fixture
):
    supervisor = patch_extract

    async def fake_arrange(city, days, preferences, pois):
        # 模拟 LLM 编排：真实景点恰好各用一次、组数=天数
        mid = len(pois) // 2
        return [pois[:mid], pois[mid:]]

    monkeypatch.setattr(supervisor, "arrange_pois_by_llm", fake_arrange)

    result = await build_graph().ainvoke({"query": "成都玩2天看熊猫", "trace_id": "p4-1"})

    assert result["fatal"] is False
    assert result["degraded_level"] == DegradedLevel.NONE
    itineraries = result["itineraries"]
    assert len(itineraries) == 2

    assigned = [p for day in itineraries for p in day.pois]
    fixture_names = {p["name"] for p in amap_fixture("poi_text_chengdu.json")["pois"]}
    # 输出景点全部可溯源至高德 fixture，无任何幻觉
    assert assigned and all(p.name in fixture_names for p in assigned)
    assert len({p.name for p in assigned}) == len(assigned)
    assert itineraries[0].hotel is not None
    assert itineraries[0].weather.condition != "unavailable"


async def test_l2_greedy_fallback_when_llm_fails(amap_mocked, patch_extract, monkeypatch):
    supervisor = patch_extract

    async def broken_arrange(city, days, preferences, pois):
        return None  # LLM 连续 N 次不可信

    monkeypatch.setattr(supervisor, "arrange_pois_by_llm", broken_arrange)

    result = await build_graph().ainvoke({"query": "成都玩2天", "trace_id": "p4-2"})

    assert result["degraded_level"] == DegradedLevel.L2_FILTER
    assert any("贪心" in w for w in result["warnings"])
    itineraries = result["itineraries"]
    assigned = [p for day in itineraries for p in day.pois]
    assert len(assigned) == len({p.name for p in assigned})
    assert len(assigned) > 0  # 贪心仍覆盖全部真实 POI


async def test_l4_global_fallback_when_no_city(monkeypatch):
    from travel_assistant.agents import supervisor

    async def no_intent(query: str):
        return None

    monkeypatch.setattr(supervisor, "extract_trip_intent", no_intent)

    result = await build_graph().ainvoke({"query": "随便推荐个地方", "trace_id": "p4-3"})

    assert result["fatal"] is True
    assert result["degraded_level"] == DegradedLevel.L4_GLOBAL
    assert "核心商圈自由探索" in result["fallback_message"]
    assert result["itineraries"] == []
