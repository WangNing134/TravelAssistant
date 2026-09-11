"""地理编码：城市名 -> adcode + 经纬度（校验城市真实存在，防幻觉城市入图）。"""

from __future__ import annotations

from travel_assistant.domain.models import Location
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
