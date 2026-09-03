"""Synthetic, from-scratch topic fixture for the publish package's full publication
lifecycle test: prepare -> verify-candidate -> activate -> verify-site.

Every artifact here is hand-built from schema-valid Python objects in ``tmp_path`` — no
dependency on this machine's real ``topics/`` or ``site/`` trees.  The shape mirrors two
already-proven fixtures rather than reinventing either:

* ``tests/pipeline_fixture.py`` — a synthetic corpus store + corpus run + manifest chain.
* ``packages/editorial/tests/test_reader_page.py``'s ``ev_*`` helpers — a ``ReaderPage``
  whose badge numerator/denominator are literally the counts its own answers produce, so
  ``check_page``'s recomputation checks (which ``render_locales`` runs on every prepare)
  pass by construction rather than by coincidence.

``build_topic`` writes a complete run closure — corpus, questions, answers, a no-op
normalization, a hand-built analysis (a1 qa) run, and one editorial page run — with a
correctly chained ``manifest/manifest.jsonl`` and active-version selector, exactly as
``newsab_publish.builder.resolve_inputs`` expects to read them.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from newsab_a1.qa_analyze import QAThresholds, analyse_qa
from newsab_schema.artifacts import append_manifest, artifact_hashes, run_set_hash
from newsab_schema.common import LangText, Provenance
from newsab_schema.enums import TopicStatus
from newsab_schema.io import write_articles, write_jsonl, write_yaml
from newsab_schema.models.corpus import (
    Article,
    CorpusRun,
    Group,
    Origin,
    Paragraph,
    Period,
    RunArticle,
    ScopeApproval,
    Sentence,
    SourceRegistry,
    TopicManifest,
    article_content_hash,
    compute_set_hash,
)
from newsab_schema.models.category_map import CategoryMap
from newsab_schema.models.findings import QAFinding
from newsab_schema.models.manifest import ManifestEntry
from newsab_schema.models.page import ReaderPage
from newsab_schema.models.qa import ClusterAnswer, Question, QuestionSet
from newsab_schema.paths import TopicPaths, source_registry_path
from newsab_schema.store import save_registry, write_corpus_run

from newsab_publish.metadata import SiteCategory, SiteMetadata

#: The public toolkit's sole fictional topic identity.
TOPIC_ID = "aabb-river-light-2026"
#: The language a synthetic reviewer reads in — the site's non-pivot locale.
REVIEW_LOCALE = "zh-CN"

NOW = datetime(2026, 8, 29, tzinfo=timezone.utc)

CORPUS_RUN_ID = "s2s-202608290900-f1000001"
QUESTIONS_RUN_ID = "qst-202608290901-f1000002"
ANSWERS_RUN_ID = "ans-202608290902-f1000003"
NORMALIZATION_RUN_ID = "nrm-202608290903-f1000004"
QA_RUN_ID = "qa-202608290904-f1000005"
PAGE_RUN_ID = "edt-202608290905-f1000006"

QUESTION_ID = "QST-aabb-river-light-002"
#: A consensus question — the catalog record needs at least two angles
#: (``CatalogRecord.angles`` has a min length of 2), so the page carries two real,
#: independently-recomputable findings rather than one repeated.
QUESTION2_ID = "QST-aabb-river-light-004"
SILENT_QUESTION_ID = "QST-aabb-river-light-003"
FINDING_ID = "FND-aabb-river-light-002-divergence"
FINDING2_ID = "FND-aabb-river-light-004-consensus"
FINDING3_ID = "FND-aabb-river-light-003-attention_gap"

#: The share each side's three single-article clusters carries, chosen to match the
#: badge/finding/question_stats numbers below exactly (2 of 3 addressed clusters land on
#: the modal category, 1 on a shared category).
AA_CATEGORIES = ["safer_crossings", "safer_crossings", "safer_crossings"]
BB_CATEGORIES = ["dark_sky_testing", "dark_sky_testing", "dark_sky_testing"]
AA2_CATEGORIES = ["adaptive_dimming", "adaptive_dimming", "adaptive_dimming"]
BB2_CATEGORIES = ["adaptive_dimming", "adaptive_dimming", "adaptive_dimming"]


def _prov(skill: str, model: str | None, run_id: str) -> Provenance:
    return Provenance(skill_version=skill, model_id=model, run_id=run_id, timestamp=NOW)


def _article(article_id: str, lang: str, sentences: list[str], title: str) -> Article:
    group, key = article_id.split("_")
    return Article(
        article_id=article_id,
        topic_id=TOPIC_ID,
        source_id=f"{group.lower()}_outlet_{key[-1]}",
        url=(
            f"https://example.com/{article_id}"
            if group == "AA"
            else f"https://example.org/{article_id}"
        ),
        title=title,
        publish_date=date(2026, 7, 17),
        lang=lang,
        structured_text=[
            Paragraph(index=0, sentences=[Sentence(index=1, text=title)]),
            Paragraph(
                index=1,
                sentences=[Sentence(index=i, text=t) for i, t in enumerate(sentences, 1)],
            ),
        ],
        fetch_timestamp=NOW,
        access_level="full",
        origin=Origin(type="original"),
        reporting_cluster_id=f"RC-{group}-{key}",
        splitter_version="split-0.1.0",
        provenance=_prov("S2stage-0.1.0", None, "s2s-202608290000-00000000"),
    )


def _cluster_articles(group: str, lang: str, count: int) -> list[Article]:
    """``count`` single-article clusters on one side, each with its own sentences."""
    return [
        _article(
            f"{group}_0000000{i}",
            lang,
            [
                f"{group} report {i} says the fictional river lights change after dusk, sentence {j}."
                for j in range(1, 5)
            ],
            f"Fictional {group} river-light report {i}",
        )
        for i in range(1, count + 1)
    ]


_INDEPENDENT_ARTICLES = _cluster_articles("AA", "zh-CN", 3) + _cluster_articles(
    "BB", "en", 3
)
_SYNDICATED_ARTICLE = _article(
    "AA_00000004",
    "zh-CN",
    ["A fictional Aster outlet republishes the first municipal dispatch."],
    "Republished fictional river-light dispatch",
).model_copy(
    update={
        "reporting_cluster_id": "RC-AA-00000001",
        "origin": Origin(type="domestic_wire", wire_source="Fictional Aster Dispatch"),
    }
)
ARTICLES: list[Article] = _INDEPENDENT_ARTICLES + [_SYNDICATED_ARTICLE]


def _source_registry() -> SourceRegistry:
    entries = []
    for article in ARTICLES:
        group = article.article_id.split("_", 1)[0]
        index = article.article_id[-1]
        is_aa = group == "AA"
        entries.append(
            {
                "id": article.source_id,
                "name": {
                    "values": {
                        "en": f"Fictional {'Aster' if is_aa else 'Beryl'} Journal {index}",
                        "zh-CN": f"虚构的{'阿斯特' if is_aa else '贝里尔'}报 {index}",
                    }
                },
                "url": (
                    f"https://example.com/outlet-{index}"
                    if is_aa
                    else f"https://example.org/outlet-{index}"
                ),
                "lang": article.lang,
                "country": group,
                "category": "serious" if int(index) % 2 else "other",
                "notes": {
                    "values": {
                        "en": "A wholly fictional local-news fixture with no real-world referent.",
                        "zh-CN": "完全虚构、没有现实对应物的本地新闻测试媒体。",
                    }
                },
            }
        )
    return SourceRegistry.model_validate(
        {
            "registry_version": "synthetic-0.1.0",
            "updated_at": NOW,
            "sources": entries,
        }
    )


def _manifest() -> TopicManifest:
    base = TopicManifest(
        topic_id=TOPIC_ID,
        title={"values": {"en": "River lighting pilot", "zh-CN": "河岸照明试点"}},
        status=TopicStatus.ACTIVE,
        groups=[
            Group(
                group_id="aa",
                prefix="AA",
                label={"values": {"en": "Aster coverage", "zh-CN": "阿斯特报道"}},
                short_label={"values": {"en": "Aster side", "zh-CN": "甲方"}},
                definition={"values": {"en": "Fictional Aster-language coverage"}},
            ),
            Group(
                group_id="bb",
                prefix="BB",
                label={"values": {"en": "Beryl coverage", "zh-CN": "贝里尔报道"}},
                short_label={"values": {"en": "Beryl side", "zh-CN": "乙方"}},
                definition={"values": {"en": "Fictional Beryl-produced English coverage"}},
            ),
        ],
        period=Period(start=date(2026, 5, 1), end=date(2026, 8, 1)),
        include=["fictional municipal lighting reports during the fixed pilot window"],
        question_seeds=[
            {
                "seed_id": "SQ-001",
                "text": {
                    "values": {
                        "en": "Are migrating birds discussed?",
                        "zh-CN": "是否谈到候鸟？",
                    }
                },
                "mandate": "reference",
            }
        ],
        provenance=_prov("S0-0.1.0", None, "s0-202608290000-00000000"),
    )
    approval = ScopeApproval(
        approved_by="fixture-model stand-in",
        approved_at=NOW,
        scope_hash=base.scope_hash(),
        decided_by="llm_stand_in",
        stand_in_model_id="fixture-model",
    )
    return base.model_copy(update={"scope_approval": approval})


def _question_set() -> QuestionSet:
    return QuestionSet(
        topic_id=TOPIC_ID,
        question_set_version=QUESTIONS_RUN_ID,
        questions=[
            Question(
                question_id=QUESTION_ID,
                topic_id=TOPIC_ID,
                tier="template",
                template_key="responsibility",
                text={"values": {"en": "What is the pilot for?", "zh-CN": "试点为了什么？"}},
                rationale=LangText(text="standard", lang="en"),
                provenance=_prov(
                    "annotate-0.1.0", "fixture-model", "ann-202608290901-00000001"
                ),
            ),
            Question(
                question_id=QUESTION2_ID,
                topic_id=TOPIC_ID,
                tier="template",
                template_key="consequences",
                text={
                    "values": {
                        "en": "How do the lights change after dusk?",
                        "zh-CN": "入夜后灯光如何变化？",
                    }
                },
                rationale=LangText(text="standard", lang="en"),
                provenance=_prov(
                    "annotate-0.1.0", "fixture-model", "ann-202608290901-00000003"
                ),
            ),
            Question(
                question_id=SILENT_QUESTION_ID,
                topic_id=TOPIC_ID,
                tier="reader",
                text={
                    "values": {"en": "Are migrating birds discussed?", "zh-CN": "是否谈到候鸟？"}
                },
                rationale=LangText(text="topic", lang="en"),
                provenance=_prov(
                    "annotate-0.1.0", "fixture-model", "ann-202608290901-00000002"
                ),
            ),
        ],
        provenance=_prov("annotate-0.1.0", "fixture-model", QUESTIONS_RUN_ID),
    )


def _cluster_answer(
    group: str,
    i: int,
    category: str | None,
    *,
    question_id: str,
    serial_base: int,
    addressed: bool = True,
) -> ClusterAnswer:
    serial = serial_base + i if group == "AA" else serial_base + 100 + i
    return ClusterAnswer(
        answer_id=f"ANS-aabb-river-light-{serial:06d}",
        topic_id=TOPIC_ID,
        question_id=question_id,
        question_set_version=QUESTIONS_RUN_ID,
        reporting_cluster_id=f"RC-{group}-0000000{i}",
        group_id=group.lower(),
        addressed=addressed,
        answer_summary=(LangText(text=f"summary {group}{i}", lang="en") if addressed else None),
        answer_category=(category if addressed else None),
        evidence=(
            [f"{group}_0000000{i}:P01:S{j:02d}" for j in range(1, 3)]
            if addressed
            else []
        ),
        confidence=0.8,
        provenance=_prov(
            "annotate-0.1.0", "fixture-model", "ann-202608290902-00000001"
        ),
    )


def _answers() -> list[ClusterAnswer]:
    first = [
        _cluster_answer("AA", i, c, question_id=QUESTION_ID, serial_base=0)
        for i, c in enumerate(AA_CATEGORIES, 1)
    ] + [
        _cluster_answer("BB", i, c, question_id=QUESTION_ID, serial_base=0)
        for i, c in enumerate(BB_CATEGORIES, 1)
    ]
    second = [
        _cluster_answer("AA", i, c, question_id=QUESTION2_ID, serial_base=10)
        for i, c in enumerate(AA2_CATEGORIES, 1)
    ] + [
        _cluster_answer("BB", i, c, question_id=QUESTION2_ID, serial_base=10)
        for i, c in enumerate(BB2_CATEGORIES, 1)
    ]
    attention_gap = [
        _cluster_answer(
            "AA", i, None, question_id=SILENT_QUESTION_ID, serial_base=20, addressed=False
        )
        for i in range(1, 4)
    ] + [
        _cluster_answer(
            "BB", i, "migrating_birds", question_id=SILENT_QUESTION_ID, serial_base=20
        )
        for i in range(1, 4)
    ]
    return first + second + attention_gap


def _category_map() -> CategoryMap:
    """One real synonym judgement plus identity-by-omission for the other questions."""
    return CategoryMap.model_validate(
        {
            "topic_id": TOPIC_ID,
            "question_set_version": QUESTIONS_RUN_ID,
            "answers_run_id": ANSWERS_RUN_ID,
            "merges": {
                QUESTION2_ID: [
                    {
                        "canonical": "adaptive_dimming",
                        "members": ["timed_dimming"],
                        "rationale": {
                            "text": "Both labels describe the fixture lights reducing output on a schedule.",
                            "lang": "en",
                        },
                    }
                ]
            },
            "provenance": _prov("normalize-0.1.0", "fixture-model", NORMALIZATION_RUN_ID),
        }
    )


def recompute_analysis(corpus_run: CorpusRun):
    """Run the production deterministic analyzer over the checked-in fixture inputs."""
    return analyse_qa(
        _question_set(),
        _answers(),
        corpus_run,
        topic_id=TOPIC_ID,
        thresholds=QAThresholds(),
        category_map=_category_map(),
        access_levels={article.article_id: article.access_level.value for article in ARTICLES},
        answers_run_id=ANSWERS_RUN_ID,
    )


def _page() -> ReaderPage:
    return ReaderPage.model_validate(
        {
            "topic_id": TOPIC_ID,
            "title": {"values": {"en": "Two views of a river-light pilot", "zh-CN": "河岸照明试点的两种讲述"}},
            "intro": [
                {
                    "text": {
                        "values": {
                            "en": "Two fictional towns begin a fixed-window river-lighting pilot.",
                            "zh-CN": "两座虚构城镇在固定时间窗内启动河岸照明试点。",
                        }
                    },
                    "claim_type": "corpus_reading",
                    "evidence": ["AA_00000001:P01:S01", "BB_00000001:P01:S01"],
                }
            ],
            "hook": {
                "text": {
                    "values": {
                        "en": "The two samples foreground different purposes for the same fictional pilot.",
                        "zh-CN": "两组样本为同一虚构试点强调了不同目的。",
                    }
                },
                "claim_type": "corpus_aggregate",
                "computed_from": FINDING_ID,
                "evidence": ["AA_00000001:P01:S01"],
            },
            "angles": [
                {
                    "rank": 1,
                    "question_id": QUESTION_ID,
                    "finding_id": FINDING_ID,
                    "kind": "divergence",
                    "caveat": {
                        "values": {
                            "en": "This intentionally tiny fixture clears only the weak statistical gate.",
                            "zh-CN": "这个刻意保持很小的示例只达到较弱统计门槛。",
                        }
                    },
                    "question_display": {
                        "values": {"en": "What is the pilot for?", "zh-CN": "试点为了什么？"}
                    },
                    "editorial_interest": {
                        "text": "The two fictional samples foreground different purposes.",
                        "lang": "en",
                    },
                    "sides": [
                        {
                            "group_id": "aa",
                            "answer": {
                                "text": {
                                    "values": {
                                        "en": "The sampled Aster coverage emphasizes safer crossings.",
                                        "zh-CN": "抽样阿斯特报道强调更安全的过河通道。",
                                    }
                                },
                                "claim_type": "corpus_aggregate",
                                "computed_from": FINDING_ID,
                            },
                            "answer_label": {
                                "values": {"en": "Safer crossings", "zh-CN": "更安全的过河通道"}
                            },
                            "answer_category": "safer_crossings",
                            "quotes": [
                                {
                                    "sentence_id": "AA_00000001:P01:S01",
                                    "translation": {"values": {"en": "x", "zh-CN": "x"}},
                                }
                            ],
                            "badge": {
                                "group_id": "aa",
                                "numerator": 3,
                                "denominator": 3,
                                "computed_from": f"{FINDING_ID}:top_category",
                            },
                        },
                        {
                            "group_id": "bb",
                            "answer": {
                                "text": {
                                    "values": {
                                        "en": "The sampled Beryl coverage emphasizes dark-sky testing.",
                                        "zh-CN": "抽样贝里尔报道强调暗夜环境测试。",
                                    }
                                },
                                "claim_type": "corpus_aggregate",
                                "computed_from": FINDING_ID,
                            },
                            "answer_label": {
                                "values": {
                                    "en": "Dark-sky testing",
                                    "zh-CN": "暗夜环境测试",
                                }
                            },
                            "answer_category": "dark_sky_testing",
                            "quotes": [
                                {
                                    "sentence_id": "BB_00000001:P01:S01",
                                    "translation": {"values": {"en": "x", "zh-CN": "x"}},
                                }
                            ],
                            "badge": {
                                "group_id": "bb",
                                "numerator": 3,
                                "denominator": 3,
                                "computed_from": f"{FINDING_ID}:top_category",
                            },
                        },
                    ],
                },
                {
                    "rank": 2,
                    "question_id": QUESTION2_ID,
                    "finding_id": FINDING2_ID,
                    "kind": "consensus",
                    "caveat": {
                        "values": {
                            "en": "This intentionally tiny fixture clears only the weak statistical gate.",
                            "zh-CN": "这个刻意保持很小的示例只达到较弱统计门槛。",
                        }
                    },
                    "shared_answer_label": {
                        "values": {"en": "Adaptive dimming", "zh-CN": "自适应调暗"}
                    },
                    "question_display": {
                        "values": {
                            "en": "How do the lights change after dusk?",
                            "zh-CN": "入夜后灯光如何变化？",
                        }
                    },
                    "editorial_interest": {
                        "text": "Both fictional samples most often describe adaptive dimming.",
                        "lang": "en",
                    },
                    "sides": [
                        {
                            "group_id": "aa",
                            "answer": {
                                "text": {
                                    "values": {
                                        "en": "The sampled Aster coverage says the lights dim adaptively.",
                                        "zh-CN": "抽样阿斯特报道说灯光会自适应调暗。",
                                    }
                                },
                                "claim_type": "corpus_aggregate",
                                "computed_from": FINDING2_ID,
                            },
                            "answer_label": {
                                "values": {
                                    "en": "Adaptive dimming",
                                    "zh-CN": "自适应调暗",
                                }
                            },
                            "answer_category": "adaptive_dimming",
                            "quotes": [
                                {
                                    "sentence_id": "AA_00000001:P01:S01",
                                    "translation": {"values": {"en": "x", "zh-CN": "x"}},
                                }
                            ],
                            "badge": {
                                "group_id": "aa",
                                "numerator": 3,
                                "denominator": 3,
                                "computed_from": f"{FINDING2_ID}:top_category",
                            },
                        },
                        {
                            "group_id": "bb",
                            "answer": {
                                "text": {
                                    "values": {
                                        "en": "The sampled Beryl coverage says the lights dim adaptively.",
                                        "zh-CN": "抽样贝里尔报道说灯光会自适应调暗。",
                                    }
                                },
                                "claim_type": "corpus_aggregate",
                                "computed_from": FINDING2_ID,
                            },
                            "answer_label": {
                                "values": {"en": "Adaptive dimming", "zh-CN": "自适应调暗"}
                            },
                            "answer_category": "adaptive_dimming",
                            "quotes": [
                                {
                                    "sentence_id": "BB_00000001:P01:S01",
                                    "translation": {"values": {"en": "x", "zh-CN": "x"}},
                                }
                            ],
                            "badge": {
                                "group_id": "bb",
                                "numerator": 3,
                                "denominator": 3,
                                "computed_from": f"{FINDING2_ID}:top_category",
                            },
                        },
                    ],
                },
            ],
            "how_we_counted": {
                "corpus_run_id": CORPUS_RUN_ID,
                "questions_run_id": QUESTIONS_RUN_ID,
                "answers_run_id": ANSWERS_RUN_ID,
                "qa_run_id": QA_RUN_ID,
                "notes": [
                    {
                        "values": {
                            "en": "Counts are over independent reporting clusters.",
                            "zh-CN": "计数单位为独立报道簇。",
                        }
                    }
                ],
            },
            "provenance": _prov(
                "write-0.1.0", "fixture-model", PAGE_RUN_ID
            ).model_dump(mode="json"),
        }
    )


def build_topic(topics_root: Path) -> TopicPaths:
    """Write a complete, correctly-chained run closure ending in one editorial page run.

    Mirrors ``tests/pipeline_fixture.py``'s ``build_topic`` for the corpus half, then
    continues the chain through questions / answers / a no-op normalization / a
    hand-built analysis run / one editorial page run — everything
    ``newsab_publish.builder.resolve_inputs`` walks before a page can be rendered.
    """
    paths = TopicPaths.for_topic(topics_root, TOPIC_ID)
    paths.root.mkdir(parents=True, exist_ok=True)

    write_articles(paths.articles_dir, ARTICLES)
    save_registry(source_registry_path(topics_root), _source_registry())
    write_yaml(paths.topic_manifest, _manifest())

    # -- corpus run ----------------------------------------------------------------
    run_articles = [
        RunArticle(
            article_id=a.article_id,
            source_id=a.source_id,
            content_hash=article_content_hash(a),
            reporting_cluster_id=a.reporting_cluster_id,
        )
        for a in sorted(ARTICLES, key=lambda a: a.article_id)
    ]
    corpus_run = CorpusRun(
        run_id=CORPUS_RUN_ID,
        topic_id=TOPIC_ID,
        articles=run_articles,
        set_hash=compute_set_hash(
            {a.article_id: article_content_hash(a) for a in ARTICLES}
        ),
        splitter_version="split-0.1.0",
        cluster_threshold=0.6,
        cluster_shingle_n=5,
        provenance=_prov("S2build-0.1.0", None, CORPUS_RUN_ID),
    )
    paths.stage_run_dir("corpus", CORPUS_RUN_ID).mkdir(parents=True, exist_ok=True)
    write_corpus_run(paths, corpus_run)
    append_manifest(
        paths,
        ManifestEntry(
            skill_id="newsab-corpus/build",
            skill_version="0.1.0",
            model_id=None,
            run_id=CORPUS_RUN_ID,
            topic_id=TOPIC_ID,
            stage="corpus",
            output_set_hash=run_set_hash(paths, "corpus", CORPUS_RUN_ID),
            timestamp=NOW,
        ),
        activate_stage="corpus",
    )

    # -- questions run ---------------------------------------------------------------
    q_dir = paths.stage_run_dir("questions", QUESTIONS_RUN_ID)
    q_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(q_dir / "questions.yaml", _question_set())
    append_manifest(
        paths,
        ManifestEntry(
            skill_id="annotate",
            skill_version="0.1.0",
            model_id="fixture-model",
            run_id=QUESTIONS_RUN_ID,
            topic_id=TOPIC_ID,
            stage="questions",
            inputs=[CORPUS_RUN_ID],
            output_set_hash=run_set_hash(paths, "questions", QUESTIONS_RUN_ID),
            timestamp=NOW,
        ),
        activate_stage="questions",
    )

    # -- answers run -------------------------------------------------------------------
    ans_dir = paths.stage_run_dir("answers", ANSWERS_RUN_ID)
    ans_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(ans_dir / "answers.jsonl", _answers())
    append_manifest(
        paths,
        ManifestEntry(
            skill_id="annotate",
            skill_version="0.1.0",
            model_id="fixture-model",
            run_id=ANSWERS_RUN_ID,
            topic_id=TOPIC_ID,
            stage="answers",
            inputs=[CORPUS_RUN_ID, QUESTIONS_RUN_ID],
            output_set_hash=run_set_hash(paths, "answers", ANSWERS_RUN_ID),
            timestamp=NOW,
        ),
        activate_stage="answers",
    )

    # -- normalization run: one auditable synonym merge; absent questions are identity. --
    nrm_dir = paths.stage_run_dir("normalization", NORMALIZATION_RUN_ID)
    nrm_dir.mkdir(parents=True, exist_ok=True)
    category_map = _category_map()
    (nrm_dir / "category_map.json").write_text(
        category_map.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    append_manifest(
        paths,
        ManifestEntry(
            skill_id="normalize",
            skill_version="0.1.0",
            model_id="fixture-model",
            run_id=NORMALIZATION_RUN_ID,
            topic_id=TOPIC_ID,
            stage="normalization",
            inputs=[QUESTIONS_RUN_ID, ANSWERS_RUN_ID],
            output_set_hash=run_set_hash(paths, "normalization", NORMALIZATION_RUN_ID),
            timestamp=NOW,
        ),
        activate_stage="normalization",
    )

    # -- analysis (a1 qa) run: recomputed by the real deterministic analyzer.  "analysis" is absent from
    # newsab_schema.paths.STAGE_NAMES (it is not a mutable-selector stage), so its
    # manifest entry uses the legacy output_hashes shape exactly as
    # newsab_a1.cli.cmd_qa writes it — no output_set_hash, no activate_stage. --------
    qa_dir = paths.a1_run_dir(QA_RUN_ID)
    qa_dir.mkdir(parents=True, exist_ok=True)
    analysis = recompute_analysis(corpus_run)
    fixed_provenance = _prov("analyze-0.5.0", None, QA_RUN_ID)
    findings = [
        finding.model_copy(update={"provenance": fixed_provenance})
        for finding in analysis.findings
    ]
    write_jsonl(qa_dir / "findings.jsonl", findings)
    (qa_dir / "question_stats.json").write_text(
        json.dumps(analysis.question_stats, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    run_record = analysis.run_record()
    run_record["qa_run_id"] = QA_RUN_ID
    (qa_dir / "run.json").write_text(
        json.dumps(
            run_record,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    append_manifest(
        paths,
        ManifestEntry(
            skill_id="analyze",
            skill_version="0.5.0",
            model_id=None,
            run_id=QA_RUN_ID,
            topic_id=TOPIC_ID,
            inputs=[CORPUS_RUN_ID, QUESTIONS_RUN_ID, ANSWERS_RUN_ID, NORMALIZATION_RUN_ID],
            output_hashes=artifact_hashes(
                paths, sorted(p for p in qa_dir.rglob("*") if p.is_file())
            ),
            timestamp=NOW,
        ),
    )

    # -- editorial (page) run -----------------------------------------------------------
    page_dir = paths.stage_run_dir("editorial", PAGE_RUN_ID)
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "page.json").write_text(_page().model_dump_json(), encoding="utf-8")
    append_manifest(
        paths,
        ManifestEntry(
            skill_id="write",
            skill_version="0.1.0",
            model_id="fixture-model",
            run_id=PAGE_RUN_ID,
            topic_id=TOPIC_ID,
            stage="editorial",
            inputs=[
                CORPUS_RUN_ID,
                QUESTIONS_RUN_ID,
                ANSWERS_RUN_ID,
                NORMALIZATION_RUN_ID,
                QA_RUN_ID,
            ],
            output_set_hash=run_set_hash(paths, "editorial", PAGE_RUN_ID),
            timestamp=NOW,
        ),
        activate_stage="editorial",
    )

    return paths


def build_metadata(metadata_path: Path) -> SiteMetadata:
    """One minimal site-owned metadata revision naming this fixture topic's category.

    ``metadata_version`` stays below ``site-metadata-1.1.0`` so the per-topic human
    approval gate (``SiteMetadata._controlled_taxonomy``) does not apply — this fixture
    is exercising the publish lifecycle, not the taxonomy approval rule.
    """
    metadata = SiteMetadata(
        metadata_version="site-metadata-1.0.0",
        taxonomy_version="taxonomy-1.0.0",
        locales=["en", "zh-CN"],
        categories=[
            SiteCategory(category_id="world", labels={"en": "World", "zh-CN": "国际"})
        ],
        topic_categories={TOPIC_ID: ["world"]},
    )
    metadata_path.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
    return metadata
