"""§4.4 / §4.4.1 / §4.5 — angle lifecycle, selection constraints, claim provenance."""

import pytest
from pydantic import ValidationError

from conftest import NOW, make_article, provenance
from newsab_schema import CandidateAngle, Claim
from newsab_schema.validate import check_selection_constraints, validate_angles, validate_claims

METRICS = {
    "prevalence": {"us": 0.654, "cn": 0.19, "method": "A1-0.3.0/cluster_prevalence"},
    "delta": {
        "group_a": "us",
        "group_b": "cn",
        "value": 0.46,
        "lo": 0.21,
        "hi": 0.68,
        "level": 0.95,
        "method": "A1-0.3.0/signed_prevalence_diff",
    },
    "direction_stability": 0.95,
    "conservative_effect": 0.21,
    "log_odds": 2.05,
    "concentration": {"us": 0.81, "cn": 0.64, "method": "A1-0.3.0/eff_publishers"},
    "resampling": {
        "n_resamples": 2000,
        "seed": 20260817,
        "scheme": "stratified_by_category_over_clusters",
    },
    "a1_run_id": "a1-202608171930-9f3ac10b",
}

COMPARISON = {
    "feature": {"dimension": "problem_definition", "concept_id": "national_security"},
    "groups": [
        {
            "group_id": "us",
            "clusters_supporting": 17,
            "clusters_total": 26,
            "by_category": {"serious": "11/16", "other": "6/10"},
        },
        {"group_id": "cn", "clusters_supporting": 4, "clusters_total": 21},
    ],
}


def angle(
    serial=7,
    angle_type="problem_definition",
    status="shortlisted",
    cluster="SC-03",
    scored=True,
    r_passed=True,
    **extra,
):
    payload = {
        "angle_id": f"ANG-aabb-river-light-{serial:04d}",
        "topic_id": "aabb-river-light-2026",
        "origin": "data_discovered",
        "angle_type": angle_type,
        "comparison": COMPARISON,
        "metrics": METRICS,
        "r_gate": (
            {
                "passed": True,
                "thresholds_version": "rgate-0.2",
                "reading": "divergence",
                "failed_checks": [],
            }
            if r_passed
            else {
                "passed": False,
                "thresholds_version": "rgate-0.2",
                "reading": "insufficient",
                "failed_checks": ["reading=insufficient"],
            }
        ),
        "semantic_cluster_id": cluster,
        "editorial": (
            {
                "question": {"values": {"en": "What problem is this first about?"}},
                "e_score": {
                    "surprise": 2,
                    "relevance": 1,
                    "non_redundancy": 2,
                    "story_potential": 2,
                    "rubric_version": "escore-0.2",
                },
                "recommended_visual": "paired_ranked_concepts",
            }
            if scored
            else None
        ),
        "supporting_observations": ["OBS-aabb-river-light-000812"],
        "exceptions": [],
        "selection": {"status": status, "constraint_roles": [f"covers_type:{angle_type}"]},
        "provenance": provenance("S6-0.1.0").model_dump(mode="json"),
    }
    payload.update(extra)
    return CandidateAngle.model_validate(payload)


def test_support_counts_round_trip_the_blueprint_string_form():
    a = angle()
    us = a.comparison.group("us")
    assert us.by_category["serious"].share == 11 / 16
    assert a.model_dump(mode="json")["comparison"]["groups"][0]["by_category"]["serious"] == "11/16"


def test_d8_a_failed_r_gate_can_never_be_shortlisted():
    with pytest.raises(ValidationError, match="may not lower the evidence bar"):
        angle(r_passed=False)


def test_shortlisting_requires_an_e_score():
    with pytest.raises(ValidationError, match="requires editorial.e_score"):
        angle(scored=False)


def test_blind_spot_needs_all_four_conditions_before_shortlisting():
    conditions = {
        name: {"passed": True, "note": {"text": "checked", "lang": "en"}}
        for name in (
            "same_event_stage",
            "opportunity_to_cover",
            "category_composition",
            "not_single_wire_amplified",
        )
    }
    ok = angle(angle_type="blind_spot", blind_spot_check=conditions)
    assert ok.blind_spot_check.all_passed

    conditions["opportunity_to_cover"] = {
        "passed": False,
        "note": {"text": "no adjacent context found", "lang": "en"},
    }
    with pytest.raises(ValidationError, match="failed conditions"):
        angle(angle_type="blind_spot", blind_spot_check=conditions)


