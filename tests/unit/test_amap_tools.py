"""P1 验收：高德工具解析 + L1 五级故障路径（超时/限流/非200/脏JSON/空结果）。"""

import httpx
import pytest
import respx

from travel_assistant.domain.models import POI
from travel_assistant.tools.amap_client import get_amap_client
from travel_assistant.tools.around_tool import search_hotels
from travel_assistant.tools.geocode_tool import geocode_city
from travel_assistant.tools.poi_tool import _interleave, search_attractions
from travel_assistant.tools.weather_tool import get_daily_weather


def test_interleave_preferred_does_not_monopolize():
    def p(name):
        return POI(name=name, lng=1.0, lat=1.0)

    preferred = [p(f"偏好{i}") for i in range(12)]
    popular = [p(f"热门{i}") for i in range(12)]
    merged = _interleave(preferred, popular, target=12)
    assert len(merged) == 12
    # 前两名必须交替，偏好优先；热门至少占 1/3 名额
    assert [x.name for x in merged[:2]] == ["偏好0", "热门0"]
    assert sum(1 for x in merged if x.name.startswith("热门")) >= 4

BASE = "https://restapi.amap.com/v3"


# ---------- 正常解析路径 ----------

@respx.mock
async def test_geocode_success(amap_fixture):
    respx.get(f"{BASE}/geocode/geo").mock(
        return_value=httpx.Response(200, json=amap_fixture("geocode_chengdu.json"))
    )
    loc = await geocode_city("成都")
    assert loc is not None
    assert loc.adcode == "510100"
    assert loc.lng == 104.066301


@respx.mock
async def test_weather_success_and_padding(amap_fixture):
    respx.get(f"{BASE}/weather/weatherInfo").mock(
        return_value=httpx.Response(200, json=amap_fixture("weather_chengdu.json"))
    )
    weather = await get_daily_weather("510100", days=7)
    assert len(weather) == 7
    assert weather[0].condition != "unavailable"
    # 高德预报约 4 天，超出部分必须标记 unavailable，严禁编造
    assert all(w.condition == "unavailable" for w in weather[4:])


@respx.mock
async def test_poi_search_parses_and_dedupes(amap_fixture):
    respx.get(f"{BASE}/place/text").mock(
        return_value=httpx.Response(200, json=amap_fixture("poi_text_chengdu.json"))
    )
    pois = await search_attractions("510100", [], days=3)
    assert len(pois) > 0
    assert all(p.lng and p.lat for p in pois)
    # 默认时长采用保守值，票价无真实来源必须为 None
    assert all(p.price is None for p in pois)
    ids = [p.poi_id for p in pois]
    assert len(ids) == len(set(ids))


@respx.mock
async def test_around_hotels_have_distance(amap_fixture):
    respx.get(f"{BASE}/place/around").mock(
        return_value=httpx.Response(200, json=amap_fixture("around_hotel_chengdu.json"))
    )
    hotels = await search_hotels(104.053307, 30.663869, limit=5)
    assert hotels
    assert all(h.kind == "hotel" and h.distance is not None for h in hotels)
    assert [h.distance for h in hotels] == sorted(h.distance for h in hotels)


# ---------- L1 防御：任何失败返回空集合 / None，绝不抛穿 ----------

@respx.mock
async def test_l1_timeout_returns_empty():
    respx.get(f"{BASE}/geocode/geo").mock(side_effect=httpx.ConnectTimeout("timeout"))
    assert await geocode_city("成都") is None


@respx.mock
async def test_l1_rate_limit_status_zero():
    # 高德限流/Key 异常时 status=0（如 infocode 10004/10021）
    respx.get(f"{BASE}/weather/weatherInfo").mock(
        return_value=httpx.Response(200, json={"status": "0", "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT", "infocode": "10021"})
    )
    weather = await get_daily_weather("510100", days=2)
    assert all(w.condition == "unavailable" for w in weather)


@respx.mock
async def test_l1_http_500():
    respx.get(f"{BASE}/place/text").mock(return_value=httpx.Response(500))
    assert await search_attractions("510100", [], days=2) == []


@respx.mock
async def test_l1_malformed_json():
    respx.get(f"{BASE}/place/around").mock(
        return_value=httpx.Response(200, text="<html>oops</html>")
    )
    assert await search_hotels(104.0, 30.0) == []


@respx.mock
async def test_l1_empty_pois_is_safe():
    respx.get(f"{BASE}/geocode/geo").mock(
        return_value=httpx.Response(
            200, json={"status": "1", "geocodes": [{"name": "x", "location": "garbage"}]}
        )
    )
    # 坐标损坏 -> None，而不是抛异常
    assert await geocode_city("不存在的奇怪地名xyz") is None
