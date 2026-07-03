from dataclasses import dataclass
import re

import pandas as pd


@dataclass(frozen=True)
class HotTopicScore:
    score: float
    top_concept: str
    top_heat: int
    concepts_text: str


@dataclass(frozen=True)
class LegitimacyScore:
    score: float
    matched_keywords: str
    reason: str


def score_hot_topics(keywords: pd.DataFrame, *, heat_cap: float = 300.0) -> HotTopicScore:
    if keywords is None or keywords.empty or "概念名称" not in keywords.columns:
        return HotTopicScore(score=0.0, top_concept="", top_heat=0, concepts_text="")

    frame = keywords.copy()
    if "热度" not in frame.columns:
        frame["热度"] = 0
    frame["热度"] = pd.to_numeric(frame["热度"], errors="coerce").fillna(0)
    frame = frame.sort_values("热度", ascending=False)

    top = frame.iloc[0]
    top_heat = int(top["热度"])
    score = max(0.0, min(100.0, top_heat / heat_cap * 100.0))
    concepts = [
        f"{str(row['概念名称'])}({int(row['热度'])})"
        for _, row in frame.head(5).iterrows()
    ]
    return HotTopicScore(
        score=score,
        top_concept=str(top["概念名称"]),
        top_heat=top_heat,
        concepts_text="; ".join(concepts),
    )


def score_legitimacy(keywords: pd.DataFrame, business: pd.DataFrame) -> LegitimacyScore:
    if keywords is None or keywords.empty or business is None or business.empty:
        return LegitimacyScore(score=0.0, matched_keywords="", reason="missing topic or business data")

    concepts = _concept_names(keywords)
    core_text = _join_columns(business, ["主营业务", "产品类型", "产品名称"])
    scope_text = _join_columns(business, ["经营范围"])

    matched_core: list[str] = []
    matched_scope: list[str] = []
    for concept in concepts:
        for token in _concept_tokens(concept):
            if token and token in core_text:
                matched_core.append(token)
                break
        else:
            for token in _concept_tokens(concept):
                if token and token in scope_text:
                    matched_scope.append(token)
                    break

    if matched_core:
        unique = _dedupe(matched_core)
        score = min(100.0, 80.0 + max(0, len(unique) - 1) * 5.0)
        return LegitimacyScore(
            score=score,
            matched_keywords=", ".join(unique),
            reason="matched hot concept in core business/product text",
        )

    if matched_scope:
        unique = _dedupe(matched_scope)
        score = min(70.0, 45.0 + max(0, len(unique) - 1) * 5.0)
        return LegitimacyScore(
            score=score,
            matched_keywords=", ".join(unique),
            reason="matched hot concept in business scope text",
        )

    return LegitimacyScore(score=0.0, matched_keywords="", reason="no business-text match")


def _concept_names(keywords: pd.DataFrame) -> list[str]:
    frame = keywords.copy()
    if "热度" in frame.columns:
        frame["热度"] = pd.to_numeric(frame["热度"], errors="coerce").fillna(0)
        frame = frame.sort_values("热度", ascending=False)
    return [str(value).strip() for value in frame["概念名称"].dropna().head(8) if str(value).strip()]


def _concept_tokens(concept: str) -> list[str]:
    cleaned = (
        concept.replace("概念", "")
        .replace("板块", "")
        .replace("题材", "")
        .replace("产业链", "")
        .strip()
    )
    parts = re.split(r"[\s,/，、;；()（）+-]+", cleaned)
    candidates = [concept, cleaned, *parts]
    return [token for token in _dedupe(candidates) if len(token) >= 2]


def _join_columns(frame: pd.DataFrame, columns: list[str]) -> str:
    values: list[str] = []
    for column in columns:
        if column in frame.columns:
            values.extend(str(value) for value in frame[column].dropna().tolist())
    return " ".join(values)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
