"""地理编码：城市名 -> adcode + 经纬度（校验城市真实存在，防幻觉城市入图）。"""

from __future__ import annotations

from travel_assistant.domain.models import Location
from travel_assistant.fallback.greedy_planner import haversine_km
from travel_assistant.observability.logging import get_logger
from travel_assistant.tools.amap_client import get_amap_client

logger = get_logger(__name__)


async def geocode_city(city: str) -> Location | None:
    """成功返回城市中心点；任何失败返回 None（L1 不抛异常）。"""
    data = await get_amap_client().get_json("/geocode/geo", {"address": city})
    geocodes = data.get("geocodes") or []
    if not geocodes:
        logger.warning("geocode_empty", city=city)
        return None

    item = geocodes[0]
    location = item.get("location") or ""
    try:
        lng_str, lat_str = location.split(",")
        lng, lat = float(lng_str), float(lat_str)
    except (ValueError, AttributeError):
        logger.warning("geocode_bad_location", city=city, raw=location)
        return None

    return Location(
        name=item.get("formatted_address") or city,
        adcode=str(item.get("adcode") or ""),
        lng=lng,
        lat=lat,
    )


async def geocode_place_in_city(
    name: str,
    city_adcode: str,
    center: Location | None = None,
    city: str | None = None,
    max_distance_km: float = 22.0,
) -> Location | None:
    """在指定城市内核验具体地点坐标（防同名异地）。

    geocode 强制带 city 限定；校验省码归属（直辖市 adcode 结构特殊）+ 距市中心距离。
    任何失败返回 None，绝不返回城市外的同名点。
    """
    addresses = [name] + ([f"{city}{name}"] if city else [])
    for address in addresses:
        params = {"address": address, "city": city_adcode}
        data = await get_amap_client().get_json("/geocode/geo", params)
        for item in data.get("geocodes") or []:
            loc = item.get("location") or ""
            try:
                lng, lat = (float(x) for x in loc.split(","))
            except (ValueError, AttributeError):
                continue
            same_province = str(item.get("adcode") or "")[:2] == city_adcode[:2]
            if not same_province:
                continue
            if center is not None and haversine_km(
                center, Location(name=name, adcode="", lng=lng, lat=lat)
            ) > max_distance_km:
                continue
            return Location(name=name, adcode=str(item.get("adcode") or ""), lng=lng, lat=lat)
    return None
