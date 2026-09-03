"""The concept map keeps every concept and answers "did both sides say this" by
exhibiting anchors, not by estimating rates (R-4/R-5)."""

from conftest import CorpusBuilder
from newsab_a1 import build_concept_map


def build(builder: CorpusBuilder) -> dict:
    return build_concept_map(
        builder.observations, builder.articles, builder.snapshot(), builder.ontology()
    )


def two_sided() -> CorpusBuilder:
    b = CorpusBuilder()
    # A concept both sides mention — the shared-ground geometry.
    b.add_group("us", clusters=10, supporting=2, concept_surface="four year cap")
    b.add_group("cn", clusters=5, supporting=1, concept_surface="four year cap")
    # A single-newsroom wording on one side only.
    b.add_group("us", clusters=0, supporting=0)
    b.add_group(
        "cn",
        clusters=1,
        supporting=1,
        dimension="stance",
        concept_surface="politicised move",
        attrs={"target": "the rule", "polarity": "oppose"},
    )
    return b


def test_sides_and_shares_use_each_groups_own_denominator():
    result = build(two_sided())
    by_id = {c["concept_id"]: c for c in result["concepts"]}

    shared = by_id["four_year_cap"]
    assert shared["side"] == "both"
    # 2 of 10 vs 1 of 6: the share, not the raw count, is what sizing may use.
    assert shared["cluster_count"] == {"cn": 1, "us": 2}
    assert shared["cluster_share"]["us"] == 2 / 10
    assert shared["cluster_share"]["cn"] == 1 / 6
    assert shared["examples"]["us"] and shared["examples"]["cn"]

    solo = by_id["politicised_move"]
    assert solo["side"] == "cn"
    assert solo["cluster_count"]["us"] == 0
    assert max(solo["cluster_count"].values()) == 1, "a single newsroom's own wording"
    assert solo["valence"] == "negative"


def test_singletons_survive_and_shared_concepts_sort_first():
    """The old pipeline's min_support_clusters discarded 94% of concepts; the map must
    keep every one, with the both-sides region up front."""
    result = build(two_sided())
    assert result["summary"]["concepts"] == 2
    assert result["summary"]["single_newsroom"] == 1
    assert result["concepts"][0]["side"] == "both"


def test_quoted_context_is_derived_from_sentence_anchor_overlap():
    b = CorpusBuilder()
    # The quoted_voice observation and the stance observation anchor to the same
    # sentence (the builder anchors everything at P01:S01), so the stance concept was
    # said inside quoted speech.
    b.add_group(
        "us",
        clusters=4,
        supporting=2,
        dimension="quoted_voice",
        concept_surface="official reassurance",
        attrs={"speaker": "spokesperson", "speaker_category": "government_official"},
    )
    b.add_group(
        "cn",
        clusters=4,
        supporting=2,
        dimension="stance",
        concept_surface="firm opposition",
        attrs={"target": "the rule", "polarity": "oppose"},
    )
    result = build(b)
    by_id = {c["concept_id"]: c for c in result["concepts"]}
    quoted = by_id["official_reassurance"]
    assert quoted["is_quoted"] == "quoted"
    assert quoted["speaker_categories"] == ["government_official"]
    # The cn stance observations share no sentence with any quoted_voice observation.
    assert by_id["firm_opposition"]["is_quoted"] == "article_voice"
