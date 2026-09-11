"""周边搜索：以核心 POI 经纬度为中心，就近检索酒店(100000)/餐饮(050000)。

distance 直接采用高德响应字段（米），结果按距离升序。
"""

from __future__ import annotations

from travel_assistant.domain.models import Hotel
from travel_assistant.observability.logging import get_logger
from travel_assistant.tools.amap_client import get_amap_client

logger = get_logger(__name__)

HOTEL_TYPE = "100000"
RESTAURANT_TYPE = "050000"


def _parse_hotel(item: dict, kind: str) -> Hotel | None:
    location = item.get("location") or ""
    try:
        lng_str, lat_str = location.split(",")
        lng, lat = float(lng_str), float(lat_str)
    except (ValueError, AttributeError):
        return None

    try:
        distance = int(item.get("distance")) if item.get("distance") not in (None, "") else None
    except (ValueError, TypeError):
        distance = None

    return Hotel(
        name=str(item.get("name") or "").strip(),
        adcode=str(item.get("adcode") or ""),
        lng=lng,
        lat=lat,
        address=str(item.get("address") or ""),
        distance=distance,
        kind=kind,
    )


async def _around(
    lng: float,
    lat: float,
    types: str,
    kind: str,
    limit: int,
    radius: int,
) -> list[Hotel]:
    data = await get_amap_client().get_json(
        "/place/around",
        {
            "location": f"{lng},{lat}",
            "types": types,
            "radius": str(radius),
            "sortrule": "distance",
            "offset": str(limit),
            "page": "1",
            "extensions": "base",
        },
    )
    parsed = [h for item in (data.get("pois") or []) if (h := _parse_hotel(item, kind))]
    valid = [h for h in parsed if h.name]
    # 高德 sortrule 偶发不严格生效，客户端按距离兜底排序（None 排最后）
    valid.sort(key=lambda h: h.distance if h.distance is not None else 10**9)
    return valid


async def search_hotels(
    lng: float, lat: float, limit: int = 5, radius: int = 5000
) -> list[Hotel]:
    hotels = await _around(lng, lat, HOTEL_TYPE, "hotel", limit, radius)
    logger.info("hotel_search_done", count=len(hotels))
    return hotels


async def search_restaurants(
    lng: float, lat: float, limit: int = 6, radius: int = 3000
) -> list[Hotel]:
    restaurants = await _around(lng, lat, RESTAURANT_TYPE, "restaurant", limit, radius)
    logger.info("restaurant_search_done", count=len(restaurants))
    return restaurants
