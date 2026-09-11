"""高德地图异步 HTTP 客户端 —— 全系统唯一外部数据出入口。

L1（API 防御）在此实现：
HTTP 超时(>5s) / 限流 / 非 200 / 非 JSON / 高德 status!=1，
底层一律捕获并返回空 dict（工具层据此得到 []），绝不向调用方抛异常。

QPS 限流：个人 Key 每秒最多 3 次请求。所有高德调用（geocode/weather/poi/around）
都经过 get_json，限流器在此统一实现，调用方无需各自节流。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from travel_assistant.config import get_settings
from travel_assistant.observability.logging import get_logger

logger = get_logger(__name__)

# 个人 Key QPS 上限
MAX_QPS = 3


class TTLCache:
    """极简内存 TTL 缓存（只缓存高德真实响应，不改变数据来源）。"""

    def __init__(self, ttl_seconds: int) -> None:
        self.ttl = ttl_seconds
        self._store: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        if self.ttl <= 0:
            return None
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        if self.ttl <= 0:
            return
        self._store[key] = (time.monotonic() + self.ttl, value)


class RateLimiter:
    """滑动窗口限流器：确保任意 1 秒窗口内最多 max_qps 次请求。

    用法：在发起 HTTP 请求前 await acquire()，限流器会阻塞到安全时刻再放行。
    请求本身（await httpx.get）不在锁内执行，允许多个请求并行 in-flight。
    """

    def __init__(self, max_qps: int) -> None:
        self._max_qps = max_qps
        self._lock = asyncio.Lock()
        self._dispatch_times: list[float] = []

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            # 清理 1 秒前的记录
            self._dispatch_times = [t for t in self._dispatch_times if now - t < 1.0]
            if len(self._dispatch_times) >= self._max_qps:
                # 需要等到最早的请求满 1 秒后才能放行
                wait = 1.0 - (now - self._dispatch_times[0])
                if wait > 0:
                    await asyncio.sleep(wait)
                    now = time.monotonic()
                    self._dispatch_times = [t for t in self._dispatch_times if now - t < 1.0]
            self._dispatch_times.append(now)


class AmapClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.amap_base_url,
            timeout=settings.amap_timeout,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=0),
            headers={"User-Agent": "TravelAssistant/0.1"},
        )
        self._cache = TTLCache(settings.amap_cache_ttl)
        self._limiter = RateLimiter(MAX_QPS)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_json(
        self, path: str, params: dict[str, str], timeout: float | None = None
    ) -> dict:
        """发起高德 GET 请求；任何失败路径都返回 {} 而不是抛异常。

        所有高德 API 调用统一经过此方法，RateLimiter 自动确保 QPS 不超限。
        """
        cache_key = (path, tuple(sorted(params.items())))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # 全局限流：等到安全时刻再发请求（锁内等待，锁外执行 HTTP）
        await self._limiter.acquire()

        request_params = {**params, "key": self._settings.amap_api_key}
        request_timeout = httpx.Timeout(timeout) if timeout else None
        try:
            resp = await self._client.get(path, params=request_params, timeout=request_timeout)
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException:
            logger.warning("amap_timeout_L1", path=path)
            return {}
        except httpx.HTTPStatusError as exc:
            logger.warning("amap_http_error_L1", path=path, status_code=exc.response.status_code)
            return {}
        except Exception as exc:  # 含限流、连接错误、JSON 解析错误等
            logger.warning("amap_request_failed_L1", path=path, error=str(exc)[:200])
            return {}

        if not isinstance(data, dict) or data.get("status") != "1":
            logger.warning(
                "amap_business_error_L1",
                path=path,
                infocode=(data or {}).get("infocode") if isinstance(data, dict) else None,
                info=(data or {}).get("info") if isinstance(data, dict) else None,
            )
            return {}

        self._cache.set(cache_key, data)
        return data


_singleton: AmapClient | None = None


def get_amap_client() -> AmapClient:
    global _singleton
    if _singleton is None:
        _singleton = AmapClient()
    return _singleton
