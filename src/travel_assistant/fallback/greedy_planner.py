"""L2 贪心兜底编排：最近邻排序 + 按游玩时长切天。

不依赖 LLM，只使用真实 POI 的经纬度，保证任何情况下路线仍然合理、零幻觉。
"""

from __future__ import annotations

import math

from travel_assistant.domain.models import Location, POI

# 每天游玩时长预算（小时）
DAILY_HOUR_BUDGET = 8.0


def haversine_km(a: Location | tuple[float, float], b: Location | tuple[float, float]) -> float:
    """两点球面距离（公里）。"""
    lng1, lat1 = (a.lng, a.lat) if isinstance(a, Location) else a
    lng2, lat2 = (b.lng, b.lat) if isinstance(b, Location) else b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def nearest_neighbor_order(center: Location | None, pois: list[POI]) -> list[POI]:
    """从城市中心出发，每一步选择距离当前点最近且未访问的 POI。"""
    if not pois:
        return []
    remaining = list(pois)
    anchor: Location | tuple[float, float] = center or (remaining[0].lng, remaining[0].lat)
    ordered: list[POI] = []
    while remaining:
        nxt = min(remaining, key=lambda p: haversine_km(anchor, p))
        ordered.append(nxt)
        remaining.remove(nxt)
        anchor = nxt
    return ordered


def split_into_days(ordered: list[POI], days: int) -> list[list[POI]]:
    """按时长预算与每日软上限切分；保证返回组数恰为 days（末尾补空）。"""
    if days <= 0:
        return []
    if not ordered:
        return [[] for _ in range(days)]

    cap_per_day = max(2, math.ceil(len(ordered) / days) + 1)
    groups: list[list[POI]] = [[]]
    used_hours = 0.0
    for poi in ordered:
        current = groups[-1]
        need_new_day = (
            current
            and len(groups) < days
            and (used_hours + poi.duration > DAILY_HOUR_BUDGET or len(current) >= cap_per_day)
        )
        if need_new_day:
            groups.append([])
            used_hours = 0.0
        groups[-1].append(poi)
        used_hours += poi.duration

    while len(groups) < days:
        groups.append([])
    return groups


def greedy_plan(center: Location | None, pois: list[POI], days: int) -> list[list[POI]]:
    return split_into_days(nearest_neighbor_order(center, pois), days)
