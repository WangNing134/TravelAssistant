"""天气感知 POI 过滤：LLM 分类景点室内外，坏天气时移除纯户外景点。

成功：返回仅含室内景点的 POI 列表。
失败/不足：返回原始列表（不冒险丢数据）。
"""

from __future__ import annotations

from travel_assistant.domain.models import POI
from travel_assistant.llm.client import get_llm_client
from travel_assistant.llm.parsers import parse_poi_filter
from travel_assistant.llm.prompts import POI_FILTER_SYSTEM, POI_FILTER_USER
from travel_assistant.observability.logging import get_logger

logger = get_logger(__name__)

# 过滤后剩余 POI 最少数量（不足则保留全部，避免行程空荡）
MIN_POI_AFTER_FILTER = 4


def _build_user(pois: list[POI]) -> str:
    names = "\n".join(f"- {p.name}" for p in pois)
    return POI_FILTER_USER.format(poi_names=names)


async def filter_outdoor_pois(pois: list[POI]) -> list[POI]:
    """LLM 分类后保留室内景点；失败或剩余不足时返回原始列表。"""
    if not pois:
        return pois

    allowed = {p.name for p in pois}
    by_name = {p.name: p for p in pois}
    user_prompt = _build_user(pois)

    data = await get_llm_client().chat_json(
        POI_FILTER_SYSTEM, user_prompt, max_tokens=1024, temperature=0.1
    )
    classification = parse_poi_filter(data, allowed)
    if classification is None:
        logger.warning("poi_filter_llm_failed_keep_all")
        return pois

    indoor_names = [name for name, indoor in classification.items() if indoor]
    filtered = [by_name[name] for name in indoor_names if name in by_name]

    # 未被 LLM 分类的景点默认保留（保守策略）
    classified = set(classification.keys())
    for p in pois:
        if p.name not in classified:
            filtered.append(p)

    if len(filtered) < MIN_POI_AFTER_FILTER:
        logger.info("poi_filter_too_few_keep_all", filtered=len(filtered), min=MIN_POI_AFTER_FILTER)
        return pois

    logger.info("poi_filter_done", before=len(pois), after=len(filtered), removed=len(pois) - len(filtered))
    return filtered
