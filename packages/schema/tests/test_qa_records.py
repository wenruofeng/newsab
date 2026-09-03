"""Q×A model invariants (value_chain.md V-1)."""

from __future__ import annotations

import pytest
from conftest import make_article, provenance

from newsab_schema.models.qa import (
    ANSWER_CATEGORY_UNCLEAR,
    ClusterAnswer,
    Question,
    QuestionSet,
    validate_answer_category,
)
from newsab_schema.validate import validate_answers

TOPIC = "aabb-river-light-2026"


def make_question(
    question_id: str = "QST-aabb-river-light-001",
    tier: str = "template",
    template_key: str | None = "problem_definition",
    status: str = "active",
    text: dict | None = None,
) -> Question:
    return Question.model_validate(
        {
            "question_id": question_id,
            "topic_id": TOPIC,
            "tier": tier,
            "template_key": template_key,
            "text": {"values": text or {"en": "What is the problem?", "zh-CN": "问题是什么？"}},
            "rationale": {"text": "template standard", "lang": "en"},
            "status": status,
            "provenance": provenance(skill="annotate-0.1.0"),
        }
    )


def make_answer(**overrides) -> ClusterAnswer:
    payload = {
        "answer_id": "ANS-aabb-river-light-000001",
        "topic_id": TOPIC,
        "question_id": "QST-aabb-river-light-001",
        "question_set_version": "qst-202608200000-abcdef01",
        "reporting_cluster_id": "RC-CN-001",
        "group_id": "cn",
        "addressed": True,
        "answer_summary": {"text": "新规改变签证停留方式。", "lang": "zh-CN"},
        "answer_category": "policy_change",
        "evidence": ["CN_001:P01:S01"],
        "confidence": 0.9,
        "provenance": provenance(skill="annotate-0.1.0"),
    }
    payload.update(overrides)
    return ClusterAnswer.model_validate(payload)


# --- Question -----------------------------------------------------------------------


def test_template_question_needs_key():
    with pytest.raises(ValueError, match="template_key"):
        make_question(template_key=None)


def test_reader_question_rejects_key():
    with pytest.raises(ValueError, match="template_key"):
        make_question(tier="reader", template_key="responsibility")


def test_question_requires_english_pivot():
    with pytest.raises(ValueError, match="pivot"):
        make_question(text={"zh-CN": "问题是什么？"})


def test_question_set_rejects_duplicate_active_template_key():
    q1 = make_question()
    q2 = make_question(question_id="QST-aabb-river-light-002")
    with pytest.raises(ValueError, match="instantiated twice"):
        QuestionSet(
            topic_id=TOPIC,
            question_set_version="qst-202608200000-abcdef01",
            questions=[q1, q2],
            provenance=provenance(skill="annotate-0.1.0"),
        )


def test_question_set_allows_retired_duplicate_key():
    q1 = make_question()
    q2 = make_question(question_id="QST-aabb-river-light-002", status="retired")
    qs = QuestionSet(
        topic_id=TOPIC,
        question_set_version="qst-202608200000-abcdef01",
        questions=[q1, q2],
        provenance=provenance(skill="annotate-0.1.0"),
    )
    assert [q.question_id for q in qs.active] == ["QST-aabb-river-light-001"]


# --- ClusterAnswer ------------------------------------------------------------------


def test_addressed_requires_summary_category_evidence():
    with pytest.raises(ValueError, match="addressed=true requires"):
        make_answer(answer_summary=None)
    with pytest.raises(ValueError, match="addressed=true requires"):
        make_answer(answer_category=None)
    with pytest.raises(ValueError, match="addressed=true requires"):
        make_answer(evidence=[])


def test_silence_carries_nothing():
    silent = make_answer(
        addressed=False, answer_summary=None, answer_category=None, evidence=[]
    )
    assert not silent.is_comparable
    with pytest.raises(ValueError, match="addressed=false"):
        make_answer(addressed=False, answer_summary=None, answer_category=None)


def test_group_must_match_cluster():
    with pytest.raises(ValueError, match="does not match cluster"):
        make_answer(group_id="us")