def test_blind_spot_check_is_meaningless_on_other_angle_types():
    with pytest.raises(ValidationError, match="only meaningful"):
        angle(
            angle_type="stance",
            blind_spot_check={
                name: {"passed": True, "note": {"text": "x", "lang": "en"}}
                for name in (
                    "same_event_stage",
                    "opportunity_to_cover",
                    "category_composition",
                    "not_single_wire_amplified",
                )
            },
        )


def test_invariant_4_exceptions_cannot_be_a_placeholder():
    with pytest.raises(ValidationError, match="empty string placeholder"):
        angle(exceptions=[""])


def test_zero_clusters_is_an_absent_denominator_not_zero_prevalence():
    a = angle(
        comparison={
            "feature": {"dimension": "stance"},
            "groups": [
                {"group_id": "us", "clusters_supporting": 0, "clusters_total": 0},
                {"group_id": "cn", "clusters_supporting": 4, "clusters_total": 21},
            ],
        }
    )
    assert a.comparison.group("us").prevalence is None


def test_a_conflict_only_set_is_reported_as_an_unmet_goal_not_a_failure():
    """D22: a set with no voice/actor angle is a shape worth telling G2 about, but
    the label string it is measured by is an artifact of the reading→type mapping,
    so it must not block the run."""
    angles = [
        angle(serial=1, angle_type="problem_definition", cluster="SC-01"),
        angle(serial=2, angle_type="stance", cluster="SC-02"),
        angle(serial=3, angle_type="consequence", cluster="SC-03"),
        angle(serial=4, angle_type="terminology", cluster="SC-04"),
        angle(serial=5, angle_type="salience", cluster="SC-05"),
    ]
    report = check_selection_constraints(angles, "aabb-river-light-2026")
    assert report.satisfied, report.failures()
    assert report.failures() == []
    assert set(report.unmet_goals()) == {
        "at_least_one_voice_or_actor",
        "shared_ground_editorial_goal",
    }
    goal = next(r for r in report.results if r.name == "at_least_one_voice_or_actor")
    assert goal.satisfied and goal.goal_met is False and "not met" in goal.detail


def test_an_undersized_set_does_not_fail_the_run():
    """D22: set_size is a yardstick for the report, not a gate. Going back for another
    round when a set is genuinely thin stays an agent obligation (runbook §5), not a
    schema-level refusal."""
    angles = [
        angle(serial=1, angle_type="problem_definition", cluster="SC-01"),
        angle(serial=2, angle_type="voice_structure", cluster="SC-02"),
        angle(serial=3, angle_type="shared_ground", cluster="SC-03"),
    ]
    report = check_selection_constraints(angles, "aabb-river-light-2026")
    assert report.satisfied, report.failures()
    assert report.unmet_goals() == ["set_size"]
    size = next(r for r in report.results if r.name == "set_size")
    assert "3 angles selected" in size.detail and "5–8" in size.detail


def test_an_unclustered_selected_angle_still_fails_the_run():
    """D22 leaves exactly one fatal row: an angle that never went through semantic
    clustering is an incomplete artifact, not an editorial judgement call."""
    angles = [
        angle(serial=1, angle_type="problem_definition", cluster="SC-01"),
        angle(serial=2, angle_type="voice_structure", cluster="SC-02"),
        angle(serial=3, angle_type="shared_ground", cluster="SC-03"),
        angle(serial=4, angle_type="consequence", cluster="SC-04"),
        angle(serial=5, angle_type="terminology", cluster=None),
    ]
    report = check_selection_constraints(angles, "aabb-river-light-2026")
    assert not report.satisfied
    assert report.failures() == ["all_selected_are_clustered"]


def test_missing_shared_ground_is_reported_as_an_unmet_goal_not_a_failure():
    """R-8: with current corpus sizes statistical consensus is structurally
    unreachable (G-5), so its absence must not fail the run — but G2 must still see it."""
    angles = [
        angle(serial=1, angle_type="problem_definition", cluster="SC-01"),
        angle(serial=2, angle_type="voice_structure", cluster="SC-02"),
        angle(serial=3, angle_type="stance", cluster="SC-03"),
        angle(serial=4, angle_type="consequence", cluster="SC-04"),
        angle(serial=5, angle_type="terminology", cluster="SC-05"),
    ]
    report = check_selection_constraints(angles, "aabb-river-light-2026")
    assert report.satisfied, report.failures()
    goal = next(r for r in report.results if r.name == "shared_ground_editorial_goal")
    assert goal.satisfied and "not met" in goal.detail


