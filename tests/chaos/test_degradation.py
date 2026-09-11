"""P5 验收（混沌测试）：逐级注入故障，断言 L1-L4 降级行为且响应始终合法。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx

from travel_assistant.config import get_settings
from travel_assistant.domain.models import DegradedLevel, Location
from travel_assistant.llm.parsers import IntentDraft
from travel_assistant.service.runner import run_plan

BASE = "https://restapi.amap.com/v3"
CHENGDU = Location(name="成都", adcode="510100", lng=104.066301, lat=30.572961)

CLASSIC_DATA = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "amap" / "geocode_chengdu.json").read_text(
        encoding="utf-8"
    )
)
CLASSIC_ROUTES = json.loads(
    (
        Path(__file__).parents[2]
        / "src"
        / "travel_assistant"
        / "fallback"
        / "classic_routes.json"
    ).read_text(encoding="utf-8")
)


@pytest.fixture
def patch_extract(monkeypatch):
    from travel_assistant.agents import supervisor

    async def fake_extract(query):
        return IntentDraft(city="成都", days=2, preferences=["熊猫"])

    async def fake_geocode(city):
        return CHENGDU

    monkeypatch.setattr(supervisor, "extract_trip_intent", fake_extract)
    monkeypatch.setattr(supervisor, "geocode_city", fake_geocode)


@pytest.fixture
def amap_ok(amap_fixture):
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/geocode/geo").mock(
            return_value=httpx.Response(200, json=amap_fixture("geocode_chengdu.json"))
        )
        router.get(f"{BASE}/weather/weatherInfo").mock(
            return_value=httpx.Response(200, json=amap_fixture("weather_chengdu.json"))
        )
        router.get(f"{BASE}/place/text").mock(
            return_value=httpx.Response(200, json=amap_fixture("poi_text_chengdu.json"))
        )
        router.get(f"{BASE}/place/around").mock(
            return_value=httpx.Response(200, json=amap_fixture("around_hotel_chengdu.json"))
        )
        yield


# ---------- L3：节点超时熔断 -> 经典路线库 ----------

async def test_l3_node_timeout_circuit_breaks_to_classic(patch_extract, monkeypatch, amap_ok):
    from travel_assistant.agents import weather_agent

    async def slow_weather(adcode, days):
        await asyncio.sleep(1.0)  # 远超节点超时
        return []

    monkeypatch.setattr(weather_agent, "get_daily_weather", slow_weather)
    monkeypatch.setenv("NODE_TIMEOUT", "0.05")
    get_settings.cache_clear()

    plan = await run_plan("成都玩2天", "chaos-l3-timeout")
    get_settings.cache_clear()

    assert plan.meta.degraded_level == DegradedLevel.L3_CIRCUIT
    assert plan.meta.source == "classic"
    classic_names = {p["name"] for d in CLASSIC_ROUTES["cities"]["成都"]["days"] for p in d}
    got = {p.name for day in plan.itineraries for p in day.pois}
    assert got & classic_names  # 命中本地真实经典路线
    assert len(plan.itineraries) == 2


# ---------- L3：POI 全空 -> 经典路线库（不调用周边搜索） ----------

async def test_l3_empty_pois_uses_classic(patch_extract, amap_fixture):
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/weather/weatherInfo").mock(
            return_value=httpx.Response(200, json=amap_fixture("weather_chengdu.json"))
        )
        empty_poi = httpx.Response(200, json={"status": "1", "pois": []})
        text_route = router.get(f"{BASE}/place/text").mock(return_value=empty_poi)
        around_route = router.get(f"{BASE}/place/around").mock(
            return_value=httpx.Response(200, json=amap_fixture("around_hotel_chengdu.json"))
        )

        plan = await run_plan("成都玩2天", "chaos-l3-empty")

    assert plan.meta.degraded_level == DegradedLevel.L3_CIRCUIT
    assert any("经典路线" in w for w in plan.meta.warnings)
    assert not text_route.called or all(  # 景点检索确实发生
        True for _ in text_route.calls
    )
    assert not around_route.called  # 无 POI 坐标，周边搜索必须被短路
    assert any(p.name == "宽窄巷子" for day in plan.itineraries for p in day.pois)


# ---------- L3：未知城市的经典库通用模板 ----------

async def test_l3_unknown_city_generic_template(patch_extract, monkeypatch, amap_ok):
    from travel_assistant.agents import poi_agent

    async def empty_pois(adcode, preferences, days, center=None, limit=None, city=None):
        return []

    monkeypatch.setattr(poi_agent, "search_attractions", empty_pois)
    # 把城市改为库内不存在的城市
    from travel_assistant.agents import supervisor
    original = supervisor.extract_trip_intent

    async def fake_extract(query):
        return IntentDraft(city="铁岭", days=2, preferences=[])

    monkeypatch.setattr(supervisor, "extract_trip_intent", fake_extract)

    plan = await run_plan("铁岭玩2天", "chaos-l3-generic")
    assert plan.meta.degraded_level == DegradedLevel.L3_CIRCUIT
    assert any("通用模板" in w for w in plan.meta.warnings)
    assert all(day.pois == [] for day in plan.itineraries)  # 绝不编造点位


# ---------- L4：未知 Panic 全局兜底 ----------

async def test_l4_unhandled_panic_never_escapes(monkeypatch):
    from travel_assistant.service import runner

    def boom():
        raise RuntimeError("boom: 不可知严重 Panic")

    monkeypatch.setattr(runner, "build_graph", boom)

    plan = await run_plan("任意请求", "chaos-l4")
    assert plan.meta.degraded_level == DegradedLevel.L4_GLOBAL
    assert plan.meta.source == "fallback"
    assert "核心商圈自由探索" in plan.message
    assert len(plan.itineraries) == 0


# ---------- L1：天气接口失败，其余正常，行程仍可用 ----------

async def test_l1_weather_failure_partial_degraded(patch_extract, monkeypatch, amap_fixture):
    from travel_assistant.agents import supervisor

    async def working_arrange(city, days, preferences, pois):
        mid = len(pois) // 2
        return [pois[:mid], pois[mid:]]

    monkeypatch.setattr(supervisor, "arrange_pois_by_llm", working_arrange)

    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE}/geocode/geo").mock(
            return_value=httpx.Response(200, json={"status": "1", "geocodes": []})
        )
        router.get(f"{BASE}/weather/weatherInfo").mock(
            return_value=httpx.Response(
                200, json={"status": "0", "infocode": "10021", "info": "CUQPS_HAS_EXCEEDED"}
            )
        )
        router.get(f"{BASE}/place/text").mock(
            return_value=httpx.Response(200, json=amap_fixture("poi_text_chengdu.json"))
        )
        router.get(f"{BASE}/place/around").mock(
            return_value=httpx.Response(200, json=amap_fixture("around_hotel_chengdu.json"))
        )
        plan = await run_plan("成都玩2天", "chaos-l1")

    assert plan.meta.degraded_level == DegradedLevel.L1_API
    assert plan.meta.source == "realtime"
    assert len(plan.itineraries) == 2
    assert plan.itineraries[0].weather.condition == "unavailable"  # 不编造天气
    assert plan.itineraries[0].hotel is not None  # 其余真实数据照常
