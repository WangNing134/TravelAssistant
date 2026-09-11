"""贪心编排纯函数测试（L2 兜底算法，P3 聚合已使用）。"""

from travel_assistant.domain.models import Location, POI
from travel_assistant.fallback.greedy_planner import (
    greedy_plan,
    haversine_km,
    nearest_neighbor_order,
    split_into_days,
)


def _poi(name: str, lng: float, lat: float, duration: float = 2.0) -> POI:
    return POI(name=name, lng=lng, lat=lat, duration=duration)


def test_haversine_known_distance():
    # 成都中心到约 1 公里外
    d = haversine_km((104.066, 30.573), (104.076, 30.573))
    assert 0.9 < d < 1.1


def test_nearest_neighbor_visits_each_once():
    center = Location(name="c", lng=0.0, lat=0.0)
    pois = [_poi("远", 0.2, 0.0), _poi("近", 0.01, 0.0), _poi("中", 0.1, 0.0)]
    ordered = nearest_neighbor_order(center, pois)
    assert [p.name for p in ordered] == ["近", "中", "远"]


def test_split_groups_count_equals_days_and_covers_all():
    pois = [_poi(f"p{i}", i * 0.01, 0.0) for i in range(9)]
    ordered = nearest_neighbor_order(None, pois)
    groups = split_into_days(ordered, days=3)
    assert len(groups) == 3
    assert sum(len(g) for g in groups) == 9
    assert all(groups)  # 每天都非空


def test_greedy_empty_pois_pads_empty_days():
    groups = greedy_plan(None, [], days=2)
    assert groups == [[], []]


def test_greedy_more_days_than_pois():
    pois = [_poi("only", 1.0, 1.0)]
    groups = greedy_plan(None, pois, days=3)
    assert len(groups) == 3
    assert groups[0][0].name == "only"
    assert groups[1] == [] and groups[2] == []
