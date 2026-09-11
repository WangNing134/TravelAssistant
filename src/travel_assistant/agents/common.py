"""Agent 公共能力：节点追踪日志、节点级超时熔断护栏（L3）、日期工具。"""

from __future__ import annotations

import asyncio
import functools
import time
from datetime import date, timedelta
from typing import Awaitable, Callable

from travel_assistant.config import get_settings
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


def circuit_breaker(
    name: str,
    empty_outputs: dict,
    *,
    aggregate: bool = False,
    timeout_attr: str | None = None,
) -> Callable[[Callable[[dict], Awaitable[dict]]], Callable[[dict], Awaitable[dict]]]:
    """L3 节点级超时熔断装饰器。

    - 业务超时：返回节点空产出 + circuit=True，保证下游 barrier 不因缺键死等；
    - aggregate=True 时超时直接在护栏内构造经典路线（不再依赖后续节点）；
    - timeout_attr：指定该节点在 Settings 中的独立超时字段名（如 poi_node_timeout）。
    """

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(state: dict) -> dict:
            if state.get("circuit") and not aggregate:
                # 上游已熔断：本节点不再做外部调用，直接透传空产出
                logger.warning("node_skipped_circuit", node=name)
                return {**empty_outputs, "circuit": True}

            settings = get_settings()
            if aggregate:
                timeout = settings.aggregate_node_timeout
            elif timeout_attr:
                timeout = getattr(settings, timeout_attr)
            else:
                timeout = settings.node_timeout
            try:
                return await asyncio.wait_for(fn(state), timeout=timeout)
            except asyncio.TimeoutError:
                logger.error("node_timeout_L3_circuit", node=name, timeout=timeout)
                payload = {**empty_outputs, "circuit": True}
                if aggregate:
                    # 延迟导入避免循环依赖
                    from travel_assistant.fallback.classic import load_classic_itineraries

                    itineraries, known = load_classic_itineraries(
                        state.get("city", ""), state.get("days", 1)
                    )
                    # 天气是已获取的真实数据，降级时保留附加（不编造）
                    for i, it in enumerate(itineraries):
                        if i < len(state.get("weathers", [])):
                            it.weather = state["weathers"][i]
                    payload.update(
                        {
                            "itineraries": itineraries,
                            "aggregated": True,
                            "degraded_level": 3,
                            "warnings": [
                                "行程编排节点超时熔断，已切换本地经典路线"
                                if known
                                else "行程编排节点超时熔断，当前城市使用通用模板"
                            ],
                        }
                    )
                else:
                    payload["warnings"] = [f"{name} 节点超时已熔断"]
                return payload

        return wrapper

    return decorator


def itinerary_dates(days: int, start: date | None = None) -> list[str]:
    start = start or date.today()
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]
