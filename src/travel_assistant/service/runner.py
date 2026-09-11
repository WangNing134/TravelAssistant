"""行程规划统一入口：执行 LangGraph，并在最外层兜住一切未知异常（L4）。"""

from __future__ import annotations

import uuid

from travel_assistant.domain.models import DegradedLevel, PlanMeta, TripPlan
from travel_assistant.fallback.degrader import build_l4_message
from travel_assistant.graph.builder import build_graph
from travel_assistant.observability.logging import get_logger
from travel_assistant.service.result import build_trip_plan

logger = get_logger(__name__)


async def run_plan(query: str, trace_id: str | None = None) -> TripPlan:
    trace_id = trace_id or str(uuid.uuid4())
    try:
        result = await build_graph().ainvoke({"query": query, "trace_id": trace_id})
        return build_trip_plan(result)
    except Exception:
        # L4：任何未在图内消化的 Panic 都不允许穿透到调用方
        logger.exception("unhandled_panic_L4", trace_id=trace_id)
        message = build_l4_message(None)
        return TripPlan(
            city="",
            days=0,
            itineraries=[],
            meta=PlanMeta(
                trace_id=trace_id,
                degraded_level=DegradedLevel.L4_GLOBAL,
                warnings=["服务内部异常，已触发全局兜底"],
                source="fallback",
                note=message,
            ),
            message=message,
        )
