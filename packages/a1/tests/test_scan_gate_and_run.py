"""Scans, the R-gate, and the reproducibility promise behind `a1_run_id`."""

import json
from dataclasses import replace

import pytest

from conftest import CorpusBuilder
from newsab_a1 import (
    RGateThresholds,
    ScanConfig,
    analyse,
    build_feature_matrix,
    evaluate,
    evaluate_all,
    rank_passed,
    recompute_metrics,
    scan_all,
    summarise,
    write_run,
)
from newsab_a1.rgate import UncalibratedGateError
from newsab_schema.models.analysis import Feature


def matrix_of(builder):
    return build_feature_matrix(
        builder.observations, builder.articles, builder.snapshot(), builder.ontology()
    )


def by_feature(candidates, key):
    return next(c for c in candidates if c.feature.key == key)


BARE_PD = Feature(dimension="problem_definition").key


def _strong_builder() -> CorpusBuilder:
    b = CorpusBuilder()
    b.add_group("us", clusters=14, supporting=12, sources=12, category="serious")
    b.add_group("cn", clusters=14, supporting=2, sources=12, category="serious")
    b.add_group("us", clusters=6, supporting=5, sources=6, category="other")
    b.add_group("cn", clusters=6, supporting=1, sources=6, category="other")
    return b


@pytest.fixture
def strong():
    """A fresh builder, for the tests that mutate it before scanning."""
    return _strong_builder()


# The scan's bootstrap intervals dominate this file's runtime, so the tests that
# never mutate the corpus share one matrix / one scan / one analysed run per module.


@pytest.fixture(scope="module")
def strong_matrix():
    return matrix_of(_strong_builder())


@pytest.fixture(scope="module")
def strong_candidates(strong_matrix):
    return scan_all(strong_matrix, "us", "cn")


@pytest.fixture(scope="module")
def strong_run():
    b = _strong_builder()
    return analyse(
        b.observations,
        b.articles,
        b.snapshot(),
        b.ontology(),
        config=ScanConfig(n_resamples=200),
        groups=("us", "cn"),
    )


def test_scan_enumerates_the_controlled_universe(strong_candidates):
    """R-3/R-2.3: every bare dimension and every enum-valued attribute cell is a
    candidate, observed or not; concepts and blind spots never are."""
    candidates = strong_candidates
    keys = {c.feature.key for c in candidates}
    # All nine bare dimensions, including ones no observation touched.
    assert Feature(dimension="proposed_response").key in keys
    # Enumerated attribute cells nobody filled.
    ghost = Feature(
        dimension="quoted_voice", attr_key="speaker_category", attr_value="foreign_government"
    ).key
    assert ghost in keys
    # No concept-level candidates (R-4), no blind_spot label (S6's four-condition path).
    assert all(c.feature.concept_id is None for c in candidates)
    assert all(c.angle_type != "blind_spot" for c in candidates)


def test_labels_derive_from_the_feature_not_a_scan_table(strong):
    strong.add_group(
        "us",
        clusters=6,
        supporting=5,
        dimension="quoted_voice",
        concept_surface="official voice",
        attrs={"speaker": "spokesperson", "speaker_category": "government_official"},
        category="other",
    )
    strong.add_group(
        "cn",
        clusters=6,
        supporting=1,
        dimension="quoted_voice",
        concept_surface="official voice",
        attrs={"speaker": "发言人", "speaker_category": "government_official"},
        category="other",
    )
    candidates = scan_all(matrix_of(strong), "us", "cn")
    voice = [c for c in candidates if c.angle_type == "voice_structure"]
    assert voice and all(c.feature.attr_key == "speaker_category" for c in voice)
    assert by_feature(candidates, BARE_PD).angle_type == "salience"


def test_exceptions_are_computed_not_left_to_memory(strong_candidates):
    """§4.4.1 invariant 4: counter-examples travel with the candidate."""
    candidate = by_feature(strong_candidates, BARE_PD)
    assert candidate.supporting_observations
    assert candidate.exceptions, "the CN clusters that DO frame it this way are the exceptions"
    assert all(o.startswith("OBS-") for o in candidate.exceptions)


