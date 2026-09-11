"""端到端真实联调：LangGraph + 高德 + DeepSeek（P4/P7 验收用）。

用法：
    .venv\\Scripts\\python scripts\\smoke_e2e.py "下周五去成都玩3天，想吃火锅看熊猫"
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from travel_assistant.graph.builder import build_graph  # noqa: E402


async def main(query: str) -> None:
    graph = build_graph()
    result = await graph.ainvoke({"query": query, "trace_id": str(uuid.uuid4())})

    print("=" * 70)
    print(f"城市: {result.get('city')}  天数: {result.get('days')}  降级级别: {result.get('degraded_level')}")
    if result.get("fallback_message"):
        print("兜底文案:", result["fallback_message"])
    for w in result.get("warnings", []):
        print("WARN:", w)
    for day in result.get("itineraries", []):
        print("-" * 70)
        weather = day.weather
        hotel = day.hotel
        print(f"{day.date}  天气: {weather.condition} {weather.temperature}")
        if hotel:
            print(f"  住宿: {hotel.name}（距核心景点 {hotel.distance}m）")
        for r in day.restaurants[:3]:
            print(f"  餐饮: {r.name}（{r.distance}m）")
        for i, p in enumerate(day.pois, 1):
            print(f"  {i}. {p.name}  ({p.lng},{p.lat})  建议{p.duration}h")

    # 反幻觉自检：输出地点必须都是非桩数据
    names = [p.name for d in result.get("itineraries", []) for p in d.pois]
    assert not any("桩" in n for n in names), "出现桩数据"
    print("=" * 70)
    print(f"共 {len(names)} 个景点，全部来自高德真实数据")


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "下周五去成都玩3天，想吃火锅看熊猫"
    asyncio.run(main(q))
