# 旅途（TravelAssistant）分期工程规划

> 从空目录到「可运行、效果好」的多智能体旅游规划 API 服务，共分 **8 期（P0–P7）**。
> 每期都有独立可验收的产出，批准后按顺序逐期实施；每期结束即为下一期的稳定基线。

---

## 一、仓库研究结论（Repository Research）

- 工作目录 `f:\java-study\TravelAssistant` 当前**仅有一份 PRD**（`PRD_for_AI.md`），无任何代码、依赖管理文件或 Git 历史，属于绿地项目。
- PRD 的硬性约束（不可协商）：
  1. **纯 API 服务**：自然语言入参 → 结构化 JSON 行程，无 GUI。
  2. **零地点幻觉**：地点/天气/酒店只允许来自高德地图 API；API 故障走预设兜底，禁止 LLM 捏造。
  3. **多智能体 + LangGraph 状态图**：Supervisor、WeatherAgent、POIAgent、HotelAgent。
  4. **非对称 DAG 拓扑**：START → Supervisor →（Weather ‖ POI 并行）→ 等 POI 完成 → Hotel 串行 → Supervisor 聚合 → END。
  5. **4 级降级 SLA**：L1 工具防御返回 `[]`；L2 编排 >3 次失败走贪心算法；L3 节点假死走本地经典路线 JSON 库；L4 全局 Panic 返回极简兜底文案。
- 已确认选型：**Python 3.11+ / LangGraph / FastAPI / Pydantic v2 / httpx（异步）**；LLM 使用 **OpenAI 兼容协议**（`base_url + api_key + model` 可配置，默认 DeepSeek，可切通义/Kimi）。

### 关键外部事实（影响设计）

- 高德 REST 端点（Web 服务 Key）：
  - 地理编码 `/v3/geocode/geo`：城市名 → `adcode` + 经纬度；
  - 天气 `/v3/weather/weatherInfo?extensions=all`：入参为 **adcode**，未来预报通常只覆盖 **约 4 天**——超过部分天气必须标记 `unavailable`，严禁编造（与反幻觉约束一致）；
  - 关键字搜索 `/v3/place/text`：按城市 + 关键字/类型码取景点（景点类型码 `110000`）；
  - 周边搜索 `/v3/place/around`：以 `lng,lat` 为中心找酒店（`100000`）/餐饮（`050000`），响应自带 `distance` 字段。
- 高德坐标为 GCJ-02，全链路统一坐标系即可，距离排序用周边搜索返回值或 haversine。
- LangGraph 对同一节点扇出到多个下游时，会在同一 superstep **并行执行**；多个上游汇入同一节点时具备 **barrier（等齐）语义**——这正是非对称 DAG 所需。并发节点写同一 State 字段必须声明 **reducer**。

---

## 二、目标架构与目录骨架

