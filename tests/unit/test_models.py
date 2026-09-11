"""P0 验收：领域模型序列化/默认值/数据契约。"""

from travel_assistant.domain.models import (
    DegradedLevel,
    Hotel,
    Itinerary,
    Location,
    PlanMeta,
    POI,
    TripPlan,
    Weather,
)


def test_location_to_json():
    loc = Location(name="成都", adcode="510100", lng=104.0668, lat=30.5728)
    assert loc.model_dump()["adcode"] == "510100"


def test_poi_inherits_location_and_defaults():
    poi = POI(name="大熊猫繁育研究基地", lng=104.145, lat=30.733)
    assert poi.duration == 2.0
    assert poi.price is None  # 无真实来源禁止编造


def test_hotel_distance():
    h = Hotel(name="某酒店", lng=104.0, lat=30.6, distance=320, kind="hotel")
    assert h.distance == 320 and h.kind == "hotel"


def test_weather_unavailable():
    w = Weather.unavailable("2026-09-15")
    assert w.condition == "unavailable" and w.temperature == "unavailable"


def test_itinerary_defaults_and_nested():
    it = Itinerary(
        date="2026-09-12",
        weather=Weather(date="2026-09-12", condition="晴", temperature="20~28℃"),
        hotel=Hotel(name="酒店", lng=1, lat=1),
        pois=[POI(name="景点", lng=1, lat=1)],
    )
    dumped = it.model_dump()
    assert dumped["restaurants"] == []
    assert dumped["pois"][0]["name"] == "景点"


def test_trip_plan_full_envelope():
    plan = TripPlan(
        city="成都",
        days=1,
        itineraries=[],
        meta=PlanMeta(trace_id="t1", degraded_level=DegradedLevel.NONE),
    )
    import json

    raw = json.loads(plan.model_dump_json())
    assert raw["meta"]["degraded_level"] == 0
    assert raw["message"] is None
