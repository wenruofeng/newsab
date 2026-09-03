"""§4.1: the four locked vocabularies have exactly one definition site."""

import json
import subprocess
import sys
from pathlib import Path

from newsab_schema import enums

REPO = Path(__file__).resolve().parents[3]


def test_locked_vocabularies_match_the_blueprint():
    assert enums.Dimension.values() == [
        "problem_definition",
        "responsibility",
        "consequence",
        "stance",
        "proposed_response",
        "actor_role",
        "quoted_voice",
        "terminology",
        "factual_claim",
    ]
    # The third path was added by D24: "the two sides
    # answer differently" is read out of the source text, so it may never carry a metric.
    assert enums.ClaimType.values() == ["source_claim", "corpus_aggregate", "corpus_reading"]
    assert len(enums.SpeakerCategory.values()) == 9
    # 9 blueprint types + co_silence, added (additively — §4.1 allows that) by R-2.2.
    assert len(enums.AngleType.values()) == 10
    assert "co_silence" in enums.AngleType.values()


def test_every_dimension_has_a_required_attrs_entry():
    assert set(enums.REQUIRED_ATTRS) == set(enums.Dimension)


def test_attr_enums_only_reference_required_keys():
    for (dimension, key) in enums.ATTR_ENUMS:
        assert key in enums.REQUIRED_ATTRS[dimension]


def test_valence_accepts_the_abbreviated_blueprint_spelling():
    assert enums.coerce_valence("neg") is enums.Valence.NEGATIVE
    assert enums.coerce_valence("negative") is enums.Valence.NEGATIVE


def test_locked_enum_values_are_not_redefined_elsewhere_in_the_repo():
    """A second copy of a locked vocabulary is a §4.1 violation, wherever it lives.

    We look for the tell-tale shape of a re-declared list (several locked values quoted
    together) in any file other than the definition site and its generated exports.
    """
    allowed_exact = {
        "packages/schema/newsab_schema/enums.py",  # the definition site
        "packages/schema/tests/test_enums.py",  # this file
        "docs/archive/init_design_blueprint_20260817.md",  # the spec the definition site followed
        # A synthetic corpus is pipeline *input* stated in vocabulary values — usage,
        # not a re-declaration (its Observation rows are validated against the enums).
        "tests/pipeline_fixture.py",
    }
    # Everything under dist/ is generated *from* the definition site, so it is a copy by
    # construction and `export --check` already fails if it drifts.
    #
    # `topics/` is pipeline *output*: a feature matrix or a candidate set naturally carries
    # dimension values as data — keys, column names, recorded observations — and that is the
    # vocabulary being used, not a second declaration of it. Without this exclusion the test
    # starts failing the moment a real A1 run is committed, which is the moment it should be
    # least in the way.
    allowed_prefixes = ("packages/schema/dist/", "topics/")
    probe = ["problem_definition", "responsibility", "consequence", "proposed_response"]
    out = subprocess.run(
        ["git", "grep", "-l", "--", probe[0]], cwd=REPO, capture_output=True, text=True
    )
    offenders = []
    for rel in out.stdout.split():
        if rel in allowed_exact or rel.startswith(allowed_prefixes):
            continue
        text = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
        if sum(term in text for term in probe) >= 3 and rel.endswith((".py", ".json", ".ts")):
            offenders.append(rel)
    assert not offenders, (
        f"these files look like they re-declare the `dimension` vocabulary: {offenders}; "
        "import it from newsab_schema.enums or read dist/enums.json instead (§4.1)"
    )


def test_dist_enums_json_matches_the_module():
    payload = json.loads(
        (REPO / "packages/schema/dist/enums.json").read_text(encoding="utf-8")
    )
    for name, cls in enums.ALL.items():
        assert payload["enums"][name]["values"] == cls.values()
