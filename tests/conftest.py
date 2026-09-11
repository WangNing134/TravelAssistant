"""pytest 全局夹具：隔离真实配置，默认不访问外网。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "amap"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def amap_fixture():
    """测试用例通过该工厂读取录制的高德响应。"""
    return load_fixture


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch, request):
    if request.node.get_closest_marker("live"):
        # 标记 @pytest.mark.live 的用例使用真实 .env 配置访问外网
        yield
        return

    monkeypatch.setenv("AMAP_API_KEY", "test-amap-key")
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.test")
    monkeypatch.setenv("AMAP_CACHE_TTL", "0")

    from travel_assistant.config import get_settings
    from travel_assistant.llm.client import reset_llm_client
    from travel_assistant.tools import amap_client

    get_settings.cache_clear()
    amap_client._singleton = None  # 每个用例使用全新 httpx 客户端
    reset_llm_client()
    yield
    get_settings.cache_clear()
    amap_client._singleton = None
    reset_llm_client()