def test_evidence_must_stay_in_group():
    with pytest.raises(ValueError, match="foreign anchors"):
        make_answer(evidence=["US_002:P01:S01"])


def test_unclear_is_not_comparable():
    answer = make_answer(answer_category=ANSWER_CATEGORY_UNCLEAR)
    assert answer.addressed and not answer.is_comparable


def test_answer_category_grammar():
    assert validate_answer_category("us_government") == "us_government"
    with pytest.raises(ValueError):
        validate_answer_category("US government")


# --- validate_answers ----------------------------------------------------------------


def _question_set() -> QuestionSet:
    return QuestionSet(
        topic_id=TOPIC,
        question_set_version="qst-202608200000-abcdef01",
        questions=[make_question()],
        provenance=provenance(skill="annotate-0.1.0"),
    )


def test_validate_answers_clean():
    articles = [make_article()]
    report = validate_answers(
        [make_answer()],
        _question_set(),
        articles,
        cluster_assignment={"CN_001": "RC-CN-001"},
    )
    assert not report.errors, report.render()


def test_validate_answers_coverage_gap_and_dangling_anchor():
    articles = [make_article()]
    report = validate_answers(
        [make_answer(evidence=["CN_001:P09:S09"])],
        _question_set(),
        articles,
        cluster_assignment={"CN_001": "RC-CN-001", "CN_002": "RC-CN-002"},
    )
    codes = {f.code for f in report.errors}
    assert "dangling_anchor" in codes
    assert "coverage_gap" in codes


def test_coverage_scope_can_be_narrowed_to_the_questions_a_shard_owns():
    """An incremental shard answers new questions only; carried ones are not its holes.

    Without this the shard is measured against every active question, so its check can
    never come back clean and each worker invents its own way of reading past the noise
    (four workers, four different workarounds).
    """
    articles = [make_article()]
    question_set = QuestionSet.model_validate(
        {
            "topic_id": TOPIC,
            "question_set_version": "qst-202608200000-abcdef01",
            "questions": [
                make_question(),
                make_question(question_id="QST-aabb-river-light-002", tier="reader",
                              template_key=None),
            ],
            "provenance": provenance(skill="annotate-0.1.0"),
        }
    )
    carried_only = [make_answer()]  # answers -001 but not -002

    wide = validate_answers(
        carried_only, question_set, articles,
        cluster_assignment={"CN_001": "RC-CN-001"},
    )
    assert "coverage_gap" in {f.code for f in wide.errors}

    scoped = validate_answers(
        carried_only, question_set, articles,
        cluster_assignment={"CN_001": "RC-CN-001"},
        scope_questions=["QST-aabb-river-light-001"],
    )
    assert not scoped.errors, scoped.render()

    # A scope naming something that is not an active question is itself an error, so a
    # typo cannot silently excuse the coverage it was meant to check.
    typo = validate_answers(
        carried_only, question_set, articles,
        cluster_assignment={"CN_001": "RC-CN-001"},
        scope_questions=["QST-aabb-river-light-999"],
    )
    assert "unknown_scope_question" in {f.code for f in typo.errors}


def test_validate_answers_accepts_english_pivot_and_checks_version():
    articles = [make_article()]
    report = validate_answers(
        [
            make_answer(
                question_set_version="qst-202608200001-ffffffff",
                answer_summary={"text": "An English summary.", "lang": "en"},
            )
        ],
        _question_set(),
        articles,
        cluster_assignment={"CN_001": "RC-CN-001"},
    )
    codes = {f.code for f in report.errors}
    assert "question_set_mismatch" in codes
    assert "summary_language" not in codes


def test_validate_answers_anchor_outside_cluster():
    articles = [make_article(), make_article(article_id="CN_002", cluster="RC-CN-002")]
    report = validate_answers(
        [make_answer(evidence=["CN_001:P01:S01", "CN_002:P01:S01"])],
        _question_set(),
        articles,
        cluster_assignment={"CN_001": "RC-CN-001", "CN_002": "RC-CN-002"},
    )
    codes = {f.code for f in report.errors}
    assert "anchor_outside_cluster" in codes
