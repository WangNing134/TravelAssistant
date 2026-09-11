"""HTTP 中间件：请求级 trace_id、结构化访问日志、L4 最外层异常拦截。"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from travel_assistant.domain.models import DegradedLevel, PlanMeta, TripPlan
from travel_assistant.fallback.degrader import build_l4_message
from travel_assistant.observability.logging import bind_trace, get_logger

logger = get_logger(__name__)


class TraceContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self: "TraceContextMiddleware", request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
        request.state.trace_id = trace_id
        bind_trace(trace_id)
        started = time.monotonic()

        try:
            response = await call_next(request)
        except Exception:
            # L4 最后一道防线：即使业务层遗漏，HTTP 层也绝不 5xx
            logger.exception("http_unhandled_panic_L4", path=request.url.path)
            message = build_l4_message(None)
            fallback = TripPlan(
                city="",
                days=0,
                itineraries=[],
                meta=PlanMeta(
                    trace_id=trace_id,
                    degraded_level=DegradedLevel.L4_GLOBAL,
                    warnings=["HTTP 层捕获未处理异常"],
                    source="fallback",
                    note=message,
                ),
                message=message,
            )
            return JSONResponse(status_code=200, content=fallback.model_dump())

        response.headers["X-Trace-Id"] = trace_id
        logger.info(
            "http_access",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            elapsed_ms=round((time.monotonic() - started) * 1000, 1),
        )
        return response
