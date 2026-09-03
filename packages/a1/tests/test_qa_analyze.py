"""Assertion-based Q×A analyze (2026-08-22 refactor): posterior machine, kinds,
ranking, identity, merge sensitivity, determinism."""

from __future__ import annotations

import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

for pkg in ("schema", "a1"):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / pkg / "..").replace("/..", ""))

from newsab_schema.common import Provenance
from newsab_schema.enums import FindingKind, FindingStrength
from newsab_schema.models.category_map import CategoryMap
from newsab_schema.models.corpus import CorpusRun, RunArticle, compute_set_hash
from newsab_schema.models.qa import ClusterAnswer, Question, QuestionSet

from newsab_a1.qa_analyze import QAThresholds, analyse_qa, top_probability

TOPIC = "aabb-river-light-2026"
NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def prov() -> Provenance:
    return Provenance(
        skill_version="annotate-0.1.0",
        model_id="test-model",
        run_id="ans-202608200000-00000001",
        timestamp=NOW,
    )


def question(serial: int, key: str | None = "responsibility", tier: str = "template") -> Question:
    return Question.model_validate(
        {
            "question_id": f"QST-aabb-river-light-{serial:03d}",
            "topic_id": TOPIC,
            "tier": tier,
            "template_key": key,
            "text": {"values": {"en": f"Question {serial}?"}},
            "rationale": {"text": "test", "lang": "en"},
            "provenance": prov().model_dump(mode="json"),
        }
    )


def corpus(n_cn: int = 5, n_us: int = 5) -> CorpusRun:
    articles = []
    for i in range(n_cn):
        articles.append(
            RunArticle(
                article_id=f"CN_{i:08x}",
                source_id="src_cn",
                content_hash="sha256:" + "0" * 64,
                reporting_cluster_id=f"RC-CN-{i:08x}",
            )
        )
    for i in range(n_us):
        articles.append(
            RunArticle(
                article_id=f"US_{i:08x}",
                source_id="src_us",
                content_hash="sha256:" + "0" * 64,
                reporting_cluster_id=f"RC-US-{i:08x}",
            )
        )
    articles.sort(key=lambda a: a.article_id)
    return CorpusRun(
        run_id="s2s-20260820000000000000-00000000",
        topic_id=TOPIC,
        articles=articles,
        set_hash=compute_set_hash({a.article_id: a.content_hash for a in articles}),
        splitter_version="split-0.2.0",
        cluster_threshold=0.6,
        cluster_shingle_n=5,
        provenance=Provenance(
            skill_version="S2build-0.4.0",
            model_id=None,
            run_id="s2s-20260820000000000000-00000000",
            timestamp=NOW,
        ),
    )


def corpus_with_peripheral(peripheral: set[str], n_cn: int = 5, n_us: int = 5) -> CorpusRun:
    base = corpus(n_cn, n_us)
    return base.model_copy(update={"articles": [
        a.model_copy(update={
            "topic_relevance": "peripheral" if a.reporting_cluster_id in peripheral else "core"
        })
        for a in base.articles
    ]})


_SERIAL = [0]


def answer(question_id: str, cluster: str, category: str | None, addressed: bool = True) -> ClusterAnswer:
    _SERIAL[0] += 1
    group = cluster.split("-")[1].lower()
    lang = "zh-CN" if group == "cn" else "en"
    art = cluster.replace("RC-", "").replace("-", "_")
    payload = {
        "answer_id": f"ANS-aabb-river-light-{_SERIAL[0]:06d}",
        "topic_id": TOPIC,
        "question_id": question_id,
        "question_set_version": "qst-202608200000-00000001",
        "reporting_cluster_id": cluster,
        "group_id": group,
        "addressed": addressed,
        "provenance": prov().model_dump(mode="json"),
    }
    if addressed:
        payload.update(
            answer_summary={"text": "回答。" if group == "cn" else "An answer.", "lang": lang},
            answer_category=category,
            evidence=[f"{art}:P01:S01"],
        )
    return ClusterAnswer.model_validate(payload)


def qset(questions: list[Question]) -> QuestionSet:
    return QuestionSet(
        topic_id=TOPIC,
        question_set_version="qst-202608200000-00000001",
        questions=questions,
        provenance=prov(),
    )