```text
TravelAssistant/
├── pyproject.toml                  # 依赖与工具配置（依赖版本锁定）
├── .env.example                    # AMAP_KEY / LLM_BASE_URL / LLM_KEY / LLM_MODEL
├── README.md
├── Dockerfile                      # P7
├── docker-compose.yml              # P7
├── src/travel_assistant/
│   ├── main.py                     # FastAPI 应用与 uvicorn 启动
│   ├── config.py                   # pydantic-settings 读取环境变量
│   ├── domain/
│   │   ├── models.py               # Location/POI/Hotel/Weather/Itinerary/TripPlan（Pydantic）
│   │   └── state.py                # AgentState（LangGraph TypedDict + reducer）
│   ├── tools/                      # 高德工具层（唯一外部数据源，L1 防御在此）
│   │   ├── amap_client.py          # 异步 httpx 客户端：5s 超时/限流/异常 → []
│   │   ├── geocode_tool.py         # 城市名 → adcode/经纬度
│   │   ├── weather_tool.py
│   │   ├── poi_tool.py             # 关键字搜索
│   │   └── around_tool.py          # 周边搜索（酒店/餐饮）
│   ├── llm/
│   │   ├── client.py               # OpenAI 兼容客户端封装（JSON Mode/Function Calling）
│   │   ├── prompts.py              # 全部提示词集中管理（few-shot 调优点）
│   │   └── parsers.py              # LLM 输出 → Pydantic，校验失败即视为不可信
│   ├── agents/
│   │   ├── supervisor.py           # 意图提取 + 天级编排聚合
│   │   ├── weather_agent.py
│   │   ├── poi_agent.py
│   │   └── hotel_agent.py
│   ├── graph/
│   │   └── builder.py              # StateGraph 装配：fan-out / barrier / 串行边
│   ├── fallback/
│   │   ├── greedy_planner.py       # L2：距离贪心 + 按游玩时长切天
│   │   ├── classic_routes/         # L3：城市经典路线 JSON 库（真实数据手工维护）
│   │   └── degrader.py             # 统一降级决策、降级标记与告警
│   ├── api/
│   │   ├── routes.py               # POST /api/v1/trips/plan、GET /healthz
│   │   ├── schemas.py              # 请求/响应/错误模型
│   │   └── middleware.py           # trace_id 注入 + L4 全局异常拦截
│   └── observability/logging.py    # 结构化日志（trace_id、耗时、降级级别）
├── tests/
│   ├── fixtures/amap/              # 录制的高德真实响应（脱敏）
│   ├── unit/
│   ├── integration/                # API + Graph 全链路（mock 外部依赖）
│   └── chaos/                      # 故障注入：逐级验证 L1–L4
└── scripts/smoke_amap.py           # 高德 Key 联通性冒烟脚本
```

### 核心数据契约（P0 冻结，后续只增不改）

- `Location{name, adcode, lng, lat}`；`POI(Location)+{duration, price}`；`Hotel(Location)+{distance}`；
- `Weather{date, condition, temperature}`（无数据时 `condition="unavailable"`，不编造）；
- `Itinerary{date, weather, hotel, pois: 有序列表}`；
- 最终响应 `TripPlan{city, days, itineraries[], meta{degraded_level, trace_id, warnings[]}}`。

---

## 三、分期实施计划

### P0 · 工程地基与领域模型（骨架可运行）
**目标**：可安装、可启动空壳、配置/日志/数据契约就位。
- 建立 `pyproject.toml`（langgraph、fastapi、uvicorn、pydantic、pydantic-settings、httpx、openai、structlog；dev：pytest、pytest-asyncio、respx），Python 3.11+，创建虚拟环境。
- `.env.example`：`AMAP_API_KEY`、`AMAP_BASE_URL`、`LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`、超时与重试参数。
- `config.py` 集中配置并在启动时校验必填项；`observability/logging.py` 结构化日志。
- `domain/models.py`：按 PRD 写全 Pydantic 模型与统一响应壳；`domain/state.py`：定义 `AgentState`（含城市、天数、偏好、poi 列表、weather 列表、hotel、错误/降级标记，列表字段配 `Annotated[..., add]` reducer 供并行写入）。
- 最小 `main.py` + `/healthz`，`uvicorn` 可起。
**验收**：`pytest` 空跑通过；`GET /healthz` 200；配置缺失时报清晰错误；模型实例化/序列化单测通过。

### P1 · 高德工具层 + L1 防御（真实数据源打通）
**目标**：所有真实数据唯一出入口就位，故障绝不抛穿。
- `amap_client.py`：统一异步 GET，**5s 超时**、HTTP 非 200 / 高德 `status!=1` / 限流失效 / JSON 异常一律捕获并返回空集合，记录 warning；key 与分页统一处理。
- 四个工具：geocode（城市→adcode/坐标）、weather（adcode→逐日，超 4 天部分置 `unavailable`）、poi（`place/text` + 类型码）、around（`place/around`，取 distance）。
- `scripts/smoke_amap.py`：用真实 Key 冒烟（需用户提供 Key）；同时把响应脱敏录制为 `tests/fixtures/amap/*.json`。
- 单测：正常解析、空结果、超时、限流、脏 JSON 五条路径（respx mock），断言**任何异常都返回 `[]` 而进程存活**。
**验收**：冒烟脚本能拿到真实城市的天气/景点/酒店；L1 单测全绿。

