"""LLM 输出解析：未经 Pydantic 校验的 LLM 结果一律不可信。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

MAX_DAYS = 7


class IntentDraft(BaseModel):
    city: str
    days: int = 1
    preferences: list[str] = Field(default_factory=list)

    @field_validator("city")
    @classmethod
    def _strip_city(cls, v: str) -> str:
        v = v.strip()
        for suffix in ("市", "地区", "特别行政区"):
            if v.endswith(suffix):
                v = v[: -len(suffix)]
        return v

    @field_validator("days", mode="before")
    @classmethod
    def _coerce_days(cls, v) -> int:
        try:
            days = int(v)
        except (TypeError, ValueError):
            days = 1
        return max(1, min(days, MAX_DAYS))

    @field_validator("preferences", mode="before")
    @classmethod
    def _coerce_prefs(cls, v) -> list[str]:
        if isinstance(v, str):
            return [v] if v.strip() else []
        return [str(x).strip() for x in (v or []) if str(x).strip()]


def parse_intent(data: dict | None) -> IntentDraft | None:
    if not isinstance(data, dict):
        return None
    try:
        draft = IntentDraft.model_validate(data)
    except Exception:
        return None
    if not draft.city:
        return None
    return draft


class ArrangementDraft(BaseModel):
    day_groups: list[list[str]]

    @field_validator("day_groups")
    @classmethod
    def _strip_names(cls, groups: list[list[str]]) -> list[list[str]]:
        return [[str(name).strip() for name in group if str(name).strip()] for group in groups]


def parse_arrangement(data: dict | None, days: int, allowed_names: set[str]) -> ArrangementDraft | None:
    """校验编排结果：组数恰为 days、名称全部来自真实清单、每个最多用一次。"""
    if not isinstance(data, dict):
        return None
    try:
        draft = ArrangementDraft.model_validate(data)
    except Exception:
        return None

    if len(draft.day_groups) != days:
        return None
    used: list[str] = []
    for group in draft.day_groups:
        for name in group:
            if name not in allowed_names:
                return None  # 出现清单外地点 = 幻觉，立即否决
            used.append(name)
    if len(used) != len(set(used)):
        return None  # 重复使用
    if set(used) != allowed_names:
        return None  # 遗漏真实景点
    return draft
