"""高德 Key 联通性冒烟脚本。

用法（项目根目录）：
    .venv\\Scripts\\python scripts\\smoke_amap.py [城市名，默认成都]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from travel_assistant.config import get_settings  # noqa: E402
from travel_assistant.tools.around_tool import search_hotels, search_restaurants  # noqa: E402
from travel_assistant.tools.geocode_tool import geocode_city  # noqa: E402
from travel_assistant.tools.poi_tool import search_attractions  # noqa: E402
from travel_assistant.tools.weather_tool import get_daily_weather  # noqa: E402


async def main(city: str) -> None:
    settings = get_settings()
    print(f"AMAP_KEY configured: {bool(settings.amap_api_key)}")

    loc = await geocode_city(city)
    print(f"\n[geocode] {city} -> {loc}")
    assert loc is not None, "地理编码失败：检查 Key 与网络"

    weather = await get_daily_weather(loc.adcode, 3)
    print(f"\n[weather] {len(weather)} 天")
    for w in weather:
        print(f"  {w.date} {w.condition} {w.temperature}")

    pois = await search_attractions(loc.adcode, ["熊猫", "博物馆"], 3)
    print(f"\n[poi] {len(pois)} 个景点（前 5）")
    for p in pois[:5]:
        print(f"  {p.name} ({p.lng},{p.lat}) {p.address}")

    hotels = await search_hotels(pois[0].lng, pois[0].lat, limit=3)
    print(f"\n[hotel] 距 {pois[0].name} 最近 3 家")
    for h in hotels:
        print(f"  {h.name} distance={h.distance}m")

    rests = await search_restaurants(pois[0].lng, pois[0].lat, limit=3)
    print(f"\n[restaurant] 附近 3 家")
    for r in rests:
        print(f"  {r.name} distance={r.distance}m")

    assert weather and pois and hotels, "冒烟失败：至少一类真实数据为空"
    print("\nSMOKE OK")


if __name__ == "__main__":
    city_name = sys.argv[1] if len(sys.argv) > 1 else "成都"
    asyncio.run(main(city_name))
