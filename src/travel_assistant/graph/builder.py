"""LangGraph 非对称 DAG 装配（全系统编排拓扑集中于此）。

拓扑（PRD 第 4 节）：

    START
      -> supervisor_extract
      -> fan-out: weather_agent ∥ poi_agent          (同一 superstep 并行)
      -> poi_agent -> hotel_agent                     (串行依赖，weather 不接 hotel)
      -> weather_agent ┐
         hotel_agent  ┴-> supervisor_aggregate       (barrier：两路到齐才执行)
      -> END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

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


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node(NODE_EXTRACT, supervisor_extract)
    graph.add_node(NODE_WEATHER, weather_agent)
    graph.add_node(NODE_POI, poi_agent)
    graph.add_node(NODE_HOTEL, hotel_agent)
    graph.add_node(NODE_AGGREGATE, supervisor_aggregate)

    # 1. START -> Supervisor 提取核心参数
    graph.add_edge(START, NODE_EXTRACT)

    # 2. Fan-out：Weather 与 POI 并行
    graph.add_edge(NODE_EXTRACT, NODE_WEATHER)
    graph.add_edge(NODE_EXTRACT, NODE_POI)

    # 3. Chain：Hotel 必须等 POI 返回核心经纬度
    graph.add_edge(NODE_POI, NODE_HOTEL)

    # 4. Fan-in barrier：Weather 与 Hotel 两路都完成，Supervisor 才聚合
    graph.add_edge(NODE_WEATHER, NODE_AGGREGATE)
    graph.add_edge(NODE_HOTEL, NODE_AGGREGATE)

    graph.add_edge(NODE_AGGREGATE, END)
    return graph.compile()
