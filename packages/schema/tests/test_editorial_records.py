"""The S5/S7 record invariants (§2.4, §4.5, D24).

Each test here stands for a way the page could lie to a reader while every other check in
the pipeline still passed.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from newsab_schema import (  # noqa: E402
    AngleCard,
    AngleSection,
    Claim,
    ClaimType,
    EditorialPage,
    MultiLangText,
    Provenance,
)
from newsab_schema.common import LangText  # noqa: E402

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)
PROV = Provenance(
    skill_version="S7-0.1.0", model_id="test-model", run_id="s7-202608200000-0123abcd", timestamp=NOW
)
ANGLE = "ANG-aabb-river-light-2026-0001"


def claim(**over):
    base = dict(
        claim_id="CLM-aabb-river-light-2026-0001",
        angle_id=ANGLE,
        topic_id="aabb-river-light-2026",
        text=MultiLangText(values={"en": "The sampled US coverage names an agency."}),
        claim_type=ClaimType.SOURCE_CLAIM,
        evidence=["US_0a1b2c3d:P01:S01"],
        provenance=PROV,
    )
    base.update(over)
    return Claim(**base)


def card(**over):
    base = dict(
        card_id="CARD-aabb-river-light-2026-0001-us",
        topic_id="aabb-river-light-2026",
        angle_id=ANGLE,
        group_id="us",
        lang="en",
        stance_summary=LangText(text="Most clusters name an actor.", lang="en"),
        structured_summary=LangText(text="Agencies and universities speak.", lang="en"),
        evidence=["US_0a1b2c3d:P01:S01"],
        clusters_supporting=22,
        clusters_total=43,
        provenance=PROV,
    )
    base.update(over)
    return AngleCard(**base)


# -- D24: the reading path may never borrow a statistic's authority --------------------


def test_a_reading_claim_cannot_carry_a_metric():
    with pytest.raises(ValidationError, match="computed_from"):
        claim(
            claim_type=ClaimType.CORPUS_READING,
            computed_from=f"{ANGLE}.metrics",
            evidence=["US_0a1b2c3d:P01:S01", "CN_1a2b3c4d:P01:S01"],
        )


def test_a_reading_claim_needs_more_than_one_anchor():
    """One sentence is one source speaking; a reading characterises a body of coverage."""
    with pytest.raises(ValidationError, match="two sentence anchors"):
        claim(claim_type=ClaimType.CORPUS_READING, evidence=["US_0a1b2c3d:P01:S01"])


def test_a_reading_claim_is_accepted_with_anchors_from_both_sides():
    made = claim(
        claim_type=ClaimType.CORPUS_READING,
        evidence=["US_0a1b2c3d:P01:S01", "CN_1a2b3c4d:P01:S01"],
    )
    assert made.computed_from is None


def test_an_aggregate_claim_still_requires_its_metric():
    with pytest.raises(ValidationError, match="computed_from"):
        claim(claim_type=ClaimType.CORPUS_AGGREGATE)


# -- S5: a side card is one side's, and cannot smuggle in the comparison ---------------


def test_a_side_card_cannot_quote_the_other_side():
    with pytest.raises(ValidationError, match="comparison belongs to S7"):
        card(evidence=["US_0a1b2c3d:P01:S01", "CN_1a2b3c4d:P01:S01"])


def test_a_side_card_id_must_name_its_own_side():
    with pytest.raises(ValidationError, match="does not end in its group_id"):
        card(card_id="CARD-aabb-river-light-2026-0001-cn")


def test_a_silence_card_still_needs_anchors():
    """D5: silence is data.  A card with no anchors is 'we did not look', not 'absent'."""
    with pytest.raises(ValidationError):
        card(is_silence_card=True, evidence=[])


def test_supporting_clusters_cannot_exceed_the_denominator():
    with pytest.raises(ValidationError, match="supporting clusters out of"):
        card(clusters_supporting=44, clusters_total=43)


# -- S7: the page's layers are checkable, not decorative -------------------------------


def section(**over):
    base = dict(
        angle_id=ANGLE,
        rank=1,
        angle_type="salience",
        headline=MultiLangText(values={"en": "Who gets a role"}),
        overview_claims=["CLM-aabb-river-light-2026-0001"],
        detail_claims=["CLM-aabb-river-light-2026-0002"],
    )
    base.update(over)
    return AngleSection(**base)


def test_a_claim_cannot_sit_in_both_layers():
    with pytest.raises(ValidationError, match="both the overview and detail"):
        section(detail_claims=["CLM-aabb-river-light-2026-0001"])


def test_page_ranks_must_be_a_dense_sequence():
    with pytest.raises(ValidationError, match="ranks must be 1..n"):
        EditorialPage(
            topic_id="aabb-river-light-2026",
            g2_run_id="g2-202608200010-e7255fcb",
            s6_run_id="s6-202608192252-6b3c04e2",
            a1_run_id="a1-20260819224937558530-5a6095bb",
            corpus_run_id="s2s-20260819203506210546-cb683282",
            title=MultiLangText(values={"en": "Visa"}),
            sections=[section(rank=2)],
            provenance=PROV,
        )
