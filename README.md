# 旅途 TravelAssistant

基于 **LangGraph 多智能体编排 + 高德地图 API + DeepSeek（OpenAI 兼容协议）** 的端到端旅游规划 API 服务。
输入一句自然语言诉求（如"去成都玩 2 天，看熊猫"），输出带真实坐标、天气、食宿的结构化天级行程。

两条铁律：

- **零地点幻觉**：所有城市、景点、酒店、餐饮必须来自高德返回数据；LLM 只负责意图抽取与天级编排，输出点位经严格校验（名称白名单 + 不重不漏），幻觉即否决重试。
- **永远返回可用 JSON**：任何外部故障都按 4 级降级体系兜底，HTTP 不返回 5xx。

## 架构

非对称 DAG（LangGraph）：

```
START → supervisor_extract（意图 + geocode 校验城市）
          ├─ fatal（无法识别/校验城市）→ global_fallback(L4) → END
          └─ fan-out ┬─ weather_agent（高德天气）
                     └─ poi_agent（高德景点三路融合 + 地理围栏 + 同景区配额）
                              └─ hotel_agent（高德周边：酒店 + 餐饮，POI 空时短路）
  weather + hotel → supervisor_aggregate（barrier 就绪门）
                     ├─ 熔断/POI 全空 → 经典路线库（L3，6 城 35 点，坐标经城市归属核验）
                     ├─ LLM 编排失败 → 距离贪心（L2）
                     └─ LLM 编排成功 → 结构化行程
                  → END
```

关键机制：

| 机制 | 说明 |
| --- | --- |
| 城市校验 | LLM 抽取的城市必须再经高德 geocode 校验，防幻觉城市入图 |
| 景点三路融合 | 偏好检索 / 已核验城市名片种子（geocode 城市限定）/ 热词 + 泛检索，交替配额防垄断 |
| 22km 地理围栏 | 丢弃地级市 adcode 下的远郊县点位 |
| 同景区配额 | 0.8km 空间聚类 + 名称包含，同一景区最多保留 2 个点，名额回填城市名片 |
| 编排强校验 | 天数组数、名称全在真实清单、不重复、不遗漏，违规则重试（最多 3 次） |
| 节点熔断 | `asyncio.wait_for` 节点级超时；`circuit` 信号经 OR reducer 在 fan-out 合并 |
| 屏障 | 多入边会重复调度聚合节点，就绪门保证真实编排只执行一次 |

## 4 级降级 SLA

| 级别 | 触发 | 行为 |
| --- | --- | --- |
| L0 | 正常 | 全量实时真实数据，LLM 编排 |
| L1 | 单个高德接口超时/限流/脏数据 | 吞异常置空（天气置 `unavailable`，绝不编造），其余数据照常 |
| L2 | LLM 编排连续不合规 | 切换距离最近邻 + 天级时长预算贪心算法 |
| L3 | 节点超时熔断 / 景点全空 | 切换本地经典路线库（成都/杭州/北京/上海/西安/重庆，真实核验坐标）；未知城市用空点位通用模板 |
| L4 | 城市不可识别 / 未捕获 Panic | 极简文案 + 核心商圈自由探索建议；runner 与 HTTP 中间件双层兜底 |

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate      # Linux/macOS
pip install -e ".[dev]"
copy .env.example .env          # 填入 AMAP_API_KEY 与 LLM_API_KEY
uvicorn travel_assistant.main:app --app-dir src --reload
```

Docker：

```bash
docker compose up --build
```

## API

### POST `/api/v1/trips/plan`

```bash
curl -X POST http://127.0.0.1:8000/api/v1/trips/plan \
  -H "Content-Type: application/json" \
  -d '{"query": "去成都玩2天，看熊猫"}'
```

响应（节选）：

```json
{
  "city": "成都",
  "days": 2,
  "itineraries": [
    {
      "date": "2026-09-11",
      "weather": {"date": "2026-09-11", "condition": "多云", "temperature": "18~24℃"},
      "hotel": {"name": "...", "distance": 500, "kind": "hotel"},
      "pois": [{"name": "成都大熊猫繁育研究基地", "lng": 104.138, "lat": 30.74, "duration": 2.0}]
    }
  ],
  "meta": {
    "trace_id": "...",
    "degraded_level": 0,
    "warnings": [],
    "source": "realtime"
  }
}
```

- 业务失败也返回 HTTP 200，通过 `meta.degraded_level`（0-4）与 `meta.warnings` 表达降级；仅空 query 返回 422。
- 请求头 `X-Trace-Id` 可传入自定义追踪 ID，响应头原样回显并贯穿结构化日志。
- 交互式文档：服务启动后访问 `/docs`。
- 健康检查：`GET /healthz`。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AMAP_API_KEY` | - | 高德 Web 服务 Key（必填） |
| `AMAP_TIMEOUT` | 5.0 | 高德 HTTP 超时秒数 |
| `AMAP_CACHE_TTL` | 300 | 高德响应内存缓存秒数 |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | deepseek-chat | 任意 OpenAI 兼容服务 |
| `LLM_TIMEOUT` | 15.0 | LLM HTTP 超时 |
| `NODE_TIMEOUT` | 15.0 | 子 Agent 节点熔断阈值 |
| `AGGREGATE_NODE_TIMEOUT` | 45.0 | 聚合节点熔断阈值（超时直接给 L3） |
| `LLM_ARRANGE_MAX_ATTEMPTS` | 3 | LLM 编排不合规重试次数 |

## 测试与联调

```bash
pytest -q                      # 48 项：单元/集成/混沌全绿
python scripts/smoke_e2e.py "去重庆玩2天，吃火锅看夜景"   # 真实端到端联调
python scripts/build_classic_routes.py                   # 重新核验生成经典路线库
```

混沌测试覆盖：节点超时熔断、POI 全空、未知城市模板、未知 Panic、L1 单点故障。

## 目录结构

```
src/travel_assistant/
  api/            FastAPI 路由、schema、trace/兜底中间件
  agents/         supervisor 与 weather/poi/hotel 子 Agent（含熔断装饰器）
  graph/          LangGraph DAG 装配
  tools/          高德 client、geocode/weather/poi/around 工具（L1 防御）
  llm/            DeepSeek 客户端、意图抽取、天级编排与严格校验
  fallback/       L2 贪心、L3 经典路线库（classic_routes.json）、L4 文案
  domain/         冻结数据契约（models）与 AgentState
  service/        图执行统一入口 + TripPlan 组装 + L4 Panic 兜底
  observability/  structlog 结构化日志
scripts/          联调与数据构建脚本
tests/            unit / integration / chaos
```
