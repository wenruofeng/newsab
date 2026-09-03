"""The matrix counts clusters, not articles — and every metric follows from that."""

import pytest

from conftest import CorpusBuilder
from newsab_a1 import (
    bootstrap_stability,
    build_feature_matrix,
    cross_stratum_consistency,
    divergence,
    signed_difference_interval,
    source_diversity,
)
from newsab_schema.models.analysis import Feature

# Metrics are exercised on the bare (salience) feature: concept-level features no longer
# enter the matrix at all (R-4) — see test_concept_features_stay_out_of_the_matrix.
FEATURE = Feature(dimension="problem_definition").key


def matrix_of(builder: CorpusBuilder):
    return build_feature_matrix(
        builder.observations, builder.articles, builder.snapshot(), builder.ontology()
    )


def test_prevalence_divides_by_clusters_not_articles(builder):
    """D7: one wire story in ten papers is one cluster, not ten."""
    builder.add_group("us", clusters=10, supporting=5, articles_per_cluster=3)
    builder.add_group("cn", clusters=10, supporting=2)
    matrix = matrix_of(builder)

    assert len(matrix.clusters_in("us")) == 10  # 30 articles, 10 clusters
    assert matrix.prevalence(FEATURE, "us") == 0.5
    assert matrix.prevalence(FEATURE, "cn") == 0.2


def test_absent_denominator_is_none_not_zero(builder):
    builder.add_group("us", clusters=6, supporting=3, category="serious")
    builder.add_group("cn", clusters=6, supporting=1, category="serious")
    matrix = matrix_of(builder)
    assert matrix.prevalence(FEATURE, "us", "other") is None


def test_divergence_matches_the_prevalence_gap(builder):
    builder.add_group("us", clusters=10, supporting=8)
    builder.add_group("cn", clusters=10, supporting=2)
    matrix = matrix_of(builder)
    assert divergence(matrix, FEATURE, "us", "cn") == pytest.approx(0.6)


def test_log_odds_is_more_sensitive_at_the_extremes(builder):
    """2% vs 12% is a bigger editorial difference than 45% vs 55%, same raw gap."""
    extreme = CorpusBuilder()
    extreme.add_group("us", clusters=50, supporting=6)
    extreme.add_group("cn", clusters=50, supporting=1)
    middle = CorpusBuilder()
    middle.add_group("us", clusters=50, supporting=28)
    middle.add_group("cn", clusters=50, supporting=23)

    me, mm = matrix_of(extreme), matrix_of(middle)
    assert divergence(me, FEATURE, "us", "cn", "prevalence_diff") == pytest.approx(
        divergence(mm, FEATURE, "us", "cn", "prevalence_diff"), abs=0.01
    )
    assert divergence(me, FEATURE, "us", "cn", "log_odds_ratio") > divergence(
        mm, FEATURE, "us", "cn", "log_odds_ratio"
    )


def test_diversity_separates_many_newsrooms_from_one_amplified_voice(builder):
    """§3.3 A1's stated reason for this layer's existence."""
    many = CorpusBuilder()
    many.add_group("us", clusters=10, supporting=8, sources=10)
    many.add_group("cn", clusters=10, supporting=8, sources=10)

    one = CorpusBuilder()
    one.add_group("us", clusters=10, supporting=1, sources=10)
    one.add_group("cn", clusters=10, supporting=8, sources=10)

    diverse = source_diversity(matrix_of(many), FEATURE, "us")
    concentrated = source_diversity(matrix_of(one), FEATURE, "us")
    assert diverse > concentrated
    assert concentrated < 0.2


