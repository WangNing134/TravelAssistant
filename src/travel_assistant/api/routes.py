"""HTTP 路由：健康检查 + 行程规划。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from travel_assistant import __version__
from travel_assistant.api.schemas import PlanRequest, PlanResponse
from travel_assistant.config import get_settings
from travel_assistant.service.runner import run_plan

router = APIRouter()


@router.get("/healthz", tags=["system"])
async def healthz() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "amap_key_configured": bool(settings.amap_api_key),
        "llm_key_configured": bool(settings.llm_api_key),
    }


@router.post(
    "/api/v1/trips/plan",
    response_model=PlanResponse,
    tags=["trips"],
    summary="自然语言生成结构化旅游行程",
)
async def plan_trip(payload: PlanRequest, request: Request) -> PlanResponse:
    # 任何业务失败均由 runner/中间件转成合法降级 JSON（HTTP 始终 200）
    return await run_plan(payload.query, trace_id=getattr(request.state, "trace_id", None))