### P2 · LLM 能力层（意图提取，规则兜底）
**目标**：自然语言 → 可信的结构化参数，LLM 不可信时不崩。
- `llm/client.py`：OpenAI 兼容封装（默认 DeepSeek 端点，换供应商只改环境变量），JSON Mode/Function Calling + 超时/重试。
- Supervisor 意图提取：输出 `{city, days, preferences}`，Pydantic 校验；城市名再经 P1 geocode 校验为**真实存在**（防止幻觉城市进入图）。
- 解析失败 → 规则兜底（正则抽天数 + 城市名词典），仍失败则提前走 L4 文案。
- `prompts.py` 建立提示词版本化管理。
**验收**：给定「下周五去成都玩 3 天，想吃火锅看熊猫」正确提取；胡说/缺天数用例走规则兜底，有测试覆盖。

### P3 · LangGraph 非对称 DAG 骨架（桩驱动，先通后真）
**目标**：在不依赖任何外部服务的情况下，证明拓扑与状态流转完全正确。
- `graph/builder.py` 用 `StateGraph(AgentState)` 装配：
  `START → supervisor_extract →` 扇出 `weather_agent` 与 `poi_agent`（并行 superstep）；
  `poi_agent → hotel_agent`（唯一串行依赖边，weather 不接 hotel）；
  `weather_agent、hotel_agent → supervisor_aggregate`（barrier 等齐）→ `END`。
- 三个 Agent 先返回桩数据；并发写字段验证 reducer 无覆盖。
- 增加图级追踪日志（每节点进入/退出、state 快照摘要、trace_id 贯穿）。
**验收**：集成测试断言节点执行顺序满足「weather/poi 并发、hotel 必在 poi 之后、aggregate 最后」；桩数据能聚合成完整 `TripPlan` JSON。

### P4 · 真实 Agent 接线与天级路线编排（效果核心）
**目标**：把 P1/P2 能力挂进 P3 骨架，产出真实可用行程。
- WeatherAgent：城市→adcode→逐日天气写入 State。
- POIAgent：偏好→关键字/类型映射，取景点经纬度、名称；`duration/price` 缺失时用保守默认值并在 warnings 标注（不编造具体数值来源）。
- HotelAgent：以核心 POI 坐标周边搜索酒店+餐饮，按 distance 筛选配对。
- Supervisor 聚合（LL2 主战场）：LLM 把乱序 POI 编排成**天内有序路线**并按游玩时长切天；结构化解析失败/不合理即重试，**累计 >3 次丢弃 LLM 结果，改走贪心算法**（`greedy_planner.py`：最近邻排序 + 按时长/就近聚类切天）；降级事件写入 `meta.degraded_level=2`。
**验收**：端到端跑通「成都 3 天」「杭州 2 天」等真实请求，输出字段全部可溯源到高德；强制 LLM 返回乱码时自动落到贪心路线。

### P5 · 4 级降级体系闭环（100% 可用承诺）
**目标**：按 PRD SLA 把容错补成完整链条，每级可观测、可测试。
- **L1**：P1 已实现，本期补齐所有外部调用点与限流退避。
- **L2**：P4 已实现，抽出统一重试计数与降级标记。
- **L3**：为每个 Agent 节点包 `asyncio.wait_for`（节点级超时预算），Supervisor 假死/超时即中断图，读取 `fallback/classic_routes/{city}.json` 真实手工路线；未知城市用同库「通用城市模板」；`degraded_level=3`。
- **L4**：API 中间件兜底所有未捕获异常，返回 PRD 原文案（城市名取自解析结果，取不到则用「当前城市」），`degraded_level=4`，HTTP 200（保证调用方拿到可用 JSON）。
- `tests/chaos/`：分别注入超时、限流、LLM 乱码、节点死循环、未知异常，断言逐级触发且响应始终合法。
**验收**：五类混沌测试全绿；响应 `meta.degraded_level` 与实际故障级别一致。

