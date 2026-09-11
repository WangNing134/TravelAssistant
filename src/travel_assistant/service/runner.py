"""行程规划统一入口：执行 LangGraph，并在最外层兜住一切未知异常（L4）。"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

from travel_assistant.domain.models import DegradedLevel, PlanMeta, TripPlan
from travel_assistant.fallback.degrader import build_l4_message
from travel_assistant.graph.builder import build_graph
from travel_assistant.observability.logging import get_logger
from travel_assistant.service.result import build_trip_plan

logger = get_logger(__name__)

# 节点中文展示名 + 进度文案模板
_NODE_DISPLAY: dict[str, tuple[str, str]] = {
    "supervisor_extract": ("意图识别", "正在解析您的旅游需求…"),
    "weather_agent": ("天气查询", "正在获取目的地天气…"),
    "poi_agent": ("景点检索", "正在搜索真实景点数据…"),
    "hotel_agent": ("食宿搜索", "正在搜索周边酒店与餐饮…"),
    "supervisor_aggregate": ("行程编排", "正在编排天级行程…"),
    "global_fallback": ("兜底处理", "正在生成兜底方案…"),
}


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


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


async def run_plan_stream(query: str, trace_id: str | None = None) -> AsyncGenerator[str, None]:
    """流式执行行程规划，逐节点产出 SSE 进度，最终输出完整行程 JSON。"""
    trace_id = trace_id or str(uuid.uuid4())
    try:
        graph = build_graph()
        final_state: dict = {}
        async for chunk in graph.astream(
            {"query": query, "trace_id": trace_id}, stream_mode="updates"
        ):
            # chunk 格式: {node_name: state_update_dict}
            if not isinstance(chunk, dict):
                continue
            for node_name, update in chunk.items():
                if not isinstance(update, dict):
                    continue
                final_state.update(update)
                display = _NODE_DISPLAY.get(node_name)
                if display is None:
                    continue
                label, default_msg = display
                # 根据状态内容生成更具体的进度消息
                msg = _node_progress_message(node_name, update, final_state)
                yield _sse({"type": "progress", "node": node_name, "label": label, "message": msg})

        plan = build_trip_plan(final_state)
        yield _sse({"type": "result", "plan": plan.model_dump()})
        yield _sse({"type": "done"})
    except Exception:
        logger.exception("unhandled_panic_L4_stream", trace_id=trace_id)
        message = build_l4_message(None)
        plan = TripPlan(
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
        yield _sse({"type": "result", "plan": plan.model_dump()})
        yield _sse({"type": "done"})


def _node_progress_message(node: str, update: dict, state: dict) -> str:
    """根据节点状态生成更具体的进度文案。"""
    if node == "supervisor_extract":
        city = update.get("city") or state.get("city", "")
        days = update.get("days") or state.get("days", 0)
        if city:
            return f"已识别目的地：{city}，{days}天行程"
        if update.get("fatal"):
            return "无法识别城市，正在生成兜底方案"
        return "正在解析您的旅游需求…"
    if node == "weather_agent":
        weathers = update.get("weathers") or state.get("weathers", [])
        if weathers:
            return f"已获取{len(weathers)}天天气数据"
        return "天气数据获取完成（部分不可用）"
    if node == "poi_agent":
        pois = update.get("pois") or state.get("pois", [])
        if pois:
            return f"已检索到{len(pois)}个真实景点"
        return "景点检索完成（结果为空）"
    if node == "hotel_agent":
        hotels = update.get("hotels") or state.get("hotels", [])
        restaurants = update.get("restaurants") or state.get("restaurants", [])
        parts = []
        if hotels:
            parts.append(f"{len(hotels)}家酒店")
        if restaurants:
            parts.append(f"{len(restaurants)}家餐饮")
        return f"已搜索到{'、'.join(parts)}" if parts else "食宿搜索完成"
    if node == "supervisor_aggregate":
        level = update.get("degraded_level") or state.get("degraded_level", 0)
        itineraries = update.get("itineraries") or state.get("itineraries", [])
        if itineraries:
            level_name = ["全链路真实数据", "含部分降级", "贪心兜底", "经典路线库", "全局兜底"]
            return f"行程编排完成（{level_name[int(level)] if int(level) < 5 else '未知'}）"
        return "行程编排中…"
    if node == "global_fallback":
        return "已生成兜底方案"
    return "处理中…"
