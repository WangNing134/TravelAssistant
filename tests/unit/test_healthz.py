"""P0 验收：/healthz 可启动、可响应。"""

import httpx

from travel_assistant.main import app


async def test_healthz():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["amap_key_configured"] is True
    assert body["llm_key_configured"] is True