### P6 · FastAPI 服务化（可对外提供 API）
**目标**：从脚本变成规范的 HTTP 服务。
- `POST /api/v1/trips/plan`：入参 `{query: string}`，出参 `TripPlan`；`GET /healthz`。
- `middleware.py`：请求级 trace_id、访问日志、统一异常 → L4；`schemas.py` 统一 `data/meta/error` 响应壳。
- 配置 uvicorn workers、连接池上限（与高德 QPS 匹配）、可选简单内存 TTL 缓存（城市级天气/POI 结果缓存，既降限流风险又不牺牲真实性）。
- 接口文档（FastAPI 自带 OpenAPI）；集成测试用 `httpx.AsyncClient`。
**验收**：本地起服务，真实/模拟请求返回结构正确；故障注入下接口永不 5xx。

### P7 · 质量打磨、可观测与部署（效果好、可交付）
**目标**：稳定性、可调试性、可部署性达到长期运行标准。
- 提示词调优：典型城市 few-shot 集；建 `tests` 黄金用例集（多城市/多天数/异常输入），防回归。
- 可观测：每节点耗时、外部调用耗时/失败率、各级降级计数随日志输出；单次请求 trace 可串联。
- 补齐 `classic_routes` 热门城市真实数据（手工核验，杜绝幻觉）。
- `Dockerfile` + `docker-compose.yml`（环境变量注入，无密钥入库）；README 写明申请高德 Key、配置 LLM、启动与测试方式。
- 测试覆盖率达标（工具层/编排/降级为重点）；CI 可选（本地 `pytest` 一键通过即基线）。
**验收**：容器一键启动；全量测试通过；主路径与四类降级均有演示用例和日志证据。

---

## 四、依赖与前置条件（Dependencies & Considerations）

- **高德开放平台 Web 服务 Key**：P1 冒烟必需，需用户提前申请（免费额度足够开发）；未就绪前 P1 用 fixtures/mock 先行。
- **LLM API Key**：P2 必需；采用 OpenAI 兼容协议，供应商可随时通过环境变量切换。
- 依赖版本在 P0 锁定（LangGraph 迭代较快，固定主版本），全部异步栈（httpx + asyncio + LangGraph async API）。
- 数据契约（Pydantic 模型）在 P0 冻结，是各 Agent 并行开发的接口约定。
- Windows 环境：虚拟环境与 pytest-asyncio 原生兼容；容器化放在 P7。

## 五、验证策略（Validation）

- 每级外部数据调用都有「成功 + 空结果 + 超时 + 限流 + 脏数据」单测。
- P3 起用集成测试锁定 DAG 执行顺序与 barrier 语义。
- P5 的混沌测试是 4 级 SLA 的验收凭证。
- P6 起以真实 HTTP 请求做端到端验证，断言输出每个地点字段均可溯源至高德响应。
- 全程坚持反幻觉红线：任何模型/兜底输出含非高德来源地点即视为缺陷。

## 六、风险与应对（Risks）

| 风险 | 应对 |
| --- | --- |
| 高德 Key 配额/限流或未及时申请 | P1 先用录制 fixtures 开发；客户端做退避 + P6 缓存；L1 保证返回 `[]` |
| 天气预报仅约 4 天，超出天数无数据 | 超出部分置 `unavailable` 并告警，绝不编造；经典路线库也不写假天气 |
| LLM 输出不稳定/夹带幻觉地点 | 强制 JSON Mode + Pydantic 校验 + 地点必须命中高德结果集，否则丢弃；L2 贪心兜底 |
| LangGraph 并行节点 State 写冲突 | P0 即定义 reducer；P3 用测试证明无覆盖 |
| LangGraph 版本 API 变动 | P0 锁定版本；图装配集中在 `graph/builder.py` 单一文件，便于升级 |
| HotelAgent 在 POI 为空时无坐标可用 | 空 POI 直接短路到 L3 经典路线，不调用周边搜索 |

---

## 七、执行方式

批准本规划后，默认 **从 P0 开始逐期实施**：每期完成 → 跑当期验收测试 → 简报结果 → 继续下一期；你也可以在任意两期之间插入评审或调整。若某期实施中发现需要实质偏离本规划（如技术选型、拓扑变更），将先更新本文档并重新获得确认。