def test_consensus_reading_needs_resolution_not_just_closeness():
    """G-5's central fact: 'both sides high and close' only reads as consensus when the
    corpus is large enough to squeeze the interval inside ±δ_consensus."""
    big = CorpusBuilder()
    big.add_group("us", clusters=40, supporting=36)
    big.add_group("cn", clusters=40, supporting=36)
    result = evaluate(
        by_feature(scan_all(matrix_of(big), "us", "cn"), BARE_PD), RGateThresholds.load()
    )
    assert result.reading == "consensus"
    assert result.passed, result.failed_checks

    small = CorpusBuilder()
    small.add_group("us", clusters=10, supporting=7)
    small.add_group("cn", clusters=10, supporting=7)
    result = evaluate(
        by_feature(scan_all(matrix_of(small), "us", "cn"), BARE_PD), RGateThresholds.load()
    )
    assert result.reading == "insufficient", "10 clusters a side cannot certify consensus"
    assert not result.passed


def test_co_silence_reads_only_on_controlled_vocabulary_cells():
    """R-2.3: an empty enum cell is silence; an empty free-text cell is circular."""
    b = CorpusBuilder()
    b.add_group("us", clusters=10, supporting=3)
    b.add_group("cn", clusters=10, supporting=3)
    candidates = scan_all(matrix_of(b), "us", "cn")
    ghost = Feature(
        dimension="quoted_voice", attr_key="speaker_category", attr_value="foreign_government"
    ).key
    result = evaluate(by_feature(candidates, ghost), RGateThresholds.load())
    assert result.reading == "co_silence"
    assert result.passed, result.failed_checks

    free_text = replace(
        by_feature(candidates, ghost), controlled_vocabulary=False
    )
    result = evaluate(free_text, RGateThresholds.load())
    assert result.reading == "insufficient"
    assert not result.passed


def test_rgate_rejects_a_fragile_candidate_and_says_why():
    weak = CorpusBuilder()
    weak.add_group("us", clusters=12, supporting=7, sources=12)
    weak.add_group("cn", clusters=12, supporting=6, sources=12)
    candidate = by_feature(scan_all(matrix_of(weak), "us", "cn"), BARE_PD)
    result = evaluate(candidate, RGateThresholds.load())
    assert not result.passed
    assert result.reading == "insufficient"
    assert any("insufficient" in check for check in result.failed_checks)
    assert result.measured["delta"] is not None


def test_rgate_passes_a_strong_candidate_with_a_divergence_reading(strong_candidates):
    candidate = by_feature(strong_candidates, BARE_PD)
    result = evaluate(candidate, RGateThresholds.load())
    assert result.passed, result.failed_checks
    assert result.reading == "divergence"
    assert result.conservative_effect > 0


def test_rank_passed_orders_divergences_by_conservative_effect(strong_candidates):
    results = evaluate_all(strong_candidates)
    ranked = rank_passed(results)
    divergences = [r for r in ranked if r.reading == "divergence"]
    effects = [r.conservative_effect for r in divergences]
    assert effects == sorted(effects, reverse=True)
    # equivalence readings come after every divergence
    first_non_div = next(
        (i for i, r in enumerate(ranked) if r.reading != "divergence"), len(ranked)
    )
    assert all(r.reading == "divergence" for r in ranked[:first_non_div])


def test_blind_spot_variant_is_strictly_tighter(strong_candidates):
    """The blind-spot statistical half: a divergence whose low side is genuinely silent,
    on stricter floors — not just any strong difference relabelled."""
    thresholds = RGateThresholds.load()
    default = thresholds.for_angle_type("problem_definition")
    blind_rules = thresholds.for_angle_type("blind_spot")
    for key in ("min_clusters_total", "min_clusters_supporting"):
        assert blind_rules[key] > default[key], f"{key} must be stricter (§3.3 S6)"

    candidate = by_feature(strong_candidates, BARE_PD)
    ordinary = evaluate(candidate, thresholds)
    assert ordinary.passed
    # cn side is at 3/20 = 0.15 > low_prevalence 0.10: quieter, not silent.
    as_blind = evaluate(replace(candidate, angle_type="blind_spot"), thresholds)
    assert not as_blind.passed
    assert any("not silent" in check for check in as_blind.failed_checks)


def test_provisional_thresholds_cannot_be_used_in_strict_mode(strong_candidates):
    with pytest.raises(UncalibratedGateError, match="calibrate the thresholds"):
        evaluate_all(strong_candidates, require_calibrated=True)


