"""P6 验收：HTTP 接口（成功 / 参数校验 / L4 不 5xx / 中间件兜底 / trace_id）。"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from travel_assistant.domain.models import DegradedLevel, Location
from travel_assistant.llm.parsers import IntentDraft
from travel_assistant.main import app

BASE_AMAP = "https://restapi.amap.com/v3"
CHENGDU = Location(name="成都", adcode="510100", lng=104.066301, lat=30.572961)

FIXTURE_POI_NAMES = {
    p["name"]
    for p in json.loads(
        (Path(__file__).parents[1] / "fixtures" / "amap" / "poi_text_chengdu.json").read_text(
            encoding="utf-8"
        )
    )["pois"]
}


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def patch_graph(monkeypatch, amap_fixture):
    from travel_assistant.agents import supervisor

    async def fake_extract(query):
        return IntentDraft(city="成都", days=2, preferences=["熊猫"])

    async def fake_geocode(city):
        return CHENGDU

    async def working_arrange(city, days, preferences, pois):
        mid = len(pois) // 2
        return [pois[:mid], pois[mid:]]

    monkeypatch.setattr(supervisor, "extract_trip_intent", fake_extract)
    monkeypatch.setattr(supervisor, "geocode_city", fake_geocode)
    monkeypatch.setattr(supervisor, "arrange_pois_by_llm", working_arrange)

    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_AMAP}/weather/weatherInfo").mock(
            return_value=httpx.Response(200, json=amap_fixture("weather_chengdu.json"))
        )
        router.get(f"{BASE_AMAP}/place/text").mock(
            return_value=httpx.Response(200, json=amap_fixture("poi_text_chengdu.json"))
        )
        router.get(f"{BASE_AMAP}/place/around").mock(
            return_value=httpx.Response(200, json=amap_fixture("around_hotel_chengdu.json"))
        )
        yield router


async def test_plan_endpoint_success(client, patch_graph):
    resp = await client.post("/api/v1/trips/plan", json={"query": "成都玩2天看熊猫"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["city"] == "成都"
    assert body["days"] == 2
    assert body["meta"]["degraded_level"] == DegradedLevel.NONE
    assert len(body["itineraries"]) == 2
    # trace_id 贯穿响应头与响应体
    assert resp.headers["X-Trace-Id"] == body["meta"]["trace_id"]
    # 所有输出景点可溯源至高德
    for day in body["itineraries"]:
        for p in day["pois"]:
            assert p["name"] in FIXTURE_POI_NAMES
            assert p["lng"] and p["lat"]


async def test_plan_endpoint_validation_error(client):
    resp = await client.post("/api/v1/trips/plan", json={"query": ""})
    assert resp.status_code == 422  # 空 query 属于调用方参数错误


async def test_plan_endpoint_l4_on_unrecognized_city(client, monkeypatch):
    from travel_assistant.agents import supervisor

    async def no_intent(query):
        return None

    monkeypatch.setattr(supervisor, "extract_trip_intent", no_intent)

    resp = await client.post("/api/v1/trips/plan", json={"query": "随便推荐"})
    assert resp.status_code == 200  # 业务降级保证可用 JSON，不返回 5xx
    body = resp.json()
    assert body["meta"]["degraded_level"] == DegradedLevel.L4_GLOBAL
    assert "核心商圈自由探索" in body["message"]


async def test_http_middleware_catches_panic(client, monkeypatch):
    from travel_assistant.api import routes

    async def boom(query, trace_id=None):
        raise RuntimeError("route 层意外爆炸")

    monkeypatch.setattr(routes, "run_plan", boom)

    resp = await client.post("/api/v1/trips/plan", json={"query": "成都2天"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["degraded_level"] == DegradedLevel.L4_GLOBAL
    assert body["message"]


async def test_custom_trace_id_header(client, patch_graph):
    resp = await client.post(
        "/api/v1/trips/plan",
        json={"query": "成都2天"},
        headers={"X-Trace-Id": "fixed-trace-123"},
    )
    assert resp.status_code == 200
    assert resp.headers["X-Trace-Id"] == "fixed-trace-123"
    assert resp.json()["meta"]["trace_id"] == "fixed-trace-123"
