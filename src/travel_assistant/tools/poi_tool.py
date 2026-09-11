"""景点关键字搜索：城市 + 偏好 -> 真实 POI 经纬度列表（仅取高德数据）。"""

from __future__ import annotations

import asyncio

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

# 同一景区内部子点位配额：如“小熊猫产房/熊猫别墅/大熊猫1号别墅”挤掉城市名片
# 大型园区（熊猫基地/古镇）内部场馆跨度可达 0.8km，半径取 0.8 覆盖
SAME_SITE_RADIUS_KM = 0.8
SAME_SITE_QUOTA = 2

# 高德 110000 类型下混入的商业体脏数据，名称命中即丢弃
JUNK_NAME_TERMS = ("电器", "安防", "商厦", "建材", "家具", "批发", "五金", "汽配", "购物广场")


def _is_junk_name(name: str) -> bool:
    return any(term in name for term in JUNK_NAME_TERMS)


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
    return _cap_same_site(_dedupe(merged))[:target]


def _is_same_site(a: POI, b: POI) -> bool:
    """判定为同一景区：物理上紧邻，或名称存在包含关系（如景区与其子场馆）。"""
    if haversine_km(a, b) <= SAME_SITE_RADIUS_KM:
        return True
    na, nb = a.name, b.name
    return len(na) >= 4 and len(nb) >= 4 and (na in nb or nb in na)


def _cap_same_site(pois: list[POI]) -> list[POI]:
    """同一景区最多保留 SAME_SITE_QUOTA 个点，被挤掉的名额由后续不同景区回填。"""
    clusters: list[list[POI]] = []
    kept: list[POI] = []
    dropped: list[str] = []
    for p in pois:
        for cluster in clusters:
            if any(_is_same_site(p, q) for q in cluster):
                if len(cluster) < SAME_SITE_QUOTA:
                    cluster.append(p)
                    kept.append(p)
                else:
                    dropped.append(p.name)
                break
        else:
            clusters.append([p])
            kept.append(p)
    if dropped:
        logger.info("poi_same_site_capped", dropped=dropped, quota=SAME_SITE_QUOTA)
    return kept


async def _seed_search(
    names: list[str], adcode: str, center: Location | None, city: str
) -> list[POI]:
    """城市名片逐个 geocode 定位（place/text 权重排序会淹没精确匹配）。

    geocode 强制城市限定 + 归属/距离核验，坐标全部来自高德；串行节流规避 QPS 限制。
    """
    from travel_assistant.tools.geocode_tool import geocode_place_in_city

    result: list[POI] = []
    for i, name in enumerate(names):
        if i:
            await asyncio.sleep(0.25)  # 个人 Key QPS 节流
        loc = await geocode_place_in_city(name, adcode, center=center, city=city)
        if loc is not None:
            result.append(
                POI(
                    name=name,
                    adcode=adcode,
                    lng=loc.lng,
                    lat=loc.lat,
                    poi_id="",
                    address="",
                    type_code="",
                    duration=2.0,
                    price=None,
                )
            )
    return result


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
    parsed = [
        p
        for item in (data.get("pois") or [])
        if (p := _parse_poi(item)) and not _is_junk_name(p.name)
    ]
    return parsed


async def search_attractions(
    adcode: str,
    preferences: list[str],
    days: int,
    center: Location | None = None,
    limit: int | None = None,
    city: str | None = None,
) -> list[POI]:
    """偏好检索优先，同时合并城市热门景点保证覆盖；去重后截取。任何失败返回 []。

    热门候选三路融合（解决高德空关键字按 adcode 全市排序、市区名片被远郊县淹没）：
    1. 已核验经典景点名种子词（本城城市名片，最可靠）；
    2. 精准类型热词（古镇/博物馆/寺等）；
    3. 空关键字泛检索（兜底补充）。
    """
    from travel_assistant.fallback.classic import classic_seed_names

    target = limit or min(max(days * 4, 8), 16)

    keyword_str = "|".join(k.strip() for k in preferences if k.strip())

    preferred: list[POI] = []
    if keyword_str:
        preferred = await _text_search(adcode, keyword_str, target)

    # 路 1：已核验城市名片种子（种子仅为检索词，坐标全部来自高德 geocode）
    seed_names = classic_seed_names(city) if city else []
    seeded = (
        await _seed_search(seed_names, adcode, center, city) if seed_names and center else []
    )

    # 路 2/3：精准热度词 + 泛热门（城市名片常不含精准词，如“宽窄巷子”）
    keyworded = await _text_search(adcode, POPULAR_KEYWORDS, target)
    generic = await _text_search(adcode, "", target)
    popular = _dedupe(seeded + keyworded + generic)

    if center is not None:
        before = len(preferred) + len(popular)
        preferred = [p for p in preferred if haversine_km(center, p) <= CITY_GEOFENCE_KM]
        popular = [p for p in popular if haversine_km(center, p) <= CITY_GEOFENCE_KM]
        logger.info("poi_geofence", radius_km=CITY_GEOFENCE_KM, dropped=before - len(preferred) - len(popular))

    pois = (
        _interleave(preferred, popular, target)
        if preferred
        else _cap_same_site(_dedupe(popular))[:target]
    )
    logger.info(
        "poi_search_done",
        adcode=adcode,
        preferred=len(preferred),
        popular=len(popular),
        count=len(pois),
    )
    return pois