def test_summarise_reports_readings_and_why_candidates_died(strong_candidates):
    results = evaluate_all(strong_candidates)
    summary = summarise(results)
    assert summary["candidates"] == summary["passed"] + summary["rejected"]
    assert isinstance(summary["rejection_reasons"], dict)
    assert sum(summary["readings"].values()) == summary["candidates"]


def test_run_id_has_a_reproducible_digest_and_unique_timestamp(strong_matrix):
    from newsab_a1.run import compute_run_id

    matrix = strong_matrix
    config = ScanConfig()
    a = compute_run_id(matrix, config, ("us", "cn"))
    b = compute_run_id(matrix, config, ("us", "cn"))
    assert a.split("-")[-1] == b.split("-")[-1], "same inputs must give the same digest"

    changed = compute_run_id(matrix, ScanConfig(seed=1), ("us", "cn"))
    assert changed.split("-")[-1] != a.split("-")[-1], "a config change must change the digest"
    assert a != b, "reruns must receive distinct immutable run directories"


def test_round_trip_through_disk_reproduces_every_metric(strong_run, tmp_path):
    """§4.4.1 invariant 1, end to end: store a run, reload it, get the same numbers."""
    run = strong_run
    run_dir = write_run(run, tmp_path)
    assert (run_dir / "run.json").exists()
    assert (run_dir / "candidates.jsonl").exists()

    recomputer = recompute_metrics(run_dir)
    assert recomputer.matrix_is_intact()

    candidate = next(c for c in run.candidates if c.feature.key == BARE_PD)
    again = recomputer.for_feature(candidate.feature, "us", "cn")
    assert again["delta"] == pytest.approx(candidate.interval.delta)
    assert again["delta_lo"] == pytest.approx(candidate.interval.lo)
    assert again["delta_hi"] == pytest.approx(candidate.interval.hi)
    assert again["direction_stability"] == pytest.approx(candidate.interval.direction_stability)
    assert again["conservative_effect"] == pytest.approx(candidate.interval.conservative_effect)
    assert again["prevalence.us"] == pytest.approx(candidate.interval.p_a)
    assert again["prevalence.cn"] == pytest.approx(candidate.interval.p_b)


def test_a_tampered_matrix_is_detected(strong_run, tmp_path):
    run = strong_run
    run_dir = write_run(run, tmp_path)
    matrix_file = run_dir / "feature_matrix.csv"
    if matrix_file.exists():
        lines = matrix_file.read_text(encoding="utf-8").splitlines()
        matrix_file.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    else:  # pragma: no cover - only when pyarrow is installed
        pytest.skip("parquet backend; tamper test covers the CSV path")
    recomputer = recompute_metrics(run_dir)
    assert not recomputer.matrix_is_intact()
    with pytest.raises(ValueError, match="input digest"):
        recomputer.for_feature(run.candidates[0].feature, "us", "cn")


def test_tampered_cluster_metadata_is_detected(strong_run, tmp_path):
    run = strong_run
    run_dir = write_run(run, tmp_path)
    clusters_path = run_dir / "clusters.json"
    clusters = json.loads(clusters_path.read_text(encoding="utf-8"))
    first = next(iter(clusters.values()))
    first["category"] = "other" if first["category"] != "other" else "serious"
    clusters_path.write_text(json.dumps(clusters), encoding="utf-8")
    recomputer = recompute_metrics(run_dir)
    assert not recomputer.matrix_is_intact()
    with pytest.raises(ValueError, match="input digest"):
        recomputer.for_feature(run.candidates[0].feature, "us", "cn")


def test_run_directory_is_never_overwritten(strong_run, tmp_path):
    write_run(strong_run, tmp_path)
    with pytest.raises(FileExistsError):
        write_run(strong_run, tmp_path)


def test_analyse_refuses_to_guess_which_groups_to_compare(strong):
    strong.add_group("id", clusters=4, supporting=2)
    with pytest.raises(ValueError, match="exactly two groups"):
        analyse(strong.observations, strong.articles, strong.snapshot(), strong.ontology())


def test_analyse_refuses_invalid_evidence_before_computing_statistics(strong):
    broken = strong.observations[0].model_copy(
        update={"evidence": [f"{strong.observations[0].article_id}:P99:S99"]}
    )
    observations = [broken, *strong.observations[1:]]
    with pytest.raises(ValueError, match="fail S4 invariants"):
        analyse(observations, strong.articles, strong.snapshot(), strong.ontology())
