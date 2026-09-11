"""P2 验收：LLM 意图提取 + 规则兜底 + 天数钳制。"""

import pytest

from travel_assistant.llm import intents
from travel_assistant.llm.parsers import parse_arrangement, parse_intent


@pytest.fixture
def patch_llm(monkeypatch):
    def _set(payload):
        async def fake_llm_intent(query):
            return parse_intent(payload)

        monkeypatch.setattr(intents, "_llm_intent", fake_llm_intent)

    return _set


async def test_llm_intent_success(patch_llm):
    patch_llm({"city": "成都市", "days": 3, "preferences": ["熊猫", "火锅"]})
    draft = await intents.extract_trip_intent("下周五去成都玩3天，看熊猫吃火锅")
    assert draft.city == "成都"   # 市后缀被剥离
    assert draft.days == 3
    assert "熊猫" in draft.preferences


async def test_llm_garbage_falls_back_to_rule(patch_llm):
    patch_llm({"totally": "unexpected"})  # 校验失败 -> None
    draft = await intents.extract_trip_intent("我想去杭州玩2天")
    assert draft is not None
    assert draft.city == "杭州"
    assert draft.days == 2


async def test_llm_none_rule_weekend(patch_llm):
    patch_llm(None)
    draft = await intents.extract_trip_intent("周末去厦门")
    assert draft.city == "厦门" and draft.days == 2


async def test_no_city_anywhere_returns_none(patch_llm):
    patch_llm(None)
    assert await intents.extract_trip_intent("帮我随便推荐个地方") is None


async def test_days_clamped_to_seven(patch_llm):
    patch_llm({"city": "北京", "days": 99, "preferences": []})
    draft = await intents.extract_trip_intent("北京99天")
    assert draft.days == 7


def test_arrangement_rejects_hallucinated_name():
    allowed = {"宽窄巷子", "武侯祠"}
    good = parse_arrangement(
        {"day_groups": [["宽窄巷子"], ["武侯祠"]]}, days=2, allowed_names=allowed
    )
    assert good is not None

    # 出现清单外的幻觉景点 -> 必须否决
    bad = parse_arrangement(
        {"day_groups": [["宽窄巷子", "一个不存在的奇幻乐园"], ["武侯祠"]]},
        days=2,
        allowed_names=allowed,
    )
    assert bad is None

    # 组数与天数不符 -> 否决
    wrong_days = parse_arrangement(
        {"day_groups": [["宽窄巷子", "武侯祠"]]}, days=2, allowed_names=allowed
    )
    assert wrong_days is None
