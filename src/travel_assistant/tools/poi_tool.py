"""景点关键字搜索：城市 + 偏好 -> 真实 POI 经纬度列表（仅取高德数据）。"""

from __future__ import annotations

from travel_assistant.domain.models import Location, POI
from travel_assistant.fallback.greedy_planner import haversine_km
from travel_assistant.observability.logging import get_logger
from travel_assistant.tools.amap_client import get_amap_client

logger = get_logger(__name__)

# 风景名胜一级类型码
ATTRACTIONS_TYPE = "110000"

# 城市热门景点检索词（空关键字排序不等于热度，且地级市 adcode 含下辖县，需精准词）
POPULAR_KEYWORDS = "风景名胜区|古镇|古街|博物馆|纪念馆|寺"

# 距城市中心超过该半径（公里）的远郊县点位丢弃
CITY_GEOFENCE_KM = 22.0


def _parse_poi(item: dict) -> POI | None:
    location = item.get("location") or ""
    try:
        lng_str, lat_str = location.split(",")
        lng, lat = float(lng_str), float(lat_str)
    except (ValueError, AttributeError):
        return None  # 无坐标的脏数据直接丢弃，不允许进入后续编排

    return POI(
        poi_id=str(item.get("id") or ""),
        name=str(item.get("name") or "").strip(),
        adcode=str(item.get("adcode") or ""),
        lng=lng,
        lat=lat,
        address=str(item.get("address") or ""),
        type_code=str(item.get("typecode") or ""),
        # 高德基础接口不提供时长/票价：保守默认值，聚合时在 warnings 标注
        duration=2.0,
        price=None,
    )


def _dedupe(pois: list[POI]) -> list[POI]:
    seen: set[str] = set()
    result: list[POI] = []
    for p in pois:
        key = p.poi_id or f"{p.name}:{p.lng},{p.lat}"
        if key in seen or not p.name:
            continue
        seen.add(key)
        result.append(p)
    return result


def _interleave(preferred: list[POI], popular: list[POI], target: int) -> list[POI]:
    """偏好与热门交替合并：偏好优先但不垄断，避免同一景区子点位占满全部名额。"""
    merged: list[POI] = []
    for i in range(max(len(preferred), len(popular))):
        if i < len(preferred):
            merged.append(preferred[i])
        if i < len(popular):
            merged.append(popular[i])
        if len(merged) >= target * 2:
            break
    return _dedupe(merged)[:target]


async def _text_search(adcode: str, keywords: str, limit: int) -> list[POI]:
    params: dict[str, str] = {
        "types": ATTRACTIONS_TYPE,
        "city": adcode,
        "citylimit": "true",
        "offset": str(limit),
        "page": "1",
        "extensions": "base",
    }
    if keywords:
        params["keywords"] = keywords
    data = await get_amap_client().get_json("/place/text", params)
    parsed = [p for item in (data.get("pois") or []) if (p := _parse_poi(item))]
    return parsed


async def search_attractions(
    adcode: str,
    preferences: list[str],
    days: int,
    center: Location | None = None,
    limit: int | None = None,
) -> list[POI]:
    """偏好检索优先，同时合并城市热门景点保证覆盖；去重后截取。任何失败返回 []。"""
    target = limit or min(max(days * 4, 8), 16)

    keyword_str = "|".join(k.strip() for k in preferences if k.strip())

    preferred: list[POI] = []
    if keyword_str:
        preferred = await _text_search(adcode, keyword_str, target)

    # 热门景点双路：精准热度词 + 泛热门（城市名片常不含精准词，如“宽窄巷子”）
    keyworded = await _text_search(adcode, POPULAR_KEYWORDS, target)
    generic = await _text_search(adcode, "", target)
    popular = _dedupe(keyworded + generic)

    if center is not None:
        before = len(preferred) + len(popular)
        preferred = [p for p in preferred if haversine_km(center, p) <= CITY_GEOFENCE_KM]
        popular = [p for p in popular if haversine_km(center, p) <= CITY_GEOFENCE_KM]
        logger.info("poi_geofence", radius_km=CITY_GEOFENCE_KM, dropped=before - len(preferred) - len(popular))

    pois = _interleave(preferred, popular, target) if preferred else _dedupe(popular)[:target]
    logger.info(
        "poi_search_done",
        adcode=adcode,
        preferred=len(preferred),
        popular=len(popular),
        count=len(pois),
    )
    return pois
