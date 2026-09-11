"""Agent 公共能力：节点追踪日志、节点级超时护栏（L3）、日期工具。"""

from __future__ import annotations

import asyncio
import functools
import time
from datetime import date, timedelta

from travel_assistant.observability.logging import get_logger

logger = get_logger(__name__)

# 测试用时间线（P3 验证 fan-out / barrier 语义）
NODE_TIMELINE: list[tuple[str, str, float]] = []


def record_run(name: str) -> None:
    """标记节点的真实业务逻辑实际执行（区别于被调度但就绪门跳过）。"""
    NODE_TIMELINE.append(("run", name, time.monotonic()))


def trace_node(name: str):
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(state):
            t0 = time.monotonic()
            NODE_TIMELINE.append(("enter", name, t0))
            logger.info("node_enter", node=name)
            try:
                result = await fn(state)
            except Exception:
                NODE_TIMELINE.append(("error", name, time.monotonic()))
                raise
            NODE_TIMELINE.append(("exit", name, time.monotonic()))
            logger.info(
                "node_exit",
                node=name,
                elapsed_ms=round((time.monotonic() - t0) * 1000, 1),
            )
            return result

        return wrapper

    return decorator


async def guard_node_timeout(name: str, coro, timeout: float) -> tuple[dict | None, bool]:
    """L3 节点级超时熔断。返回 (结果, 是否超时)。"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout), False
    except asyncio.TimeoutError:
        logger.error("node_timeout_L3", node=name, timeout=timeout)
        return None, True


def itinerary_dates(days: int, start: date | None = None) -> list[str]:
    start = start or date.today()
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]