def test_multi_publisher_cluster_uses_reporting_representative_not_alphabetical_source(builder):
    builder.add_group("us", clusters=1, supporting=1, sources=2, articles_per_cluster=2)
    builder.add_group("cn", clusters=1, supporting=1)

    # Make the second publication the single declared original while the first source sorts
    # earlier. The representative source must follow origin metadata, not lexical order.
    first, second = builder.articles[:2]
    builder.articles[0] = first.model_copy(
        update={"origin": first.origin.model_copy(update={"type": "syndication", "wire_source": "wire"})}
    )
    matrix = matrix_of(builder)
    meta = matrix.clusters[first.reporting_cluster_id]
    assert meta.representative_article_id == second.article_id
    assert meta.representative_source_id == second.source_id
    assert matrix.source_ids_supporting(FEATURE, "us") == [second.source_id]


def test_bootstrap_is_deterministic_and_penalises_coin_flips(builder):
    strong = CorpusBuilder()
    strong.add_group("us", clusters=20, supporting=18)
    strong.add_group("cn", clusters=20, supporting=2)
    weak = CorpusBuilder()
    weak.add_group("us", clusters=20, supporting=11)
    weak.add_group("cn", clusters=20, supporting=10)

    a = bootstrap_stability(matrix_of(strong), FEATURE, "us", "cn", n_resamples=200)
    b = bootstrap_stability(matrix_of(strong), FEATURE, "us", "cn", n_resamples=200)
    assert a.direction_stability == b.direction_stability, "same seed must give same result"
    assert a.direction_stability > 0.95

    fragile = bootstrap_stability(matrix_of(weak), FEATURE, "us", "cn", n_resamples=200)
    assert fragile.direction_stability < 0.8


def test_signed_interval_is_deterministic_and_signed(builder):
    """One resampling, every reading (R-2). The sign convention is p_a − p_b."""
    builder.add_group("us", clusters=20, supporting=18)
    builder.add_group("cn", clusters=20, supporting=2)
    matrix = matrix_of(builder)

    a = signed_difference_interval(matrix, FEATURE, "us", "cn", n_resamples=400)
    b = signed_difference_interval(matrix, FEATURE, "us", "cn", n_resamples=400)
    assert a == b, "same seed must give the same interval"
    assert a.p_a == 0.9 and a.p_b == 0.1
    assert a.delta == pytest.approx(0.8)
    assert a.lo > 0, "a strong difference excludes zero from below"
    assert a.excludes_zero()
    assert a.conservative_effect == a.lo
    assert a.direction_stability > 0.99
    assert a.log_odds > 0

    flipped = signed_difference_interval(matrix, FEATURE, "cn", "us", n_resamples=400)
    assert flipped.delta == pytest.approx(-0.8)
    assert flipped.hi < 0
    assert flipped.conservative_effect == pytest.approx(-flipped.hi)


def test_signed_interval_covers_zero_for_a_weak_difference(builder):
    """Regression for the abs() bug (G-6): the old interval could never cover zero, so no
    equivalence reading was possible.  A near-tie must produce an interval spanning 0."""
    builder.add_group("us", clusters=20, supporting=11)
    builder.add_group("cn", clusters=20, supporting=10)
    matrix = matrix_of(builder)
    interval = signed_difference_interval(matrix, FEATURE, "us", "cn", n_resamples=400)
    assert interval.lo < 0 < interval.hi
    assert not interval.excludes_zero()
    assert interval.conservative_effect == 0.0


def test_signed_interval_on_a_feature_nobody_supports(builder):
    """A controlled-vocabulary cell with zero support on both sides is a real observation
    (co-silence, R-2.3), not an error: the interval collapses to [0, 0]."""
    builder.add_group("us", clusters=10, supporting=3)
    builder.add_group("cn", clusters=10, supporting=3)
    matrix = matrix_of(builder)
    ghost = Feature(
        dimension="quoted_voice", attr_key="speaker_category", attr_value="foreign_government"
    ).key
    interval = signed_difference_interval(matrix, ghost, "us", "cn", n_resamples=200)
    assert interval.p_a == 0.0 and interval.p_b == 0.0
    assert interval.delta == 0.0
    assert (interval.lo, interval.hi) == (0.0, 0.0)
    assert interval.within(0.05)
    assert interval.concentration == {"us": None, "cn": None}