def test_selection_constraints_accept_a_balanced_set():
    angles = [
        angle(serial=1, angle_type="problem_definition", cluster="SC-01"),
        angle(serial=2, angle_type="voice_structure", cluster="SC-02"),
        angle(serial=3, angle_type="shared_ground", cluster="SC-03"),
        angle(serial=4, angle_type="consequence", cluster="SC-04"),
        angle(serial=5, angle_type="terminology", cluster="SC-05"),
    ]
    report = check_selection_constraints(angles, "aabb-river-light-2026")
    assert report.satisfied, report.failures()
    assert report.to_dict()["satisfied"] is True
    goal = next(r for r in report.results if r.name == "shared_ground_editorial_goal")
    assert "met" in goal.detail


def test_no_more_than_two_angles_from_one_semantic_cluster():
    angles = [
        angle(serial=1, angle_type="problem_definition", cluster="SC-01"),
        angle(serial=2, angle_type="voice_structure", cluster="SC-01"),
        angle(serial=3, angle_type="shared_ground", cluster="SC-01"),
        angle(serial=4, angle_type="consequence", cluster="SC-02"),
        angle(serial=5, angle_type="terminology", cluster="SC-03"),
    ]
    report = check_selection_constraints(angles, "aabb-river-light-2026")
    # D22: measured and reported to G2, but three paraphrases of one story no longer stop
    # the run — the redundancy check in check_selection.py is the sharper instrument here,
    # because it compares supporting observations rather than cluster labels.
    assert "max_per_semantic_cluster" in report.unmet_goals()
    assert report.failures() == []


def test_constraint_report_is_attached_to_the_validation_stats():
    report = validate_angles([angle()], "aabb-river-light-2026")
    assert "constraint_report" in report.stats
    assert any(f.code == "metrics_not_recomputed" for f in report.warnings)


def test_recompute_hook_catches_an_edited_number():
    def recompute(_a):
        return {"delta": 0.20}

    report = validate_angles([angle()], "aabb-river-light-2026", recompute=recompute)
    assert any(f.code == "metric_recompute_mismatch" for f in report.errors)


# --- claims ---------------------------------------------------------------------------


def claim(**extra):
    payload = {
        "claim_id": "CLM-aabb-river-light-0390",
        "angle_id": "ANG-aabb-river-light-0007",
        "topic_id": "aabb-river-light-2026",
        "text": {
            "values": {
                "en": "In the sampled US coverage, the policy was more often defined as a "
                "national-security issue than in the sampled Chinese coverage."
            }
        },
        "claim_type": "corpus_aggregate",
        "computed_from": "ANG-aabb-river-light-0007.metrics",
        "evidence": ["CN_001:P01:S01"],
        "quantifier_check": {
            "phrase": "more often",
            "bound_to": "divergence=0.46",
            "lint": "pass",
        },
        "provenance": provenance("S7-0.1.0").model_dump(mode="json"),
    }
    payload.update(extra)
    return Claim.model_validate(payload)


def test_aggregate_claim_needs_a_metric_and_source_claim_must_not_have_one():
    with pytest.raises(ValidationError, match="computed_from"):
        claim(computed_from=None)
    with pytest.raises(ValidationError, match="whole basis"):
        claim(claim_type="source_claim")


def test_claim_evidence_must_be_sentence_ids_not_urls():
    with pytest.raises(ValidationError, match="free-form URL citation is forbidden"):
        claim(evidence=["https://example.com/a"])


def test_claim_validation_binds_quantifiers_to_the_angle_metrics():
    a = angle()
    good = validate_claims([claim()], [make_article()], [a])
    assert good.ok(), good.render()

    overstated = claim(
        text={
            "values": {
                "en": "In the sampled US coverage, almost all clusters defined it as a "
                "national-security issue."
            }
        }
    )
    report = validate_claims([overstated], [make_article()], [a])
    assert any(f.code == "lint_quantifier_range" for f in report.errors)


def test_claim_with_a_country_subject_fails_the_scope_lint():
    report = validate_claims(
        [claim(text={"values": {"en": "China believes the policy is hostile."}}, claim_type="corpus_aggregate")],
        [make_article()],
        [angle()],
    )
    assert any(f.code == "lint_scope_subject" for f in report.errors)