def cn_clusters(n=5):
    return [f"RC-CN-{i:08x}" for i in range(n)]


def us_clusters(n=5):
    return [f"RC-US-{i:08x}" for i in range(n)]


def category_map(merges: dict) -> CategoryMap:
    return CategoryMap.model_validate(
        {
            "topic_id": TOPIC,
            "question_set_version": "qst-202608200000-00000001",
            "answers_run_id": "ans-202608200000-00000001",
            "merges": merges,
            "provenance": prov().model_dump(mode="json"),
        }
    )


# --- §5.1 regression: the pseudo-vote posterior reproduces the plan's table ------------


@pytest.mark.parametrize(
    "counts,expected",
    [
        ({"a": 2}, 0.928),                                # 2 votes, both the same
        ({"a": 8}, 1.000),                                # 8/8 all the same
        ({"a": 4, "b": 3, "c": 1, "d": 1, "e": 1}, 0.590),  # one-vote lead
        ({"a": 5, "b": 5}, 0.492),                        # dead tie
        ({"a": 30, "b": 29, "c": 4, "d": 3}, 0.551),      # large-sample one-vote lead
    ],
)
def test_simulation_table_regression(counts, expected):
    t = QAThresholds(n_draws=20000, pseudo_total=1.0)
    p = top_probability(counts, t, random.Random(7))
    assert p == pytest.approx(expected, abs=0.02)


def test_full_vote_divergence_stays_supported():
    """The 8/8 vs 5/5 full-vote divergence (the plan's calibration anchor)."""
    q = question(1)
    cn8 = [f"RC-CN-{i:08x}" for i in range(8)]
    us5 = us_clusters(5)
    answers = [answer(q.question_id, c, "cat_x") for c in cn8]
    answers += [answer(q.question_id, c, "cat_y") for c in us5]
    run = analyse_qa(qset([q]), answers, corpus(8, 5), topic_id=TOPIC)
    modal = [f for f in run.findings if f.kind == FindingKind.DIVERGENCE]
    assert len(modal) == 1
    assert modal[0].strength == FindingStrength.SUPPORTED
    assert modal[0].stability >= 0.95


def test_small_sample_certainty_is_penalised_but_large_is_not():
    t = QAThresholds(n_draws=20000, pseudo_total=1.0)
    small = top_probability({"a": 2}, t, random.Random(1))
    large = top_probability({"a": 8}, t, random.Random(1))
    assert small < 0.95 < large


def test_two_votes_all_same_is_at_most_weak():
    """The calibration constraint: two clusters agreeing is not proof."""
    q = question(1)
    cn2 = cn_clusters(2)
    us8 = [f"RC-US-{i:08x}" for i in range(8)]
    answers = [answer(q.question_id, c, "cat_x") for c in cn2]
    answers += [answer(q.question_id, c, "cat_x") for c in us8]
    run = analyse_qa(qset([q]), answers, corpus(2, 8), topic_id=TOPIC)
    modal = [f for f in run.findings if f.kind == FindingKind.CONSENSUS]
    assert len(modal) == 1
    assert modal[0].strength != FindingStrength.SUPPORTED


# --- kinds ----------------------------------------------------------------------------


def test_divergence_supported_and_deterministic():
    q = question(1)
    answers = [answer(q.question_id, c, "chinese_government") for c in cn_clusters()]
    answers += [answer(q.question_id, c, "trump_administration") for c in us_clusters()]
    run1 = analyse_qa(qset([q]), answers, corpus(), topic_id=TOPIC)
    run2 = analyse_qa(qset([q]), answers, corpus(), topic_id=TOPIC)
    [f1] = run1.findings
    assert f1.kind == FindingKind.DIVERGENCE
    assert f1.strength == FindingStrength.SUPPORTED
    assert f1.stability is not None and f1.stability >= 0.9
    assert f1.delta is not None and f1.delta.quantity == "divergence_share_gap"
    assert {g.top_category for g in f1.groups} == {"chinese_government", "trump_administration"}
    assert f1.summary.lang == "en"
    assert f1.interest is None and f1.secondary is False
    # Same inputs, same numbers (run ids differ by timestamp only).
    assert [f.model_dump(exclude={"provenance"}) for f in run1.findings] == [
        f.model_dump(exclude={"provenance"}) for f in run2.findings
    ]


