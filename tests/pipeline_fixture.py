"""Repo-level integration fixtures: a synthetic topic rich enough to run the whole engine.

These tests are the executable form of the end-to-end runbook. They
exist because every stage of this pipeline is individually tested and the interesting
failures are between stages — a sentence ID that S4 wrote and A1 cannot find, an angle whose
metrics no longer recompute after a round-trip through disk.

The corpus is synthetic and deliberately so: a real corpus cannot live in the repo (D14),
and a fixture with known prevalences is the only way to assert that the numbers coming out
the far end are the numbers that went in.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _pkg in ("schema", "corpus", "a1"):
    sys.path.insert(0, str(REPO / "packages" / _pkg))

from datetime import datetime, timezone  # noqa: E402

from newsab_schema.artifacts import append_manifest, run_set_hash  # noqa: E402
from newsab_schema.ids import make_article_id, make_cluster_id  # noqa: E402
from newsab_schema.io import write_articles, write_jsonl, write_yaml  # noqa: E402
from newsab_schema.models.annotation import ConceptOntology, Observation  # noqa: E402
from newsab_schema.models.corpus import (  # noqa: E402
    Article,
    CorpusRun,
    RunArticle,
    ScopeApproval,
    SourceRegistry,
    TopicManifest,
    article_content_hash,
    compute_set_hash,
)
from newsab_schema.models.manifest import ManifestEntry  # noqa: E402
from newsab_schema.paths import TopicPaths, source_registry_path  # noqa: E402
from newsab_schema.store import save_registry, write_corpus_run  # noqa: E402

#: The corpus run every fixture topic activates.  A1 and the validators read the set a run
#: pinned rather than the store directory (R-2), so a fixture without one is not a topic.
CORPUS_RUN_ID = "s2s-202608171200-f1f1f1f1"

TOPIC = "aabb-river-light-2026"
LANGS = {"cn": "zh-CN", "us": "en"}
PROV_MODEL = {
    "skill_version": "S4-0.1.0",
    "model_id": "fixture-model",
    "run_id": "s4-202608171200-0123abcd",
    "timestamp": "2026-08-17T12:00:00Z",
}
PROV_CODE = {**PROV_MODEL, "model_id": None, "skill_version": "S2-0.1.0"}

PROPOSITION = {
    "zh-CN": "该政策在文中被呈现为与{}相关的议题。",
    "en": "The policy is presented as a matter of {}.",
}

#: (dimension, concept, attrs) -> per-group share of clusters that carry it.
#: Chosen so the resulting angle set can satisfy the §3.3 S6 selection constraints under
#: the interval readings: several clear divergences, one voice-structure and one
#: actor-role divergence, one genuine blind-spot shape (high side loud, low side under
#: the silence line), one near-tie that must read as `insufficient` (factual_claim), and
#: the enumerated empty vocabulary cells reading as co-silence.
FEATURES = [
    ("problem_definition", "national_security", None, {"us": 0.85, "cn": 0.15}),
    ("consequence", "study_plan_disruption", {"affected_party": "families", "valence": "negative"},
     {"us": 0.20, "cn": 0.90}),
    ("terminology", "policy_naming", {"referent": "the rule", "term_used": "politicisation"},
     {"us": 0.15, "cn": 0.80}),
    ("quoted_voice", "official_voice",
     {"speaker": "spokesperson", "speaker_category": "government_official"},
     {"us": 0.25, "cn": 0.85}),
    ("factual_claim", "effective_date",
     {"claim_normalized": "The rule takes effect on 2026-09-15"}, {"us": 0.70, "cn": 0.70}),
    ("stance", "policy_stance", {"target": "the rule", "polarity": "oppose"},
     {"us": 0.35, "cn": 0.80}),
    ("responsibility", "federal_blame",
     {"actor": "the federal government", "polarity": "blame"}, {"us": 0.60, "cn": 0.05}),
]


def _source(sid: str, group: str, category: str) -> dict:
    return {
        "id": sid,
        "name": {"values": {"en": f"The {sid} Herald", "zh-CN": f"{sid} 报"}},
        "url": "https://example.com",
        "lang": LANGS[group],
        "country": group.upper(),
        "category": category,
        "notes": {
            "values": {"en": "A synthetic fixture source.", "zh-CN": "测试用的合成源。"}
        },
    }


def _article(article_id: str, source_id: str, cluster: str, group: str, day: int) -> Article:
    lang = LANGS[group]
    title = f"{article_id} headline"
    return Article.model_validate(
        {
            "article_id": article_id,
            "topic_id": TOPIC,
            "source_id": source_id,
            "url": f"https://example.com/{article_id}",
            "title": title,
            "publish_date": f"2026-07-{(day % 28) + 1:02d}",
            "lang": lang,
            "structured_text": [
                {"index": 0, "sentences": [{"index": 1, "text": title}]},
                {
                    "index": 1,
                    "sentences": [
                        {"index": i, "text": f"Body sentence {i} of {article_id}."}
                        for i in range(1, 5)
                    ],
                },
            ],
            "fetch_timestamp": "2026-08-17T00:00:00Z",
            "access_level": "full",
            "origin": {"type": "original"},
            "reporting_cluster_id": cluster,
            "splitter_version": "split-0.1.0",
            "provenance": PROV_CODE,
        }
    )


def build_topic(base: Path, *, clusters_per_category: int = 8) -> TopicPaths:
    """Write a complete pre-A1 topic: corpus store, corpus run, sources, observations, ontology.

    ``base`` holds both halves of the layout the code expects — ``base/topics/`` and the
    cross-topic ``base/sources/registry.yaml`` (R-3) — so a test gets a self-contained repo
    rather than borrowing the real one.
    """
    topics_root = base / "topics"
    paths = TopicPaths.for_topic(topics_root, TOPIC).ensure()
    categories = ("serious", "other")

    articles: list[Article] = []
    sources: list[dict] = []
    cluster_index: dict[str, list[str]] = {"us": [], "cn": []}
    serial = {"us": 0, "cn": 0}

    for group in ("cn", "us"):
        for category in categories:
            for i in range(clusters_per_category):
                source_id = f"{group}_{category}_{i % 6}"
                if not any(s["id"] == source_id for s in sources):
                    sources.append(_source(source_id, group, category))
                serial[group] += 1
                prefix = group.upper()
                article_id = make_article_id(
                    prefix, f"https://example.com/{group}/{serial[group]:03d}"
                )
                cluster_id = make_cluster_id(prefix, article_id)
                articles.append(
                    _article(article_id, source_id, cluster_id, group, serial[group])
                )
                cluster_index[group].append(article_id)

    observations: list[Observation] = []
    obs_serial = 0
    for dimension, concept, attrs, shares in FEATURES:
        for group, share in shares.items():
            members = cluster_index[group]
            take = round(share * len(members))
            for article_id in members[:take]:
                obs_serial += 1
                lang = LANGS[group]
                observations.append(
                    Observation.model_validate(
                        {
                            "observation_id": f"OBS-aabb-river-light-{obs_serial:06d}",
                            "topic_id": TOPIC,
                            "article_id": article_id,
                            "dimension": dimension,
                            "subject": concept.replace("_", " "),
                            "concept_surface": f"{concept}::{lang}",
                            "proposition": {
                                "text": PROPOSITION[lang].format(concept.replace("_", " ")),
                                "lang": lang,
                            },
                            "attrs": attrs or {},
                            "evidence": [f"{article_id}:P01:S01"],
                            "confidence": 0.85,
                            "provenance": PROV_MODEL,
                        }
                    )
                )

    registry = SourceRegistry.model_validate(
        {
            "registry_version": "fixture-0.1.0",
            "updated_at": "2026-08-17T00:00:00Z",
            "sources": sorted(sources, key=lambda s: s["id"]),
        }
    )

    topic_manifest = TopicManifest.model_validate(
        {
            "topic_id": TOPIC,
            "title": {"values": {"en": "synthetic fixture topic"}},
            "groups": [
                {
                    "group_id": group,
                    "prefix": group.upper(),
                    "label": {"values": {"en": group}},
                    "short_label": {"values": {"en": f"{group} side"}},
                    "definition": {"values": {"en": f"synthetic {group} coverage"}},
                }
                for group in ("cn", "us")
            ],
            "period": {"start": "2026-05-01", "end": "2026-12-31"},
            "include": ["the synthetic policy round"],
            "provenance": {**PROV_CODE, "skill_version": "S0-0.1.0"},
        }
    )
    topic_manifest = topic_manifest.model_copy(update={"scope_approval": ScopeApproval(
        approved_by="test founder",
        approved_at="2026-08-17T00:00:00Z",
        scope_hash=topic_manifest.scope_hash(),
    )})

    concepts = []
    for dimension, concept, _attrs, _shares in FEATURES:
        surfaces = []
        for group, lang in LANGS.items():
            example = next(
                (
                    o.observation_id
                    for o in observations
                    if o.concept_surface == f"{concept}::{lang}"
                ),
                None,
            )
            if example:
                surfaces.append({"text": f"{concept}::{lang}", "lang": lang, "example_obs": example})
        if surfaces:
            concepts.append(
                {
                    "concept_id": concept,
                    "label": {"values": {"en": concept.replace("_", " ")}},
                    "surfaces": surfaces,
                    "merged_by": {"skill_version": "S4norm-0.1.0", "run_id": "fixture"},
                }
            )
    ontology = ConceptOntology.model_validate(
        {
            "topic_id": TOPIC,
            "ontology_version": "onto-fixture",
            "concepts": concepts,
            "provenance": {**PROV_CODE, "skill_version": "S4norm-0.1.0"},
        }
    )

    write_articles(paths.articles_dir, articles)
    save_registry(source_registry_path(topics_root), registry)
    write_yaml(paths.topic_manifest, topic_manifest)
    write_jsonl(paths.observations, observations)
    write_yaml(paths.concepts, ontology)

    run = CorpusRun(
        run_id=CORPUS_RUN_ID,
        topic_id=TOPIC,
        articles=[
            RunArticle(
                article_id=article.article_id,
                source_id=article.source_id,
                content_hash=article_content_hash(article),
                reporting_cluster_id=article.reporting_cluster_id,
            )
            for article in sorted(articles, key=lambda a: a.article_id)
        ],
        set_hash=compute_set_hash({a.article_id: article_content_hash(a) for a in articles}),
        splitter_version="split-0.1.0",
        cluster_threshold=0.6,
        cluster_shingle_n=5,
        provenance={**PROV_CODE, "skill_version": "S2build-0.3.0"},
    )
    paths.stage_run_dir("corpus", CORPUS_RUN_ID).mkdir(parents=True, exist_ok=True)
    write_corpus_run(paths, run)
    append_manifest(
        paths,
        ManifestEntry(
            skill_id="newsab-corpus/build",
            skill_version="0.3.0",
            model_id=None,
            run_id=CORPUS_RUN_ID,
            topic_id=TOPIC,
            stage="corpus",
            output_set_hash=run_set_hash(paths, "corpus", CORPUS_RUN_ID),
            timestamp=datetime(2026, 8, 17, 12, tzinfo=timezone.utc),
        ),
        activate_stage="corpus",
    )
    return paths


def run_script(relative: str, *args: str) -> subprocess.CompletedProcess:
    """Invoke a skill script the way an agent harness would: as a subprocess."""
    return subprocess.run(
        [sys.executable, str(REPO / relative), *args],
        capture_output=True,
        text=True,
    )
