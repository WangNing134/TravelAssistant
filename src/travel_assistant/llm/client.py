"""LLM 客户端：OpenAI 兼容协议（默认 DeepSeek，改环境变量即可切换供应商）。

所有调用：
- 强制 JSON 输出（response_format=json_object）；
- 任何异常 / 非法 JSON 都返回 None，由上层走兜底，绝不向图外抛异常。
"""

from __future__ import annotations

import json

from openai import AsyncOpenAI

from travel_assistant.config import get_settings
from travel_assistant.observability.logging import get_logger

logger = get_logger(__name__)


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "missing-key",
            timeout=settings.llm_timeout,
        )

    async def chat_json(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> dict | None:
        try:
            resp = await self._client.chat.completions.create(
                model=self._settings.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # 网络/限流/鉴权/超时统一视为不可用
            logger.warning("llm_request_failed", error=str(exc)[:200])
            return None

        content = resp.choices[0].message.content if resp.choices else ""
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.warning("llm_invalid_json", raw=(content or "")[:200])
            return None
        if not isinstance(data, dict):
            return None
        return data


_singleton: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _singleton
    if _singleton is None:
        _singleton = LLMClient()
    return _singleton


def reset_llm_client() -> None:
    """测试辅助：强制下次重新按当前配置构造客户端。"""
    global _singleton
    _singleton = None
