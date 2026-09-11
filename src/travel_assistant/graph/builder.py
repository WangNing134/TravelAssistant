"""LangGraph 非对称 DAG 装配（全系统编排拓扑集中于此）。

拓扑（PRD 第 4 节）：

    START
      -> supervisor_extract
          ├─ fatal=true -> global_fallback -> END          （L4 提前分流）
          └─ fan-out: weather_agent ∥ poi_agent            (同一 superstep 并行)
                -> poi_agent -> hotel_agent                (串行依赖)
                -> weather_agent ┐
                   hotel_agent  ┴-> supervisor_aggregate   (barrier + 就绪门)
      -> END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from travel_assistant.agents.fallback_nodes import global_fallback
from travel_assistant.agents.hotel_agent import hotel_agent
from travel_assistant.agents.poi_agent import poi_agent
from travel_assistant.agents.supervisor import supervisor_aggregate, supervisor_extract
from travel_assistant.agents.weather_agent import weather_agent
from travel_assistant.domain.state import AgentState

NODE_EXTRACT = "supervisor_extract"
NODE_WEATHER = "weather_agent"
NODE_POI = "poi_agent"
NODE_HOTEL = "hotel_agent"
NODE_AGGREGATE = "supervisor_aggregate"
NODE_GLOBAL_FALLBACK = "global_fallback"


def _route_after_extract(state: dict) -> list[str]:
    if state.get("fatal"):
        return [NODE_GLOBAL_FALLBACK]
    # fan-out：返回多节点即并行调度
    return [NODE_WEATHER, NODE_POI]


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node(NODE_EXTRACT, supervisor_extract)
    graph.add_node(NODE_WEATHER, weather_agent)
    graph.add_node(NODE_POI, poi_agent)
    graph.add_node(NODE_HOTEL, hotel_agent)
    graph.add_node(NODE_AGGREGATE, supervisor_aggregate)
    graph.add_node(NODE_GLOBAL_FALLBACK, global_fallback)

    graph.add_edge(START, NODE_EXTRACT)

    # 条件路由：致命分流 L4，否则 fan-out
    graph.add_conditional_edges(
        NODE_EXTRACT,
        _route_after_extract,
        [NODE_WEATHER, NODE_POI, NODE_GLOBAL_FALLBACK],
    )

    # Chain：Hotel 必须等 POI
    graph.add_edge(NODE_POI, NODE_HOTEL)

    # Fan-in barrier（就绪门保证聚合只真实执行一次）
    graph.add_edge(NODE_WEATHER, NODE_AGGREGATE)
    graph.add_edge(NODE_HOTEL, NODE_AGGREGATE)

    graph.add_edge(NODE_AGGREGATE, END)
    graph.add_edge(NODE_GLOBAL_FALLBACK, END)
    return graph.compile()
