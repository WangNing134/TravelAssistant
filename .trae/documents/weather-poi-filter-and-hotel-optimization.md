# 天气感知POI过滤 + 酒店地理优选中心点规划

## Summary

两项需求：

1. **天气感知POI过滤**：在 weather\_agent 和 poi\_agent 并行扇出后，新增一个 barrier 过滤节点，当天气不好时用 LLM 分类景点室内外，去除纯户外景点（特别是公园），再将过滤后的 POI 传给 hotel\_agent。
2. **酒店地理优选**：从过滤后的 POI 中取前 3 核心景点，计算地理均值坐标作为周边搜索中心点，用 `radius=3000 / types=010000 / sortrule=weight` 检索前 5 家酒店，再由 LLM 根据用户偏好（穷游/豪华/带老人等）精选 1 家。

## Current State Analysis

### 当前拓扑

```
START → supervisor_extract → (weather_agent ∥ poi_agent) → hotel_agent → supervisor_aggregate → END
```

* weather\_agent 和 poi\_agent 并行（同一 superstep）

* poi\_agent → hotel\_agent（串行依赖，hotel 用 pois\[0] 做锚点）

* weather\_agent → supervisor\_aggregate（天气直送聚合，不经过 hotel）

* hotel\_agent → supervisor\_aggregate（barrier 等待 weather + hotel）

### 关键问题

1. **天气不参与 POI 过滤**：weather\_agent 结果直送 aggregate，poi\_agent 和 hotel\_agent 都看不到天气数据
2. **酒店锚点单一**：hotel\_agent 用 `pois[0]`（首个景点）做中心，不是地理均值
3. **酒店搜索参数**：当前 `radius=5000, types="100000", sortrule="distance"`，用户要求 `radius=3000, types="010000", sortrule="weight"`
4. **无 LLM 选酒店**：当前返回酒店列表，aggregate 直接取 `hotels[0]`，无 LLM 精选

## Proposed Changes

### 需求一：天气感知 POI 过滤（新增 barrier 节点）

#### 1. 新增 `src/travel_assistant/agents/poi_filter.py`

barrier 节点，等待 weather + poi 双路就绪后执行：

```python
@trace_node("poi_filter")
@circuit_breaker("poi_filter", {"poi_filtered": True})
async def poi_filter(state: dict) -> dict:
    # barrier 就绪门
    if state.get("poi_filtered"):
        return {}
    if "weathers" not in state or "pois" not in state:
        return {}

    pois = state.get("pois", [])
    weathers = state.get("weathers", [])

    # 判断是否有坏天气日
    bad_days = [w for w in weathers if is_bad_weather(w.condition)]
    if not bad_days or not pois:
        return {"poi_filtered": True}  # 天气好或无POI，直接放行

    # LLM 分类室内外
    filtered = await filter_outdoor_pois(pois)
    return {"pois": filtered, "poi_filtered": True}
```

#### 2. 新增 `src/travel_assistant/llm/poi_filter.py`

LLM 景点室内外分类 + 过滤逻辑：

* `filter_outdoor_pois(pois: list[POI]) -> list[POI]`：

  * 调 LLM 传入景点名称列表

  * LLM 返回 `{"classifications": [{"name": "xxx", "indoor": true/false}, ...]}`

  * 保留 indoor=True 的 POI

  * 兜底：如果 LLM 失败或过滤后剩余 < days\*2，保留全部 POI（不冒险丢数据）

#### 3. 修改 `src/travel_assistant/llm/prompts.py`

新增 POI 分类提示词：

```python
POI_FILTER_SYSTEM = (
    "你是景点室内外分类器。给你一份景点名称清单，请判断每个景点是室内(indoor=true)还是室外(indoor=false)。\n"
    "室内：博物馆、美术馆、科技馆、纪念馆、图书馆、购物中心、海洋馆、水族馆、室内剧场、展览馆。\n"
    "室外：公园、广场、山、湖、古镇、古街、寺庙（室外为主）、风景区、步行街、自然景观、植物园。\n"
    '只输出 JSON：{"classifications": [{"name": "景点名", "indoor": true}]}'
)
POI_FILTER_USER = "景点清单：\n{poi_names}"
```

