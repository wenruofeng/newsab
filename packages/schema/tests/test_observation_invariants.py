"""Blueprint §4.2 / §4.2.2 — the observation record and its invariants."""

import pytest
from pydantic import ValidationError

from conftest import make_article, make_observation
from newsab_schema.validate import validate_observations


def test_valid_observation_passes(article, observation):
    report = validate_observations([observation], [article])
    assert report.ok(), report.render()
    assert report.stats["observations"] == 1


def test_invariant_1_evidence_must_exist_in_the_article(article):
    obs = make_observation(evidence=("CN_001:P09:S01",))
    report = validate_observations([obs], [article])
    assert not report.ok()
    assert any(f.code == "evidence_anchor_missing" for f in report.errors)


def test_invariant_1_evidence_cannot_come_from_another_article():
    with pytest.raises(ValidationError, match="foreign anchors"):
        make_observation(evidence=("CN_002:P01:S01",))


def test_evidence_cannot_be_empty():
    with pytest.raises(ValidationError):
        make_observation(evidence=())


def test_invariant_2_explanatory_wording_is_rejected(article):
    obs = make_observation(proposition="签证收紧反映了美方遏制中国的意图。")
    report = validate_observations([obs], [article])
    codes = {f.code for f in report.errors}
    assert "lint_causal_language" in codes
    assert "lint_presentation_marker" in codes


def test_invariant_2_country_as_subject_is_rejected(article):
    obs = make_observation(proposition="中国认为该政策被呈现为不友好的。")
    report = validate_observations([obs], [article])
    assert any(f.code == "lint_scope_subject" for f in report.errors)


def test_invariant_4_proposition_language_must_match_the_article(article):
    obs = make_observation(
        proposition="The tightening is presented as a direct shock to families.", lang="en"
    )
    report = validate_observations([obs], [article])
    assert any(f.code == "proposition_language_mismatch" for f in report.errors)


def test_dimension_attrs_are_enforced():
    with pytest.raises(ValidationError, match="requires attrs"):
        make_observation(dimension="responsibility", attrs={"actor": "美国政府"})
    with pytest.raises(ValidationError, match="not a valid"):
        make_observation(dimension="responsibility", attrs={"actor": "美国政府", "polarity": "bad"})


def test_quoted_voice_requires_speaker_and_category():
    obs = make_observation(
        dimension="quoted_voice",
        attrs={"speaker": "教育部发言人", "speaker_category": "government_official"},
        proposition="发言人被引述为对该政策表示反对。",
    )
    assert obs.attrs["speaker_category"] == "government_official"


def test_records_are_immutable(observation):
    with pytest.raises(ValidationError):
        observation.confidence = 0.1


def test_unknown_fields_are_rejected():
    """A field the schema does not know about fails loudly rather than being dropped.

    This is what keeps a contributor's typo — or a resurrected `sentiment` field —
    from silently vanishing between packages.
    """
    from newsab_schema import Observation

    payload = {**make_observation().model_dump(mode="json"), "sentiment": "negative"}
    with pytest.raises(ValidationError, match="[Ee]xtra"):
        Observation.model_validate(payload)


def test_invariant_5_distribution_is_reported_not_enforced(article):
    obs = [
        make_observation(observation_id=f"OBS-aabb-river-light-{i:06d}", evidence=("CN_001:P01:S01",))
        for i in range(1, 4)
    ]
    report = validate_observations(obs, [article])
    assert report.ok()
    assert report.stats["obs_per_article_max"] == 3
    assert any(f.code == "obs_count_outside_expected_band" for f in report.findings)


def test_article_with_no_observations_is_flagged():
    report = validate_observations([], [make_article()])
    assert any(f.code == "article_without_observations" for f in report.warnings)


def test_notable_language_must_quote_verbatim(article, article_annotation):
    from newsab_schema.validate import validate_article_annotations

    assert validate_article_annotations([article_annotation], [article]).ok()

    payload = article_annotation.model_dump(mode="json")
    payload["notable_language"] = [
        {"phrase": "并不存在的短语", "sentence": "CN_001:P02:S01", "signal": "high_emotion"}
    ]
    bad = type(article_annotation).model_validate(payload)
    report = validate_article_annotations([bad], [article])
    assert any(f.code == "notable_language_not_verbatim" for f in report.errors)