def test_consensus_when_both_tops_agree():
    q = question(1)
    answers = [answer(q.question_id, c, "policy_change") for c in cn_clusters()]
    answers += [answer(q.question_id, c, "policy_change") for c in us_clusters()]
    [finding] = analyse_qa(qset([q]), answers, corpus(), topic_id=TOPIC).findings
    assert finding.kind == FindingKind.CONSENSUS
    assert finding.strength == FindingStrength.SUPPORTED
    assert finding.delta is not None and finding.delta.quantity == "consensus_dominance"
    assert finding.delta.value == pytest.approx(1.0)


def test_partial_modal_overlap_no_longer_kills_the_question():
    """The old dead zone is gone: a most-probable combination always exists."""
    q = question(1)
    answers = [answer(q.question_id, c, "shared") for c in cn_clusters(3)]
    answers += [answer(q.question_id, c, "cn_only") for c in cn_clusters(6)[3:]]
    answers += [answer(q.question_id, c, "shared") for c in us_clusters(6)]
    run = analyse_qa(qset([q]), answers, corpus(6, 6), topic_id=TOPIC)
    assert len(run.findings) == 1
    assert run.findings[0].kind in (FindingKind.CONSENSUS, FindingKind.DIVERGENCE)
    # A 3:3 tie on the cn side cannot clear the supported gate.
    assert run.findings[0].strength != FindingStrength.SUPPORTED


def test_total_silence_attention_gap_replaces_blindspot():
    """qa-0.4.0: a supported gap needs a near-silent side of roughly thirty clusters."""
    q = question(1)
    cn30, us30 = cn_clusters(30), us_clusters(30)
    answers = [answer(q.question_id, c, "layoffs_reported") for c in cn30]
    answers += [answer(q.question_id, c, None, addressed=False) for c in us30]
    [finding] = analyse_qa(qset([q]), answers, corpus(30, 30), topic_id=TOPIC).findings
    assert finding.kind == FindingKind.ATTENTION_GAP
    assert finding.strength == FindingStrength.SUPPORTED
    assert finding.total_silence is True
    assert finding.secondary is False
    speaking = next(g for g in finding.groups if g.clusters_addressed)
    assert speaking.sample_evidence  # silence findings carry contrast anchors
    assert "annotated" in finding.summary.text
    assert "not proof the answer appears nowhere" in finding.summary.text


def test_attention_gap_supersedes_a_thin_modal_finding():
    """One question, one finding (2026-08-22): a firing gap owns the question, and a
    weak consensus riding on the quiet side's single answer is suppressed."""
    q = question(1)
    big = corpus(42, 42)
    cn42, us42 = cn_clusters(42), us_clusters(42)
    answers = [answer(q.question_id, c, "same_cat") for c in cn42[:35]]
    answers += [answer(q.question_id, us42[0], "same_cat")]
    run = analyse_qa(qset([q]), answers, big, topic_id=TOPIC)
    [gap] = run.findings
    assert gap.kind == FindingKind.ATTENTION_GAP
    # qa-0.5.0: one mention in 42 is decisively near-silent under the aligned prior
    # (Jeffreys marginal ≈ 1.00 at smax 0.20) — supported, where qa-0.4.0 said weak.
    assert gap.strength == FindingStrength.SUPPORTED
    assert gap.total_silence is False
    assert gap.delta is not None and gap.delta.quantity == "addressed_rate_diff"
    assert "annotated" not in gap.summary.text  # a mention exists: rate wording, not silence
    stats = run.question_stats[q.question_id]
    assert stats["attention_gap"] is True
    assert stats["attention_gap_quiet_group"] == "us"
    # The modal machine still documents what it saw, even though nothing was emitted.
    assert stats["kind"] == "consensus"


