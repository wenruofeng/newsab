"""A synthetic two-side corpus with known structure, so every metric has a right answer."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "schema"))

from newsab_schema.models.annotation import ConceptOntology, Observation  # noqa: E402
from newsab_schema.models.corpus import Article, SourceRegistry  # noqa: E402

NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)
TOPIC = "aabb-river-light-2026"

PROV = {
    "skill_version": "S4-0.1.0",
    "model_id": "test-model",
    "run_id": "s4-202608171200-0123abcd",
    "timestamp": "2026-08-17T12:00:00Z",
}
PROV_DET = {**PROV, "model_id": None, "skill_version": "S2-0.1.0"}

LANG = {"cn": "zh-CN", "us": "en", "id": "id"}
PRESENT = {
    "zh-CN": "该政策被呈现为{}问题。",
    "en": "The policy is presented as a {} issue.",
    # A third group exists only to test that A1 refuses to guess which two to compare.
    # Real Indonesian since lints-0.4: the old half-English placeholder passed
    # only because `id` had no lexicon and every id text got a free FLAG.
    "id": "Kebijakan itu digambarkan sebagai persoalan {}.",
}


def make_source(sid: str, group: str, category: str) -> dict:
    return {
        "id": sid,
        "name": {"values": {"en": f"The {sid} Herald", "zh-CN": f"{sid} 报"}},
        "url": "https://example.com",
        "lang": LANG[group],
        "country": group.upper(),
        "category": category,
        "notes": {"values": {"en": "A fixture outlet.", "zh-CN": "测试用媒体。"}},
    }


def make_article(article_id: str, source_id: str, cluster: str, group: str) -> Article:
    lang = LANG[group]
    title = f"{article_id} title"
    return Article.model_validate(
        {
            "article_id": article_id,
            "topic_id": TOPIC,
            "source_id": source_id,
            "url": f"https://example.com/{article_id}",
            "title": title,
            "publish_date": "2026-07-01",
            "lang": lang,
            "structured_text": [
                {"index": 0, "sentences": [{"index": 1, "text": title}]},
                {
                    "index": 1,
                    "sentences": [
                        {"index": 1, "text": "Sentence one."},
                        {"index": 2, "text": "Sentence two."},
                    ],
                },
            ],
            "fetch_timestamp": "2026-08-17T00:00:00Z",
            "access_level": "full",
            "origin": {"type": "original"},
            "reporting_cluster_id": cluster,
            "splitter_version": "split-0.1.0",
            "provenance": PROV_DET,
        }
    )


def make_observation(
    serial: int,
    article_id: str,
    group: str,
    dimension: str = "problem_definition",
    concept_surface: str = "national security",
    attrs: dict | None = None,
) -> Observation:
    lang = LANG[group]
    return Observation.model_validate(
        {
            "observation_id": f"OBS-aabb-river-light-{serial:06d}",
            "topic_id": TOPIC,
            "article_id": article_id,
            "dimension": dimension,
            "subject": "visa policy",
            "concept_surface": concept_surface,
            "proposition": {"text": PRESENT[lang].format("security"), "lang": lang},
            "attrs": attrs or {},
            "evidence": [f"{article_id}:P01:S01"],
            "confidence": 0.9,
            "provenance": PROV,
        }
    )


class CorpusBuilder:
    """Builds a corpus where you state, per group, how many clusters support a feature."""

    def __init__(self) -> None:
        self.articles: list[Article] = []
        self.observations: list[Observation] = []
        self.sources: list[dict] = []
        self._serial = 0
        self._counts: dict[str, int] = {}

    def add_group(
        self,
        group: str,
        *,
        clusters: int,
        supporting: int,
        category: str = "serious",
        sources: int | None = None,
        dimension: str = "problem_definition",
        concept_surface: str = "national security",
        attrs: dict | None = None,
        articles_per_cluster: int = 1,
    ) -> "CorpusBuilder":
        n_sources = sources if sources is not None else clusters
        source_ids = [f"{group}_{category}_{i}" for i in range(max(n_sources, 1))]
        for sid in source_ids:
            if not any(s["id"] == sid for s in self.sources):
                self.sources.append(make_source(sid, group, category))

        start = self._counts.get(group, 0)
        for c in range(clusters):
            cluster_id = f"RC-{group.upper()}-{start + c + 1:03d}"
            for a in range(articles_per_cluster):
                self._counts[group] = self._counts.get(group, 0) + 1
                article_id = f"{group.upper()}_{self._counts[group]:03d}"
                source_id = source_ids[c % len(source_ids)]
                self.articles.append(make_article(article_id, source_id, cluster_id, group))
                if c < supporting and a == 0:
                    self._serial += 1
                    self.observations.append(
                        make_observation(
                            self._serial, article_id, group, dimension, concept_surface, attrs
                        )
                    )
        return self

    def snapshot(self) -> SourceRegistry:
        return SourceRegistry.model_validate(
            {
                "registry_version": "fixture-0.1.0",
                "updated_at": "2026-08-17T00:00:00Z",
                "sources": sorted(self.sources, key=lambda s: s["id"]),
            }
        )

    def ontology(self) -> ConceptOntology:
        surfaces_by_concept: dict[str, list[dict]] = {}
        for obs in self.observations:
            concept_id = obs.concept_surface.replace(" ", "_").replace("-", "_").lower()
            entries = surfaces_by_concept.setdefault(concept_id, [])
            key = (obs.concept_surface, obs.proposition.lang)
            if not any((e["text"], e["lang"]) == key for e in entries):
                entries.append(
                    {
                        "text": obs.concept_surface,
                        "lang": obs.proposition.lang,
                        "example_obs": obs.observation_id,
                    }
                )
        return ConceptOntology.model_validate(
            {
                "topic_id": TOPIC,
                "ontology_version": "onto-fixture",
                "concepts": [
                    {
                        "concept_id": concept_id,
                        "label": {"values": {"en": concept_id}},
                        "surfaces": surfaces,
                        "merged_by": {"skill_version": "S4norm-0.1.0", "run_id": "fixture"},
                    }
                    for concept_id, surfaces in sorted(surfaces_by_concept.items())
                ],
                "provenance": {**PROV_DET, "skill_version": "S4norm-0.1.0"},
            }
        )


@pytest.fixture
def builder() -> CorpusBuilder:
    return CorpusBuilder()
