"""生成 L3 经典路线库：路线为人工选定的知名景点，坐标全部经高德 geocode 实时核验。

核验规则（防同名异地）：
1. geocode 时强制带 city=adcode 限定；
2. 返回结果 adcode 前 4 位必须等于城市 adcode 前 4 位，且距市中心 <= 45km；
3. 依次尝试候选列表与“城市+景点名”组合，任一通过即采用，否则报错。

产物：src/travel_assistant/fallback/classic_routes.json
用法：.venv\\Scripts\\python scripts\\build_classic_routes.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from travel_assistant.tools.amap_client import get_amap_client  # noqa: E402
from travel_assistant.tools.geocode_tool import geocode_city, geocode_place_in_city  # noqa: E402

# 兵马俑距西安中心约 32km，经典库半径放宽到 45km
MAX_CITY_DISTANCE_KM = 45.0


async def geocode_with_retry(name: str, city: str, city_adcode: str, center, retries: int = 3):
    """串行节流 + 限流重试（规避高德个人 Key QPS 限制）。"""
    for attempt in range(retries):
        await asyncio.sleep(0.35)
        loc = await geocode_place_in_city(
            name,
            city_adcode,
            center=center,
            city=city,
            max_distance_km=MAX_CITY_DISTANCE_KM,
        )
        if loc is not None:
            return loc.lng, loc.lat
        await asyncio.sleep(0.8 * (attempt + 1))
    return None


# 人工维护的城市经典路线（每天一组知名景点名称）
CLASSIC: dict[str, dict] = {
    "成都": {
        "days": [
            ["宽窄巷子", "武侯祠", "锦里古街"],
            ["成都大熊猫繁育研究基地", "春熙路", "太古里"],
        ],
    },
    "杭州": {
        "days": [
            ["断桥残雪", "平湖秋月", "灵隐寺"],
            ["雷峰塔", "河坊街", "吴山广场"],
        ],
    },
    "北京": {
        "days": [
            ["天安门广场", "故宫博物院", "景山公园"],
            ["颐和园", "圆明园", "鸟巢"],
        ],
    },
    "上海": {
        "days": [
            ["外滩", "南京路步行街", "豫园"],
            ["上海博物馆", "陆家嘴", "东方明珠广播电视塔"],
        ],
    },
    "西安": {
        "days": [
            ["秦始皇兵马俑博物馆", "华清宫"],
            ["西安城墙", "回民街", "大雁塔"],
        ],
    },
    "重庆": {
        "days": [
            ["洪崖洞民俗风貌区", "解放碑", "朝天门广场"],
            ["磁器口古镇", "李子坝轻轨站", "长江索道"],
        ],
    },
}


async def main() -> None:
    out: dict = {"cities": {}}
    for city, spec in CLASSIC.items():
        center = await geocode_city(city)
        assert center and center.adcode, f"城市 {city} 地理编码失败"
        days_payload = []
        for day in spec["days"]:
            pois = []
            for name in day:
                loc = await geocode_with_retry(name, city, center.adcode, center)
                assert loc is not None, f"{city} 景点 {name} 城市内核验失败"
                lng, lat = loc
                pois.append(
                    {"name": name, "lng": round(lng, 6), "lat": round(lat, 6), "duration": 2.0}
                )
            days_payload.append(pois)
        out["cities"][city] = {"adcode": center.adcode, "days": days_payload}
        print(f"{city}: {sum(len(d) for d in days_payload)} 个景点坐标已核验")

    target = ROOT / "src" / "travel_assistant" / "fallback" / "classic_routes.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved -> {target}")
    await get_amap_client().aclose()


if __name__ == "__main__":
    asyncio.run(main())
