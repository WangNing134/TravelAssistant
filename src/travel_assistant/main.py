"""FastAPI 应用入口。

P0：仅 /healthz；P6 起挂载完整行程规划 API 与 L4 中间件。
启动：uvicorn travel_assistant.main:app --app-dir src --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from travel_assistant import __version__
from travel_assistant.config import get_settings
from travel_assistant.observability.logging import get_logger, init_logging

settings = get_settings()
init_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("service_starting", version=__version__)
    yield
    # P1 起在此关闭 httpx 客户端
    try:
        from travel_assistant.tools.amap_client import get_amap_client

        await get_amap_client().aclose()
    except ImportError:
        pass
    logger.info("service_stopped")


app = FastAPI(title="旅途 TravelAssistant", version=__version__, lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "amap_key_configured": bool(settings.amap_api_key),
        "llm_key_configured": bool(settings.llm_api_key),
    }
