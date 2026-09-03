"""§4.3 — concept normalisation must add mappings, never rewrite surfaces."""

import pytest
from pydantic import ValidationError

from conftest import make_article, make_observation, provenance
from newsab_schema import ConceptOntology
from newsab_schema.validate import validate_observations


def ontology(surfaces):
    return ConceptOntology(
        topic_id="aabb-river-light-2026",
        ontology_version="onto-0.1",
        concepts=[
            {
                "concept_id": "study_plan_disruption",
                "label": {"values": {"en": "Study plan disruption", "zh-CN": "留学规划受阻"}},
                "surfaces": surfaces,
                "merged_by": {"skill_version": "S4norm-0.1.0", "run_id": "s4n-202608171200-aa11bb22"},
            }
        ],
        provenance=provenance("S4norm-0.1.0"),
    )


def test_surfaces_map_to_exactly_one_concept():
    with pytest.raises(ValidationError, match="more than one concept"):
        ConceptOntology(
            topic_id="aabb-river-light-2026",
            ontology_version="onto-0.1",
            concepts=[
                {
                    "concept_id": "a_concept",
                    "label": {"values": {"en": "A"}},
                    "surfaces": [
                        {"text": "留学家庭规划受冲击", "lang": "zh-CN", "example_obs": "OBS-aabb-river-light-000001"}
                    ],
                    "merged_by": {"skill_version": "S4norm-0.1.0", "run_id": "r"},
                },
                {
                    "concept_id": "b_concept",
                    "label": {"values": {"en": "B"}},
                    "surfaces": [
                        {"text": "留学家庭规划受冲击", "lang": "zh-CN", "example_obs": "OBS-aabb-river-light-000002"}
                    ],
                    "merged_by": {"skill_version": "S4norm-0.1.0", "run_id": "r"},
                },
            ],
            provenance=provenance("S4norm-0.1.0"),
        )


def test_every_observed_surface_must_be_mapped():
    """An ontology that covers some other surface leaves this observation unanalysable."""
    onto = ontology(
        [{"text": "另一个表述", "lang": "zh-CN", "example_obs": "OBS-aabb-river-light-000009"}]
    )
    report = validate_observations([make_observation(concept_surface="留学家庭规划受冲击")], [make_article()], onto)
    assert any(f.code == "surface_not_mapped" for f in report.errors), report.render()


def test_a_paraphrased_surface_breaks_the_audit_trail():
    """Invariant 3: a surface the normaliser invented appears in no observation."""
    onto = ontology(
        [{"text": "留学规划受阻", "lang": "zh-CN", "example_obs": "OBS-aabb-river-light-000001"}]
    )
    report = validate_observations([make_observation()], [make_article()], onto)
    codes = {f.code for f in report.errors}
    assert "surface_not_observed" in codes  # the paraphrase
    assert "surface_not_mapped" in codes  # the original left behind


def test_self_mapping_surface_is_clean():
    onto = ontology(
        [{"text": "留学家庭规划受冲击", "lang": "zh-CN", "example_obs": "OBS-aabb-river-light-000001"}]
    )
    report = validate_observations([make_observation()], [make_article()], onto)
    assert report.ok(), report.render()
    assert onto.lookup("留学家庭规划受冲击", "zh-CN") == "study_plan_disruption"


def test_first_run_id_survives_a_restamp():
    """merged_by.run_id says who produced the record; first_run_id says when the
    merge was decided. A carried-forward concept keeps its decision history."""
    from newsab_schema.models.annotation import MergedBy

    new = MergedBy(skill_version="S4norm-0.3.1", run_id="s4n-202608190800-cc22dd33")
    assert new.first_run_id is None
    assert new.decided_run_id == "s4n-202608190800-cc22dd33"

    carried = MergedBy(
        skill_version="S4norm-0.3.1",
        run_id="s4n-202608190800-cc22dd33",
        first_run_id="s4n-202608171200-aa11bb22",
    )
    assert carried.decided_run_id == "s4n-202608171200-aa11bb22"