def test_rate_difference_between_two_speaking_sides_is_not_a_gap():
    """The pre-0.4.0 firing shape — both sides plainly speak, rates differ by 75
    points — asserts no gap: the quiet clause needs near-silence, not a difference."""
    q = question(1)
    big = corpus(8, 8)
    cn8, us8 = cn_clusters(8), us_clusters(8)
    answers = [answer(q.question_id, c, "same_cat") for c in cn8]
    answers += [answer(q.question_id, c, "same_cat") for c in us8[:2]]
    run = analyse_qa(qset([q]), answers, big, topic_id=TOPIC)
    assert {f.kind for f in run.findings} == {FindingKind.CONSENSUS}
    stats = run.question_stats[q.question_id]
    assert stats["attention_gap"] is False
    assert stats["attention_gap_stability"] < 0.5
    assert stats["addressed_rate_diff"]["value"] == pytest.approx(0.75)


def test_small_sample_silence_fires_weak_under_the_aligned_prior():
    """qa-0.5.0: five totally silent clusters against a fully speaking side now
    assert a *weak* gap (Jeffreys marginal ≈ 0.87 at smax 0.20).  Under qa-0.4.0's
    uniform prior the same shape sat at ≈ 0.47 and the tab stayed dark — that prior
    inconsistency is what qa-0.5.0 fixes."""
    q = question(1)
    answers = [answer(q.question_id, c, "layoffs_reported") for c in cn_clusters()]
    run = analyse_qa(qset([q]), answers, corpus(), topic_id=TOPIC)
    [gap] = run.findings
    assert gap.kind == FindingKind.ATTENTION_GAP
    assert gap.strength == FindingStrength.WEAK
    assert gap.total_silence is True
    stats = run.question_stats[q.question_id]
    assert stats["kind"] == "too_thin"  # the modal machine still saw nothing comparable
    assert stats["attention_gap"] is True
    assert 0.70 <= stats["attention_gap_stability"] < 0.95


def test_two_cluster_silence_is_still_not_a_gap():
    """The small-sample penalty survives the prior fix: total silence at n=2 keeps
    too much posterior mass above silent_max_rate (Jeffreys marginal ≈ 0.69)."""
    q = question(1)
    answers = [answer(q.question_id, c, "layoffs_reported") for c in cn_clusters()]
    run = analyse_qa(qset([q]), answers, corpus(5, 2), topic_id=TOPIC)
    stats = run.question_stats[q.question_id]
    assert stats["attention_gap"] is False
    assert stats["attention_gap_stability"] < 0.70


def test_legacy_rate_prior_is_reproducible():
    """``rate_pseudo_total=2.0`` reproduces qa-0.4.0's uniform Beta(+1,+1): the 0/5
    total-silence shape does not fire under the legacy thresholds — the calibration
    tool's LEGACY/P0 columns depend on this."""
    q = question(1)
    legacy = QAThresholds(
        thresholds_version="qa-0.4.0", silent_max_rate=0.10, rate_pseudo_total=2.0
    )
    answers = [answer(q.question_id, c, "layoffs_reported") for c in cn_clusters()]
    run = analyse_qa(qset([q]), answers, corpus(), topic_id=TOPIC, thresholds=legacy)
    assert run.findings == []
    stats = run.question_stats[q.question_id]
    assert stats["attention_gap"] is False
    assert 0.0 < stats["attention_gap_stability"] < 0.70


def test_unclear_answers_do_not_manufacture_consensus():
    q = question(1)
    answers = [answer(q.question_id, c, "unclear") for c in cn_clusters()]
    answers += [answer(q.question_id, c, "unclear") for c in us_clusters()]
    run = analyse_qa(qset([q]), answers, corpus(), topic_id=TOPIC)
    modal = [f for f in run.findings if f.kind != FindingKind.ATTENTION_GAP]
    assert modal == []
    assert run.question_stats[q.question_id]["kind"] == "too_thin"


