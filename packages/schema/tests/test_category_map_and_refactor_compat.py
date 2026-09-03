"""Analyze-refactor schema changes: CategoryMap invariants, the relaxed
FND grammar, retired-field optionality, and historical-run deserialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import provenance

from newsab_schema.ids import IdError, parse_prefixed_id
from newsab_schema.models.category_map import CategoryMap, CategoryMerge
from newsab_schema.models.findings import QAFinding
from newsab_schema.models.qa import ClusterAnswer

TOPIC = "aabb-river-light-2026"

REPO_ROOT = Path(__file__).resolve().parents[3]
TOPICS_ROOT = REPO_ROOT / "topics"


def merge(canonical="us_government", members=("us_state_department",), why="same actor"):
    return {
        "canonical": canonical,
        "members": list(members),
        "rationale": {"text": why, "lang": "en"},
    }


def make_map(merges: dict | None = None) -> CategoryMap:
    return CategoryMap.model_validate(
        {
            "topic_id": TOPIC,
            "question_set_version": "qst-202608200000-abcdef01",
            "answers_run_id": "ans-202608200000-00000001",
            "merges": merges if merges is not None else {},
            "provenance": provenance(skill="normalize-0.1.0"),
        }
    )


# --- CategoryMap --------------------------------------------------------------------


def test_empty_map_is_valid_and_projects_identity():
    m = make_map()
    assert m.project("QST-aabb-river-light-001", "anything_here") == "anything_here"


def test_projection_maps_members_and_leaves_the_rest():
    m = make_map({"QST-aabb-river-light-001": [merge()]})
    assert m.project("QST-aabb-river-light-001", "us_state_department") == "us_government"
    assert m.project("QST-aabb-river-light-001", "us_government") == "us_government"
    assert m.project("QST-aabb-river-light-001", "unrelated") == "unrelated"
    # Another question is untouched — merges are per-question.
    assert m.project("QST-aabb-river-light-002", "us_state_department") == "us_state_department"


def test_a_member_may_not_appear_in_two_groups():
    with pytest.raises(ValueError, match="two merge groups"):
        make_map(
            {
                "QST-aabb-river-light-001": [
                    merge("us_government", ["shared_member"]),
                    merge("chinese_government", ["shared_member"]),
                ]
            }
        )


def test_merges_may_not_chain():
    with pytest.raises(ValueError, match="chain"):
        make_map(
            {
                "QST-aabb-river-light-001": [
                    merge("a_concept", ["b_concept"]),
                    merge("b_concept", ["c_concept"]),
                ]
            }
        )


def test_unclear_never_participates():
    with pytest.raises(ValueError, match="unclear"):
        CategoryMerge.model_validate(merge("unclear", ["something"]))
    with pytest.raises(ValueError, match="unclear"):
        CategoryMerge.model_validate(merge("something", ["unclear"]))


def test_a_map_is_an_agent_product():
    with pytest.raises(ValueError, match="model_id"):
        CategoryMap.model_validate(
            {
                "topic_id": TOPIC,
                "question_set_version": "v",
                "answers_run_id": "r",
                "merges": {},
                "provenance": provenance(skill="normalize-0.1.0", model=None),
            }
        )


# --- FND grammar --------------------------------------------------------------------


def test_legacy_fnd_ids_still_parse():
    parsed = parse_prefixed_id("FND-aabb-river-light-001", "FND")
    assert (parsed.topic_slug, parsed.serial, parsed.suffix) == ("aabb-river-light", 1, None)
    assert str(parsed) == "FND-aabb-river-light-001"


def test_kind_suffixed_fnd_ids_parse():
    parsed = parse_prefixed_id("FND-aabb-river-light-003-attention_gap", "FND")
    assert (parsed.topic_slug, parsed.serial, parsed.suffix) == ("aabb-river-light", 3, "attention_gap")
    assert str(parsed) == "FND-aabb-river-light-003-attention_gap"
    # A digit-bearing slug segment stays on the slug side of the serial.
    parsed = parse_prefixed_id("FND-cnea-sharifu-005-divergence", "FND")
    assert (parsed.topic_slug, parsed.serial, parsed.suffix) == ("cnea-sharifu", 5, "divergence")


def test_the_suffix_is_fnd_only():
    with pytest.raises(IdError):
        parse_prefixed_id("QST-aabb-river-light-001-divergence", "QST")


# --- retired fields -----------------------------------------------------------------


def test_new_answers_need_no_confidence():
    ClusterAnswer.model_validate(
        {
            "answer_id": "ANS-aabb-river-light-000001",
            "topic_id": TOPIC,
            "question_id": "QST-aabb-river-light-001",
            "question_set_version": "qst-202608200000-abcdef01",
            "reporting_cluster_id": "RC-CN-001",
            "group_id": "cn",
            "addressed": False,
            "provenance": provenance(skill="annotate-0.1.0"),
        }
    )


# --- serialized synthetic records deserialize under the compatibility defaults --------


def test_a_serialized_pre_flag_finding_still_deserializes():
    raw = {
        "finding_id": "FND-aabb-river-light-001-divergence",
        "topic_id": TOPIC,
        "question_id": "QST-aabb-river-light-001",
        "kind": "divergence",
        "strength": "supported",
        "rank": 1,
        "groups": [
            {
                "group_id": group,
                "clusters_total": 3,
                "clusters_addressed": 3,
                "category_counts": {answer: 3},
                "sample_evidence": [f"{group.upper()}_00000001:P01:S01"],
            }
            for group, answer in (("aa", "bridge_lights"), ("bb", "dark_sky"))
        ],
        "stability": 0.99,
        "summary": {"text": "The two synthetic samples give different answers.", "lang": "en"},
        "thresholds_version": "qa-fixture-0.1.0",
        "provenance": provenance(skill="analyze-0.1.0", model=None).model_dump(mode="json"),
    }
    record = QAFinding.model_validate_json(json.dumps(raw))
    assert record.merge_sensitive is False
    assert record.total_silence is False
