"""集中式配置：所有运行参数从环境变量 / .env 读取。"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 高德地图
    amap_api_key: str = ""
    amap_base_url: str = "https://restapi.amap.com/v3"
    amap_timeout: float = 5.0
    amap_cache_ttl: int = 300

    # LLM（OpenAI 兼容协议）
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout: float = 15.0

    # Agent 编排
    # 链式节点（extract=LLM+geocode、hotel=高德+LLM）最坏耗时 ≈ llm_timeout + amap_timeout，
    # 默认节点超时须覆盖叠加场景
    node_timeout: float = 30.0
    # POI 多路检索共享 3 QPS 全局限流器且种子 geocode 链长，独立放宽
    poi_node_timeout: float = 45.0
    aggregate_node_timeout: float = 45.0
    llm_arrange_max_attempts: int = 3

    # 服务
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """单例配置（测试中可通过 get_settings.cache_clear() 重置）。"""
    return Settings()