def test_stats_kind_is_honest():
    q1, q2 = question(1), question(2, key=None, tier="reader")
    # q1: a side with zero comparable answers -> too_thin.
    answers = [answer(q1.question_id, cn_clusters()[0], "a_thing")]
    answers += [answer(q1.question_id, c, None, addressed=False) for c in cn_clusters()[1:]]
    answers += [answer(q1.question_id, c, None, addressed=False) for c in us_clusters()]
    # q2: 1v1 with different answers -> a combination exists but clears no gate.
    answers += [answer(q2.question_id, cn_clusters()[0], "x_thing")]
    answers += [answer(q2.question_id, c, None, addressed=False) for c in cn_clusters()[1:]]
    answers += [answer(q2.question_id, us_clusters()[0], "y_thing")]
    answers += [answer(q2.question_id, c, None, addressed=False) for c in us_clusters()[1:]]
    run = analyse_qa(qset([q1, q2]), answers, corpus(), topic_id=TOPIC)
    assert run.question_stats[q1.question_id]["kind"] == "too_thin"
    assert run.question_stats[q2.question_id]["kind"] == "no_significant_relation"
    assert "insufficient" not in {s["kind"] for s in run.question_stats.values()}


def test_unsupported_findings_are_emitted_after_the_pool():
    q1, q2 = question(1), question(2, key=None, tier="reader")
    # q1: clean 5v5 divergence (pool).
    answers = [answer(q1.question_id, c, "cat_a") for c in cn_clusters()]
    answers += [answer(q1.question_id, c, "cat_b") for c in us_clusters()]
    # q2: 1v1 different answers (unsupported appendix material).
    answers += [answer(q2.question_id, cn_clusters()[0], "x_thing")]
    answers += [answer(q2.question_id, c, None, addressed=False) for c in cn_clusters()[1:]]
    answers += [answer(q2.question_id, us_clusters()[0], "y_thing")]
    answers += [answer(q2.question_id, c, None, addressed=False) for c in us_clusters()[1:]]
    run = analyse_qa(qset([q1, q2]), answers, corpus(), topic_id=TOPIC)
    strengths = [f.strength for f in run.findings]
    assert FindingStrength.UNSUPPORTED in strengths
    first_unsupported = strengths.index(FindingStrength.UNSUPPORTED)
    assert all(s == FindingStrength.UNSUPPORTED for s in strengths[first_unsupported:])
    assert [f.rank for f in run.findings] == list(range(1, len(run.findings) + 1))


def test_kind_rotation_orders_the_pool():
    qs = [question(1), question(2, key=None, tier="reader"), question(3, key="consequences")]
    cn30, us30 = cn_clusters(30), us_clusters(30)
    answers = []
    # q1: divergence (5v5 among addressing clusters — the modal machine never reads
    # the addressed rate, so 5 of 30 anchors it as well as 5 of 5 would).
    answers += [answer(qs[0].question_id, c, "cat_a") for c in cn30[:5]]
    answers += [answer(qs[0].question_id, c, "cat_b") for c in us30[:5]]
    # q2: consensus.
    answers += [answer(qs[1].question_id, c, "cat_c") for c in cn30[:5]]
    answers += [answer(qs[1].question_id, c, "cat_c") for c in us30[:5]]
    # q3: total-silence attention gap (30 silent clusters clear the joint gate).
    answers += [answer(qs[2].question_id, c, "cat_d") for c in cn30]
    run = analyse_qa(qset(qs), answers, corpus(30, 30), topic_id=TOPIC)
    pool = [f for f in run.findings if f.strength != FindingStrength.UNSUPPORTED]
    assert [f.kind for f in pool[:3]] == [
        FindingKind.DIVERGENCE,
        FindingKind.CONSENSUS,
        FindingKind.ATTENTION_GAP,
    ]


def test_finding_identity_is_rank_free():
    q = question(3, key="consequences")
    answers = [answer(q.question_id, c, "cat_a") for c in cn_clusters()]
    answers += [answer(q.question_id, c, "cat_b") for c in us_clusters()]
    [finding] = analyse_qa(qset([q]), answers, corpus(), topic_id=TOPIC).findings
    assert finding.finding_id == "FND-aabb-river-light-003-divergence"


# --- category map (D-c) ----------------------------------------------------------------