def test_bootstrap_percentiles_are_signed_not_folded(builder):
    """The stored spread must be able to cover 0 (the abs() bug fix)."""
    builder.add_group("us", clusters=20, supporting=11)
    builder.add_group("cn", clusters=20, supporting=10)
    matrix = matrix_of(builder)
    result = bootstrap_stability(matrix, FEATURE, "us", "cn", n_resamples=400)
    assert result.signed_diff_p05 < 0 < result.signed_diff_p95


def test_cross_stratum_flags_a_single_category_effect():
    """A gap driven only by non-serious outlets is a smaller story than one holding everywhere."""
    everywhere = CorpusBuilder()
    for category in ("serious", "other"):
        everywhere.add_group("us", clusters=6, supporting=5, category=category)
        everywhere.add_group("cn", clusters=6, supporting=1, category=category)

    one_only = CorpusBuilder()
    one_only.add_group("us", clusters=6, supporting=6, category="other")
    one_only.add_group("cn", clusters=6, supporting=0, category="other")
    one_only.add_group("us", clusters=6, supporting=2, category="serious")
    one_only.add_group("cn", clusters=6, supporting=4, category="serious")

    broad = cross_stratum_consistency(matrix_of(everywhere), FEATURE, "us", "cn")
    narrow = cross_stratum_consistency(matrix_of(one_only), FEATURE, "us", "cn")
    assert broad.value == 1.0
    assert narrow.value == 0.5
    assert "1/2" in narrow.note


def test_thin_strata_are_excluded_and_named_not_counted_as_disagreement():
    builder = CorpusBuilder()
    builder.add_group("us", clusters=8, supporting=7, category="serious")
    builder.add_group("cn", clusters=8, supporting=1, category="serious")
    builder.add_group("us", clusters=2, supporting=0, category="other")
    builder.add_group("cn", clusters=2, supporting=2, category="other")

    result = cross_stratum_consistency(matrix_of(builder), FEATURE, "us", "cn")
    assert result.value == 1.0
    assert "too thin to judge: other" in result.note


def test_unmapped_concept_surfaces_are_skipped_loudly(builder):
    """§4.3 still requires the surface→concept mapping to be total, even though concepts
    no longer mint features — an unmapped surface is a data error, not a shrug."""
    builder.add_group("us", clusters=4, supporting=2)
    builder.add_group("cn", clusters=4, supporting=1)
    ontology = builder.ontology()
    stripped = ontology.model_copy(update={"concepts": []})
    matrix = build_feature_matrix(
        builder.observations, builder.articles, builder.snapshot(), stripped
    )
    assert len(matrix.skipped) == 3
    assert all("unmapped" in reason for _, reason in matrix.skipped)


def test_concept_features_stay_out_of_the_matrix(builder):
    """R-4: concepts feed the concept map, not the Δ pipeline.  The matrix holds bare and
    attribute features only, whatever the ontology says."""
    builder.add_group("us", clusters=4, supporting=2)
    builder.add_group("cn", clusters=4, supporting=1)
    matrix = matrix_of(builder)
    shapes = {(k[1] is not None, k[2] is not None) for k in matrix.features}
    assert (True, False) not in shapes, "a concept-level feature reached the matrix"
    assert Feature(dimension="problem_definition").key in matrix.features


def test_wire_syndication_collapses_into_one_cluster(builder):
    """The C3 homogeneity story, seen from A1's side."""
    builder.add_group("cn", clusters=2, supporting=2, articles_per_cluster=10)
    builder.add_group("us", clusters=8, supporting=4)
    matrix = matrix_of(builder)
    assert len([a for a in builder.articles if a.article_id.startswith("CN")]) == 20
    assert len(matrix.clusters_in("cn")) == 2
    assert matrix.prevalence(FEATURE, "cn") == 1.0
