"""录制高德真实响应到 tests/fixtures/amap（响应本身不含 Key，可安全用于测试）。

用法（项目根目录）：
    .venv\\Scripts\\python scripts\\record_fixtures.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from travel_assistant.tools.amap_client import get_amap_client  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "amap"


async def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    client = get_amap_client()

    calls = {
        "geocode_chengdu.json": (
            "/geocode/geo",
            {"address": "成都"},
        ),
        "weather_chengdu.json": (
            "/weather/weatherInfo",
            {"city": "510100", "extensions": "all"},
        ),
        "poi_text_chengdu.json": (
            "/place/text",
            {
                "types": "110000",
                "city": "510100",
                "citylimit": "true",
                "offset": "12",
                "page": "1",
                "extensions": "base",
            },
        ),
        "around_hotel_chengdu.json": (
            "/place/around",
            {
                "location": "104.053307,30.663869",
                "types": "100000",
                "radius": "5000",
                "sortrule": "distance",
                "offset": "5",
                "page": "1",
                "extensions": "base",
            },
        ),
        "around_restaurant_chengdu.json": (
            "/place/around",
            {
                "location": "104.053307,30.663869",
                "types": "050000",
                "radius": "3000",
                "sortrule": "distance",
                "offset": "6",
                "page": "1",
                "extensions": "base",
            },
        ),
    }

    for filename, (path, params) in calls.items():
        data = await client.get_json(path, params)
        out = FIXTURE_DIR / filename
        out.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"saved {filename} (status={data.get('status')})")

    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