def test_category_map_merges_before_counting():
    q = question(1)
    answers = [answer(q.question_id, c, "us_state_department") for c in cn_clusters(3)]
    answers += [answer(q.question_id, c, "us_government") for c in cn_clusters()[3:]]
    answers += [answer(q.question_id, c, "us_government") for c in us_clusters()]
    cmap = category_map(
        {
            q.question_id: [
                {
                    "canonical": "us_government",
                    "members": ["us_state_department"],
                    "rationale": {"text": "same actor", "lang": "en"},
                }
            ]
        }
    )
    run = analyse_qa(qset([q]), answers, corpus(), topic_id=TOPIC, category_map=cmap)
    [finding] = [f for f in run.findings if f.kind != FindingKind.ATTENTION_GAP]
    assert finding.kind == FindingKind.CONSENSUS
    cn = next(g for g in finding.groups if g.group_id == "cn")
    assert cn.category_counts == {"us_government": 5}
    stats = run.question_stats[q.question_id]["groups"]["cn"]
    assert stats["category_counts_raw"] == {"us_government": 2, "us_state_department": 3}
    assert stats["category_counts"] == {"us_government": 5}
    assert run.inputs["category_map_run_id"] == "ans-202608200000-00000001"
    assert "category_map_hash" in run.inputs


def test_merge_sensitive_flags_an_outcome_that_flips_with_the_map():
    """cn raw: 3 emperor_skeptical / 2 deliberate_use / 4 official_line — merged,
    skeptical+deliberate (5) beats official_line (4) and the top flips."""
    q = question(1)
    cn9 = [f"RC-CN-{i:08x}" for i in range(9)]
    us9 = [f"RC-US-{i:08x}" for i in range(9)]
    answers = [answer(q.question_id, c, "emperor_skeptical") for c in cn9[:3]]
    answers += [answer(q.question_id, c, "deliberate_use") for c in cn9[3:5]]
    answers += [answer(q.question_id, c, "official_line") for c in cn9[5:]]
    answers += [answer(q.question_id, c, "official_line") for c in us9]
    cmap = category_map(
        {
            q.question_id: [
                {
                    "canonical": "emperor_skeptical",
                    "members": ["deliberate_use"],
                    "rationale": {"text": "same reading", "lang": "en"},
                }
            ]
        }
    )
    big = corpus(9, 9)
    merged_run = analyse_qa(qset([q]), answers, big, topic_id=TOPIC, category_map=cmap)
    [merged] = [f for f in merged_run.findings if f.kind != FindingKind.ATTENTION_GAP]
    assert merged.merge_sensitive is True
    plain_run = analyse_qa(qset([q]), answers, big, topic_id=TOPIC)
    [plain] = [f for f in plain_run.findings if f.kind != FindingKind.ATTENTION_GAP]
    assert plain.merge_sensitive is False


# --- D-a: every cluster counts ---------------------------------------------------------


def test_peripheral_clusters_are_back_in_the_denominator():
    q = question(1)
    answers = [answer(q.question_id, c, "chinese_government") for c in cn_clusters()]
    answers += [answer(q.question_id, c, "trump_administration") for c in us_clusters()]
    run = analyse_qa(
        qset([q]), answers, corpus_with_peripheral(set(cn_clusters()[-2:])), topic_id=TOPIC
    )
    cn = next(g for g in run.findings[0].groups if g.group_id == "cn")
    assert cn.clusters_total == 5
    assert run.inputs["counted_clusters"] == 10
    assert run.inputs["peripheral_clusters_excluded"] == []


# --- the readable universe -------------------------------------------------------------


def full_access(run: CorpusRun, partial: set[str] = frozenset()) -> dict[str, str]:
    """article_id -> access level; ``partial`` names the partial-only *clusters*."""
    return {
        a.article_id: "partial" if a.reporting_cluster_id in partial else "full"
        for a in run.articles
    }


def test_partial_only_clusters_leave_numerator_and_denominator_together():
    q = question(1)
    big = corpus(5, 5)
    partial = {cn_clusters()[0]}
    # The partial cluster *answered* — its answer must not be counted anyway.
    answers = [answer(q.question_id, c, "chinese_government") for c in cn_clusters()]
    answers += [answer(q.question_id, c, "trump_administration") for c in us_clusters()]
    run = analyse_qa(
        qset([q]), answers, big, topic_id=TOPIC, access_levels=full_access(big, partial)
    )
    cn = next(g for g in run.findings[0].groups if g.group_id == "cn")
    assert cn.clusters_total == 4
    assert cn.clusters_addressed == 4  # the partial cluster's answer left with it
    assert cn.category_counts == {"chinese_government": 4}
    assert run.inputs["counted_clusters"] == 9
    assert run.inputs["unreadable_clusters_excluded"] == sorted(partial)


