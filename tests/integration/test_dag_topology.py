"""DAG 拓扑结构断言 + 并行 reducer 测试（确定性，不依赖时序）。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from travel_assistant.domain.state import AgentState
from travel_assistant.graph.builder import (
    NODE_AGGREGATE,
    NODE_EXTRACT,
    NODE_GLOBAL_FALLBACK,
    NODE_HOTEL,
    NODE_POI,
    NODE_POI_FILTER,
    NODE_WEATHER,
    build_graph,
)


def test_graph_topology_is_asymmetric_dag():
    builder = build_graph().builder
    edges = set(builder.edges)
    branches = builder.branches[NODE_EXTRACT]

    # START -> extract
    assert (START, NODE_EXTRACT) in edges

    # 条件分支：extract 后可 fan-out 到 weather/poi，致命时分流 global_fallback
    spec = next(iter(branches.values()))
    assert set(spec.ends) == {NODE_WEATHER, NODE_POI, NODE_GLOBAL_FALLBACK}

    # Barrier：poi_filter 等待 weather + poi 双路就绪
    assert (NODE_WEATHER, NODE_POI_FILTER) in edges
    assert (NODE_POI, NODE_POI_FILTER) in edges

    # Chain：Filter -> Hotel（poi_filter 完成后才搜酒店）
    assert (NODE_POI_FILTER, NODE_HOTEL) in edges

    # Weather 不直连 Hotel（天气先经过 filter）
    assert not any(src == NODE_WEATHER and dst == NODE_HOTEL for src, dst in edges)

    # Hotel -> Aggregate（aggregate 上游只有 Hotel 一条边）
    assert (NODE_HOTEL, NODE_AGGREGATE) in edges
    aggregate_sources = {src for src, dst in edges if dst == NODE_AGGREGATE}
    assert aggregate_sources == {NODE_HOTEL}

    # 终止接线
    assert (NODE_AGGREGATE, END) in edges
    assert (NODE_GLOBAL_FALLBACK, END) in edges


async def test_parallel_warnings_reducer_no_overwrite():
    """两个并行节点同时写 warnings，reducer 必须累加而非覆盖。"""
    from langgraph.graph import END as E

    async def node_a(state):
        return {"warnings": ["from-a"]}

    async def node_b(state):
        return {"warnings": ["from-b"]}

    async def node_join(state):
        return {}

    g = StateGraph(AgentState)
    g.add_node("a", node_a)
    g.add_node("b", node_b)
    g.add_node("join", node_join)
    g.add_edge(START, "a")
    g.add_edge(START, "b")
    g.add_edge("a", "join")
    g.add_edge("b", "join")
    g.add_edge("join", E)
    app = g.compile()

    result = await app.ainvoke({})
    assert sorted(result["warnings"]) == ["from-a", "from-b"]
