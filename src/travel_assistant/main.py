"""FastAPI 应用入口。

启动：uvicorn travel_assistant.main:app --app-dir src --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from travel_assistant import __version__
from travel_assistant.api.middleware import TraceContextMiddleware
from travel_assistant.api.routes import router
from travel_assistant.config import get_settings
from travel_assistant.observability.logging import get_logger, init_logging

settings = get_settings()
init_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("service_starting", version=__version__)
    yield
    from travel_assistant.tools.amap_client import get_amap_client

    await get_amap_client().aclose()
    logger.info("service_stopped")


app = FastAPI(
    title="旅途 TravelAssistant",
    version=__version__,
    description="基于 LangGraph 多智能体编排的端到端旅游规划 API（零地点幻觉 + 4 级降级）",
    lifespan=lifespan,
)
app.add_middleware(TraceContextMiddleware)
app.include_router(router)
