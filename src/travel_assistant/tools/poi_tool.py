"""景点关键字搜索：城市 + 偏好 -> 真实 POI 经纬度列表（仅取高德数据）。"""

from __future__ import annotations

from travel_assistant.domain.models import POI
from travel_assistant.observability.logging import get_logger
from travel_assistant.tools.amap_client import get_amap_client

logger = get_logger(__name__)

# 风景名胜一级类型码
ATTRACTIONS_TYPE = "110000"


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
    adcode: str, preferences: list[str], days: int, limit: int | None = None
) -> list[POI]:
    """偏好检索优先，同时合并城市热门景点保证覆盖；去重后截取。任何失败返回 []。"""
    target = limit or min(max(days * 4, 8), 16)

    keyword_str = "|".join(k.strip() for k in preferences if k.strip())

    preferred: list[POI] = []
    if keyword_str:
        preferred = await _text_search(adcode, keyword_str, target)

    # 热门景点兜底：无偏好时作为主检索；有偏好时补足覆盖面
    popular = await _text_search(adcode, "", target)

    pois = _dedupe(preferred + popular)[:target]
    logger.info(
        "poi_search_done",
        adcode=adcode,
        preferred=len(preferred),
        popular=len(popular),
        count=len(pois),
    )
    return pois