#### 4. 修改 `src/travel_assistant/llm/parsers.py`

新增 POI 分类解析器：

```python
class POIClassificationDraft(BaseModel):
    name: str
    indoor: bool

class POIFilterDraft(BaseModel):
    classifications: list[POIClassificationDraft]
```

解析校验：名称必须来自真实清单，indoor 为布尔值。

#### 5. 修改 `src/travel_assistant/tools/weather_tool.py`

新增坏天气判断函数：

```python
BAD_WEATHER_KEYWORDS = ("雨", "雪", "暴", "雷", "冰雹", "沙尘", "雾", "霾")

def is_bad_weather(condition: str) -> bool:
    return any(kw in condition for kw in BAD_WEATHER_KEYWORDS)
```

#### 6. 修改 `src/travel_assistant/domain/state.py`

新增 `poi_filtered` 字段到 AgentState：

```python
class AgentState(TypedDict, total=False):
    ...
    poi_filtered: bool  # POI 过滤完成标记
```

#### 7. 修改 `src/travel_assistant/graph/builder.py`

拓扑变更（新增 poi\_filter 节点作为 barrier）：

```
START → supervisor_extract → (weather_agent ∥ poi_agent) → poi_filter → hotel_agent → supervisor_aggregate → END
```

边变更：

* 删除 `NODE_POI → NODE_HOTEL`，改为 `NODE_POI → NODE_POI_FILTER`

* 删除 `NODE_WEATHER → NODE_AGGREGATE`，改为 `NODE_WEATHER → NODE_POI_FILTER`

* 新增 `NODE_POI_FILTER → NODE_HOTEL`

* `NODE_HOTEL → NODE_AGGREGATE` 保持不变（aggregate 现在只有一条入边，barrier 简化）

新增常量：`NODE_POI_FILTER = "poi_filter"`

aggregate 的 barrier 就绪门检查不变（`"weathers" not in state` 仍有效，因为 weather\_agent 已写入 state）。

### 需求二：酒店地理优选 + LLM 选酒店

#### 8. 修改 `src/travel_assistant/tools/around_tool.py`

变更酒店搜索参数：

```python
HOTEL_TYPE = "010000"  # 用户指定：住宿服务分类码

async def _around(lng, lat, types, kind, limit, radius):
    ...
    "sortrule": "weight",  # 按综合权重排序（原为 "distance"）
    ...

async def search_hotels(lng, lat, limit=5, radius=3000):  # radius 5000→3000
    ...
```

注意：`search_restaurants` 的参数保持不变（用户未提及餐饮调整）。餐饮搜索仍用 `sortrule=distance`。

#### 9. 修改 `src/travel_assistant/agents/hotel_agent.py`

核心改造：Top3 质心 + LLM 选酒店

```python
@trace_node("hotel_agent")
@circuit_breaker("hotel_agent", _EMPTY)
async def hotel_agent(state: dict) -> dict:
    pois = state.get("pois", [])
    preferences = state.get("preferences", [])
    if not pois:
        return {"hotels": [], "restaurants": [], "warnings": [...]}

    # 1. 取前 3 核心景点（已按权重排序）
    top3 = pois[:3]

    # 2. 计算地理均值坐标
    center_lng = sum(p.lng for p in top3) / len(top3)
    center_lat = sum(p.lat for p in top3) / len(top3)

    # 3. 高德周边搜索（radius=3000, types=010000, sortrule=weight, top5）
    hotels, restaurants = await asyncio.gather(
        search_hotels(center_lng, center_lat, limit=5, radius=3000),
        search_restaurants(center_lng, center_lat, limit=6, radius=3000),
    )

    # 4. LLM 从 5 家中精选 1 家
    if hotels and preferences:
        selected = await select_hotel_by_llm(hotels, preferences)
        if selected:
            # 选中的排首位
            hotels = [selected] + [h for h in hotels if h.name != selected.name]

    return {"hotels": hotels, "restaurants": restaurants}
```

#### 10. 新增 `src/travel_assistant/llm/hotel_selection.py`

LLM 酒店精选模块：