def test_one_full_member_keeps_a_cluster_readable():
    """Same "any" rule as cluster_relevance: one fully readable carrier suffices."""
    q = question(1)
    base = corpus(2, 2)
    # Give the first cn cluster a second, partial member alongside its full one.
    extra = base.articles[0].model_copy(update={"article_id": "CN_ffffffff"})
    articles = sorted(base.articles + [extra], key=lambda a: a.article_id)
    big = base.model_copy(update={
        "articles": articles,
        "set_hash": compute_set_hash({a.article_id: a.content_hash for a in articles}),
    })
    access = {a.article_id: "full" for a in base.articles}
    access["CN_ffffffff"] = "partial"
    answers = [answer(q.question_id, c, "cat_x") for c in cn_clusters(2)]
    answers += [answer(q.question_id, c, "cat_x") for c in us_clusters(2)]
    run = analyse_qa(qset([q]), answers, big, topic_id=TOPIC, access_levels=access)
    assert run.inputs["counted_clusters"] == 4
    assert run.inputs["unreadable_clusters_excluded"] == []


# --- experiment: the absolute loud-side floor (loud_min_rate) --------------------------


def test_loud_min_rate_replaces_the_difference_clause():
    """quiet 0/12 vs loud 5/12 (observed 0.42): the posterior puts ~0.8 of its mass
    at loud ≥ 0.30 but only ~0.5 at loud ≥ 0.40, so lmin=0.30 fires and lmin=0.40
    does not.  With lmin set, ``attention_gap_min_abs_diff`` is not consulted at all —
    an absurd mdiff must change nothing."""
    q = question(1)
    big = corpus(12, 12)
    answers = [answer(q.question_id, c, "cat_x") for c in cn_clusters(12)[:5]]
    answers += [answer(q.question_id, c, None, addressed=False) for c in cn_clusters(12)[5:]]
    answers += [answer(q.question_id, c, None, addressed=False) for c in us_clusters(12)]

    def run_with(**kw):
        t = QAThresholds(**kw)
        r = analyse_qa(qset([q]), answers, big, topic_id=TOPIC, thresholds=t)
        return r.question_stats[q.question_id]

    fires_030 = run_with(loud_min_rate=0.30)
    assert fires_030["attention_gap"] is True
    assert fires_030["attention_gap_quiet_group"] == "us"
    not_040 = run_with(loud_min_rate=0.40)
    assert not_040["attention_gap"] is False
    # mdiff is dead while lmin is in force: same stream, same numbers.
    with_absurd_mdiff = run_with(loud_min_rate=0.30, attention_gap_min_abs_diff=0.99)
    assert with_absurd_mdiff["attention_gap_stability"] == fires_030["attention_gap_stability"]


# --- the answers run is on the record --------------------------------------------------


def test_run_record_names_the_answers_run_it_analysed():
    q = question(1)
    answers = [answer(q.question_id, c, "chinese_government") for c in cn_clusters()]
    answers += [answer(q.question_id, c, "trump_administration") for c in us_clusters()]
    run = analyse_qa(
        qset([q]),
        answers,
        corpus(),
        topic_id=TOPIC,
        answers_run_id="ans-20260830180740972325-7a408f62",
    )
    assert run.inputs["answers_run_id"] == "ans-20260830180740972325-7a408f62"
    assert run.run_record()["inputs"]["answers_run_id"] == "ans-20260830180740972325-7a408f62"


def test_answers_run_id_is_present_even_when_the_caller_has_none():
    # The key is always on the record: a reader must be able to tell "this run predates
    # the field" from "this run analysed answers run X", and a missing key cannot say either.
    q = question(1)
    answers = [answer(q.question_id, c, "chinese_government") for c in cn_clusters()]
    run = analyse_qa(qset([q]), answers, corpus(), topic_id=TOPIC)
    assert run.inputs["answers_run_id"] is None
