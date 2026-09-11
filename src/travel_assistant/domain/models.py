"""领域实体模型（数据契约，P0 冻结：后续只增不改）。

所有内部流转数据与最终输出必须严格反序列化为这些结构。
硬约束：任何地点字段只允许来自高德地图 API，禁止 LLM 捏造。
"""

from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel, Field


class DegradedLevel(IntEnum):
    """4 级降级 SLA 标记。"""

    NONE = 0        # 全链路真实数据
    L1_API = 1      # 高德 API 防御：单次外部调用失败返回空集合
    L2_FILTER = 2   # 编排容错：LLM 多次失败，贪心算法兜底
    L3_CIRCUIT = 3  # 编排熔断：节点超时/假死，经典路线 JSON 库
    L4_GLOBAL = 4   # 全局兜底：不可知异常，极简维护文案


class Location(BaseModel):
    """位置：所有地点的基类。"""

    name: str
    adcode: str = ""
    lng: float
    lat: float


class POI(Location):
    """景点 / 兴趣点（继承 Location）。"""

    poi_id: str = ""
    address: str = ""
    type_code: str = ""
    # 建议游玩时长（小时）。高德基础接口不返回时使用保守默认值并在 warnings 标注
    duration: float = 2.0
    # 门票预估（元）；无真实来源时为 None，禁止编造
    price: float | None = None


class Hotel(Location):
    """食宿（继承 Location）：酒店或餐饮，用 kind 区分。"""

    address: str = ""
    # 距核心景点距离（米），来自高德周边搜索 distance 字段
    distance: int | None = None
    kind: str = "hotel"  # hotel | restaurant


class Weather(BaseModel):
    """逐日气象。"""

    date: str
    condition: str
    temperature: str  # 形如 "18~26℃"；无真实数据时为 "unavailable"

    @classmethod
    def unavailable(cls, date: str) -> "Weather":
        return cls(date=date, condition="unavailable", temperature="unavailable")


class Itinerary(BaseModel):
    """单日行程：日期 + 气象 + 当日酒店 + 有序景点列表。"""

    date: str
    weather: Weather | None = None
    hotel: Hotel | None = None
    pois: list[POI] = Field(default_factory=list)
    # 增量字段（不破坏 PRD 契约）：就近餐饮建议
    restaurants: list[Hotel] = Field(default_factory=list)


class PlanMeta(BaseModel):
    """响应元信息：降级级别、可观测信息。"""

    trace_id: str
    degraded_level: int = DegradedLevel.NONE
    warnings: list[str] = Field(default_factory=list)
    # realtime（实时真实数据）| classic（经典路线库）| fallback（全局兜底）
    source: str = "realtime"
    note: str | None = None


class TripPlan(BaseModel):
    """最终结构化行程输出。"""

    city: str
    days: int
    itineraries: list[Itinerary] = Field(default_factory=list)
    meta: PlanMeta
    # L4 全局兜底时承载极简文案
    message: str | None = None
