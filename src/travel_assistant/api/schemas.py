"""HTTP 请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from travel_assistant.domain.models import TripPlan


class PlanRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="自然语言旅游诉求")


class PlanResponse(TripPlan):
    """直接复用领域 TripPlan 作为响应体（FastAPI 自动生成 OpenAPI 文档）。"""
