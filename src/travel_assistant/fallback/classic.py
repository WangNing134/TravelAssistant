"""L3 经典路线库加载（坐标均经高德地理编码核验，手工维护，零幻觉）。

- 已知城市：返回库内真实经典路线，按请求天数截断/循环；
- 未知城市：通用模板（不编造任何点位，仅给出天级框架与商圈自由探索建议）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from travel_assistant.agents.common import itinerary_dates
from travel_assistant.domain.models import Itinerary, POI

_DATA_PATH = Path(__file__).with_name("classic_routes.json")


@lru_cache
def _load_data() -> dict:
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def known_cities() -> list[str]:
    return sorted(_load_data().get("cities", {}).keys())


def classic_seed_names(city: str) -> list[str]:
    """库内该城市全部已核验景点名（用作高德检索种子词，命中后返回的仍是高德真实 POI）。"""
    entry = _load_data().get("cities", {}).get(city)
    if entry is None:
        return []
    names: list[str] = []
    for day in entry.get("days", []):
        for p in day:
            if p["name"] not in names:
                names.append(p["name"])
    return names


def _lib_to_itineraries(days_raw: list[list[dict]], days: int) -> list[Itinerary]:
    dates = itinerary_dates(days)
    result: list[Itinerary] = []
    for i in range(days):
        src = days_raw[i % len(days_raw)] if days_raw else []
        pois = [
            POI(
                name=p["name"],
                lng=float(p["lng"]),
                lat=float(p["lat"]),
                duration=float(p.get("duration", 2.0)),
            )
            for p in src
        ]
        result.append(Itinerary(date=dates[i], pois=pois))  # 天气/酒店不编造
    return result


def load_classic_itineraries(city: str, days: int) -> tuple[list[Itinerary], bool]:
    """返回 (行程列表, 是否命中城市库)。"""
    cities = _load_data().get("cities", {})
    entry = cities.get(city)
    if entry is not None:
        return _lib_to_itineraries(entry["days"], days), True

    # 未知城市通用模板：空点位框架，绝不编造
    dates = itinerary_dates(days)
    return [Itinerary(date=d, pois=[]) for d in dates], False
