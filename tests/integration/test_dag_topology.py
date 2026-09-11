"""P3 验收：LangGraph 非对称 DAG 拓扑、并行/同步语义、状态聚合、reducer 不覆盖。"""

from __future__ import annotations

import pytest
from langgraph.graph import END, START, StateGraph

from travel_assistant.agents import common
from travel_assistant.domain.state import AgentState
from travel_assistant.graph.builder import build_graph


@pytest.fixture(autouse=True)
def _clear_timeline():
    common.NODE_TIMELINE.clear()
    yield
    common.NODE_TIMELINE.clear()


def _times():
    enter: dict[str, float] = {}
    exit_: dict[str, float] = {}
    runs: dict[str, list[float]] = {}
    for event, node, t in common.NODE_TIMELINE:
        if event == "enter":
            enter[node] = t
        elif event == "exit":
            exit_[node] = t
        elif event == "run":
            runs.setdefault(node, []).append(t)
    return enter, exit_, runs


async def test_dag_runs_and_assembles_stub_plan():
    graph = build_graph()
    result = await graph.ainvoke({"query": "去成都玩2天看熊猫", "trace_id": "p3-test"})

    # ---- 时序拓扑 ----
    enter, exit_, runs = _times()
    order = ["supervisor_extract", "weather_agent", "poi_agent", "hotel_agent", "supervisor_aggregate"]
    for node in order:
        assert node in enter and node in exit_, f"节点 {node} 未执行"

    # fan-out：weather/poi 都在 extract 之后启动（<= 因 Windows monotonic 分辨率 ~15ms）
    assert exit_["supervisor_extract"] <= enter["weather_agent"]
    assert exit_["supervisor_extract"] <= enter["poi_agent"]

    # 并行性证据：poi（桩延迟0.2s）启动时 weather（0.05s）尚未结束 => 同一 superstep 并发
    assert enter["poi_agent"] < exit_["weather_agent"]

    # 串行依赖：hotel 必须在 poi 返回之后
    assert exit_["poi_agent"] <= enter["hotel_agent"]

    # fan-in barrier：aggregate 虽可能被多入边调度多次，但真实编排只执行一次，
    # 且执行时刻必须晚于 weather 与 hotel 两路全部完成
    assert runs.get("supervisor_aggregate") and len(runs["supervisor_aggregate"]) == 1
    run_at = runs["supervisor_aggregate"][0]
    assert exit_["weather_agent"] <= run_at
    assert exit_["hotel_agent"] <= run_at

    # ---- 状态聚合 ----
    assert result["city"] == "成都"
    assert result["days"] == 2
    assert len(result["weathers"]) == 2
    assert len(result["pois"]) == 4
    assert len(result["hotels"]) == 1

    itineraries = result["itineraries"]
    assert len(itineraries) == 2
    assert itineraries[0].weather.condition.startswith("晴")
    assert itineraries[0].hotel is not None and itineraries[0].hotel.name == "桩酒店"
    # 4 个真实 POI 被贪心切分，恰好分配完、无丢失
    assigned = [p for day in itineraries for p in day.pois]
    assert len(assigned) == 4
    assert len({p.name for p in assigned}) == 4
    assert result["aggregated"] is True


async def test_parallel_warnings_reducer_no_overwrite():
    """两个并行节点同时写 warnings，reducer 必须累加而非覆盖。"""

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
    g.add_edge("join", END)
    app = g.compile()

    result = await app.ainvoke({})
    assert sorted(result["warnings"]) == ["from-a", "from-b"]
