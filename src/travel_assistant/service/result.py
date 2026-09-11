"""把图终态组装为对外 TripPlan 响应契约。"""

from __future__ import annotations

from travel_assistant.domain.models import DegradedLevel, PlanMeta, TripPlan


def build_trip_plan(state: dict) -> TripPlan:
    degraded = int(state.get("degraded_level", DegradedLevel.NONE))
    warnings = list(state.get("warnings", []))

    if degraded == DegradedLevel.L3_CIRCUIT:
        source = "classic"
    elif degraded == DegradedLevel.L4_GLOBAL:
        source = "fallback"
    else:
        source = "realtime"

    meta = PlanMeta(
        trace_id=str(state.get("trace_id", "")),
        degraded_level=degraded,
        warnings=warnings,
        source=source,
        note=state.get("fallback_message") if degraded == DegradedLevel.L4_GLOBAL else None,
    )
    return TripPlan(
        city=state.get("city", "") or "",
        days=int(state.get("days", 0) or 0),
        itineraries=list(state.get("itineraries", [])),
        meta=meta,
        message=state.get("fallback_message") if degraded == DegradedLevel.L4_GLOBAL else None,
    )
