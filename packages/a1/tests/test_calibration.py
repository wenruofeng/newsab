"""The calibration harness. The numbers are absent until a scored corpus exists; the
machinery is not."""

import pytest

from conftest import CorpusBuilder
from newsab_a1 import build_feature_matrix, calibration_report, gate_agreement, scan_all, spearman
from newsab_a1.calibration import threshold_sweep
from newsab_a1.rgate import RGateThresholds


def test_spearman_handles_ties_and_short_inputs():
    assert spearman([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 1], [1, 2, 3]) is None  # no spread to speak of
    assert spearman([1, 2], [1, 2]) is None  # too few points


def test_threshold_sweep_surfaces_the_recall_cost():
    values = {"a": 0.9, "b": 0.6, "c": 0.2, "d": 0.1}
    defensible = {"a": 5.0, "b": 4.0, "c": 5.0, "d": 2.0}
    sweep = {p.threshold: p for p in threshold_sweep(values, defensible)}
    # A 0.5 cut-off keeps two of the three findings the user called well-evidenced.
    assert sweep[0.5].recall == pytest.approx(2 / 3)
    assert sweep[0.0].recall == pytest.approx(1.0)


def test_calibration_report_warns_when_the_gold_set_is_too_small():
    builder = CorpusBuilder()
    builder.add_group("us", clusters=10, supporting=8, sources=10)
    builder.add_group("cn", clusters=10, supporting=2, sources=10)
    matrix = build_feature_matrix(
        builder.observations, builder.articles, builder.snapshot(), builder.ontology()
    )
    candidates = scan_all(matrix, "us", "cn")
    defensible = {candidates[0].candidate_id: 5.0}

    report = calibration_report(
        matrix, "us", "cn", defensible, n_resample_options=(50,), stratification_options=(True,)
    )
    assert any("indicative at best" in note for note in report.notes)
    assert report.signal_scores
    assert set(report.sweeps) == {
        "conservative_effect",
        "abs_delta",
        "direction_stability",
    }


def test_gate_agreement_counts_findings_the_gate_threw_away():
    """The asymmetry that matters: defensible findings rejected before anyone read them."""
    builder = CorpusBuilder()
    builder.add_group("us", clusters=12, supporting=7, sources=12)
    builder.add_group("cn", clusters=12, supporting=6, sources=12)
    matrix = build_feature_matrix(
        builder.observations, builder.articles, builder.snapshot(), builder.ontology()
    )
    candidates = scan_all(matrix, "us", "cn")
    defensible = {c.candidate_id: 5.0 for c in candidates}

    agreement = gate_agreement(candidates, RGateThresholds.load(), defensible)
    assert agreement["rejected_but_defensible"] > 0
    assert agreement["false_rejections"][0]["failed_checks"]