* `select_hotel_by_llm(hotels: list[Hotel], preferences: list[str]) -> Hotel | None`：

  * 构造 prompt：5 家酒店名称/地址/距离 + 用户偏好

  * LLM 返回 `{"selected_hotel": "酒店名", "reason": "..."}`

  * 名称匹配回 Hotel 列表

  * LLM 失败返回 None（上层用原始排序的首家）

#### 11. 修改 `src/travel_assistant/llm/prompts.py`

新增酒店精选提示词：

```python
HOTEL_SELECT_SYSTEM = (
    "你是酒店选择顾问。给你 5 个候选酒店（来自地图 API，含名称、地址、距离核心景点距离）和用户的旅行偏好，"
    "请选出最符合用户预算和风格的那一家。\n"
    "选择依据：'穷游'/'经济'->距离近实惠；'豪华'/'高端'->品牌酒店；'带老人'/'亲子'->交通便利安静。\n"
    '只输出 JSON：{"selected_hotel": "酒店名", "reason": "简要理由"}'
)
HOTEL_SELECT_USER = (
    "用户偏好：{preferences}\n候选酒店：\n{hotel_lines}"
)
```

#### 12. 修改 `src/travel_assistant/llm/parsers.py`

新增酒店选择解析器：

```python
class HotelSelectDraft(BaseModel):
    selected_hotel: str
    reason: str = ""

def parse_hotel_select(data: dict | None, allowed_names: set[str]) -> str | None:
    # 校验：酒店名必须在候选清单中
```

### 测试更新

#### 13. 修改 `tests/integration/test_dag_topology.py`

更新拓扑断言：

```python
# POI → Filter → Hotel（不再是 POI → Hotel 直连）
assert (NODE_POI, NODE_POI_FILTER) in edges
assert (NODE_POI_FILTER, NODE_HOTEL) in edges

# Weather → Filter（不再是 Weather → Aggregate）
assert (NODE_WEATHER, NODE_POI_FILTER) in edges

# Aggregate 上游只有 Hotel
aggregate_sources = {src for src, dst in edges if dst == NODE_AGGREGATE}
assert aggregate_sources == {NODE_HOTEL}
```

#### 14. 新增 `tests/unit/test_poi_filter.py`

* 测试 `is_bad_weather()`：晴/多云=False，雨/雪/暴=True

* 测试 LLM 分类：mock LLM 返回，验证户外 POI 被移除

* 测试兜底：LLM 失败时保留全部 POI

* 测试天气好时不触发过滤

#### 15. 新增 `tests/unit/test_hotel_selection.py`

* 测试地理均值计算：3 个景点坐标取平均

* 测试酒店搜索参数：`radius=3000, types=010000, sortrule=weight`

* 测试 LLM 选酒店：mock LLM 返回，验证选中酒店排首位

* 测试 LLM 失败兜底：返回 None 时用原始排序

## Assumptions & Decisions

1. **`types=010000`**：用户明确指定，按用户指令执行。若测试中发现高德 API 不识别此码，回退到 `100000`。
2. **Top3 取法**：POI 搜索结果默认按权重排序，`pois[:3]` 即为权重最高的 3 个核心景点。
3. **过滤兜底**：LLM 分类失败或过滤后剩余 POI 不足 `days * 2` 时，保留全部 POI 不冒险丢数据。
4. **餐饮搜索**：用户未提及餐饮参数调整，餐饮仍用 `sortrule=distance`、`radius=3000`（改用质心坐标但排序方式不变）。
5. **barrier 模式**：poi\_filter 节点采用与 supervisor\_aggregate 相同的就绪门模式（检查 `weathers` 和 `pois` 都在 state 中 + `poi_filtered` 防重入）。
6. **aggregate 简化**：weather → aggregate 边改为 weather → poi\_filter 后，aggregate 只有一条入边（hotel），barrier 就绪门仍保留（防御性）。

## Verification Steps

1. `pytest tests/unit/test_poi_filter.py -v` — POI 过滤单元测试
2. `pytest tests/unit/test_hotel_selection.py -v` — 酒店优选单元测试
3. `pytest tests/integration/test_dag_topology.py -v` — 拓扑结构断言
4. `pytest tests/ -v --ignore=tests/integration` — 全量单元测试回归
5. `python scripts/smoke_e2e.py "去成都玩2天，看熊猫"` — 端到端冒烟（验证完整链路）

