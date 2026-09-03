"""Fixtures: a tiny two-side corpus that exercises every invariant path."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from newsab_schema import (  # noqa: E402
    Article,
    ArticleAnnotation,
    Observation,
    Provenance,
)
from newsab_schema.models.corpus import LocalEdits, Origin, Paragraph, Sentence  # noqa: E402

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def provenance(skill: str = "S4-0.1.0", model: str | None = "test-model") -> Provenance:
    return Provenance(
        skill_version=skill, model_id=model, run_id="s4-202608171200-0123abcd", timestamp=NOW
    )


def make_article(
    article_id: str = "CN_001",
    lang: str = "zh-CN",
    title: str = "签证收紧引发留学家庭担忧",
    body: tuple[tuple[str, ...], ...] = (
        ("新规将学生签证由身份有效期改为固定停留期限。", "该规定于九月生效。"),
        ("多位家长表示，原有的升学规划被打乱。",),
    ),
    origin_type: str = "original",
    cluster: str = "RC-CN-001",
) -> Article:
    paragraphs = [Paragraph(index=0, sentences=[Sentence(index=1, text=title)])]
    for pi, sentences in enumerate(body, start=1):
        paragraphs.append(
            Paragraph(
                index=pi,
                sentences=[Sentence(index=si, text=t) for si, t in enumerate(sentences, start=1)],
            )
        )
    origin = (
        Origin(type="original")
        if origin_type == "original"
        else Origin(
            type=origin_type,
            wire_source="wire_agency",
            local_edits=LocalEdits(headline_changed=True, lead_changed=False),
        )
    )
    return Article(
        article_id=article_id,
        topic_id="aabb-river-light-2026",
        source_id="example_daily",
        url="https://example.com/a",
        title=title,
        publish_date=date(2026, 7, 1),
        lang=lang,
        structured_text=paragraphs,
        fetch_timestamp=NOW,
        access_level="full",
        origin=origin,
        reporting_cluster_id=cluster,
        splitter_version="split-0.1.0",
        provenance=provenance("S2-0.1.0", None),
    )


def make_observation(
    observation_id: str = "OBS-aabb-river-light-000001",
    article_id: str = "CN_001",
    dimension: str = "consequence",
    proposition: str = "签证收紧被呈现为对留学家庭既有规划的直接冲击。",
    lang: str = "zh-CN",
    evidence: tuple[str, ...] = ("CN_001:P02:S01",),
    attrs: dict | None = None,
    concept_surface: str = "留学家庭规划受冲击",
) -> Observation:
    return Observation(
        observation_id=observation_id,
        topic_id="aabb-river-light-2026",
        article_id=article_id,
        dimension=dimension,
        subject="F-1 visa tightening",
        concept_surface=concept_surface,
        proposition={"text": proposition, "lang": lang},
        attrs=attrs if attrs is not None else {"affected_party": "留学家庭", "valence": "negative"},
        evidence=list(evidence),
        confidence=0.86,
        provenance=provenance(),
    )


@pytest.fixture
def article() -> Article:
    return make_article()


@pytest.fixture
def observation() -> Observation:
    return make_observation()


@pytest.fixture
def article_annotation() -> ArticleAnnotation:
    return ArticleAnnotation(
        article_id="CN_001",
        topic_id="aabb-river-light-2026",
        overall_stance={"target": "US visa policy", "polarity": "oppose", "confidence": 0.9},
        notable_language=[
            {"phrase": "打乱", "sentence": "CN_001:P02:S01", "signal": "high_emotion"}
        ],
        provenance=provenance(),
    )
