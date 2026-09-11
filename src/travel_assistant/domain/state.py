"""LangGraph 全局状态（AgentState）。

非对称 DAG 中：
- weather_agent 与 poi_agent 在同一 superstep 并行，写不同字段，无冲突；
- 多个节点都可能追加 warnings / 抬升 degraded_level，因此这些字段
  必须声明 reducer（warnings 累加、degraded_level 取最大值、circuit 取 OR）。
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from travel_assistant.domain.models import Hotel, Itinerary, Location, POI, Weather


def merge_warnings(left: list[str] | None, right: list[str] | None) -> list[str]:
    return (left or []) + (right or [])


def max_level(left: int | None, right: int | None) -> int:
    return max(left or 0, right or 0)


def merge_circuit(left: bool | None, right: bool | None) -> bool:
    # fan-out 节点同 superstep 同时熔断时会并发写 circuit，必须可合并
    return bool(left) or bool(right)


class AgentState(TypedDict, total=False):
    # 输入与追踪
    query: str
    trace_id: str

    # Supervisor 提取结果
    city: str
    adcode: str
    days: int
    preferences: list[str]
    center: Location

    # 三个子 Agent 产出（全部可溯源至高德）
    weathers: list[Weather]
    pois: list[POI]
    hotels: list[Hotel]
    restaurants: list[Hotel]

    # 聚合结果
    itineraries: list[Itinerary]
    # barrier 守卫：聚合节点被多入边多次调度时，保证真实编排只执行一次
    aggregated: bool

    # 容错
    fatal: bool
    circuit: Annotated[bool, merge_circuit]
    degraded_level: Annotated[int, max_level]
    fallback_message: str

    # 多节点共享字段（reducer）
    warnings: Annotated[list[str], merge_warnings]
