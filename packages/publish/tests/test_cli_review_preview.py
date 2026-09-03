"""``review-preview`` guards the closed category vocabulary.

A pub-repo agent once invented its own tags because nothing told it the vocabulary was
closed: the proposal rode to touchpoint two as a string and would
have matched no home-page filter.  The refusal now happens at proposal time, before any
input resolution, so the message reaches the agent that still holds the context.
"""

from newsab_publish.cli import main
from newsab_publish.metadata import default_metadata_path, load_site_metadata


def test_review_preview_refuses_a_category_outside_the_site_vocabulary(tmp_path, capsys):
    code = main(
        [
            "review-preview",
            str(tmp_path),
            "aabb-river-light-2026",
            "--page-run",
            "rl-20260825090600000001-a0000007",
            "--categories",
            "made-up-tag",
            "-o",
            str(tmp_path / "out"),
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "unknown site categories" in err
    assert "made-up-tag" in err
    # The refusal names the whole legal vocabulary, so the fix needs no second lookup.
    for category in load_site_metadata(default_metadata_path()).categories:
        assert category.category_id in err


# --------------------------------------------------------------------------------------
# The bytes a human reviews are proved equal to the submission verifier's own
# recomputation.  Until this existed the two renders were never compared, and the
# concept-cloud regression — G2 rendered a concept cloud, the reviewer's copy had none —
# was caught only by eye.
# --------------------------------------------------------------------------------------

import json
import sys
from pathlib import Path

import pytest

EXAMPLE_DIR = Path(__file__).resolve().parents[3] / "examples" / "synthetic-topic"
sys.path.insert(0, str(EXAMPLE_DIR))
import demo_fixture as fx  # noqa: E402

LOCALES = ("en", "zh-CN")


def _preview(tmp_path, out_name, *extra):
    return main(
        [
            "review-preview",
            str(tmp_path / "topics"),
            fx.TOPIC_ID,
            "--page-run",
            fx.PAGE_RUN_ID,
            "--locales",
            ",".join(LOCALES),
            "-o",
            str(tmp_path / out_name),
            *extra,
        ]
    )


def _verification(tmp_path, name, fingerprint, locales=LOCALES):
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {
                "schema_version": "submission-verify-report-0.1.0",
                "ok": True,
                "gates": {
                    "g2": {
                        "candidate_fingerprint": fingerprint,
                        "render_locales": list(locales),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def rendered(tmp_path, capsys):
    """One plain preview, and the fingerprint of the bundle it wrote."""
    fx.build_topic(tmp_path / "topics")
    assert _preview(tmp_path, "first") == 0
    return json.loads(capsys.readouterr().out)


def test_review_preview_fingerprints_only_the_bundle_it_wrote(rendered, tmp_path):
    """The chrome and the review manifest are review scaffolding, not candidate bytes:
    a fingerprint that covered them could never equal the verifier's, which renders the
    bundle alone into an empty directory."""
    assert rendered["candidate_fingerprint"].startswith("sha256:")
    assert rendered["candidate_recomputed"] is False
    written = {path.name for path in (tmp_path / "first").rglob("*") if path.is_file()}
    assert "review_manifest.json" in written  # present on disk...
    manifest = json.loads((tmp_path / "first" / "review_manifest.json").read_text("utf-8"))
    # ...and it records the same fingerprint, so the review root carries the evidence.
    assert (
        manifest["topics"][fx.TOPIC_ID]["candidate_fingerprint"]
        == rendered["candidate_fingerprint"]
    )


def test_review_preview_accepts_a_matching_verifier_recomputation(rendered, tmp_path, capsys):
    report = _verification(tmp_path, "ok.json", rendered["candidate_fingerprint"])
    assert _preview(tmp_path, "second", "--expect-candidate", report) == 0
    assert json.loads(capsys.readouterr().out)["candidate_recomputed"] is True


def test_review_preview_refuses_bytes_the_verifier_did_not_recompute(rendered, tmp_path, capsys):
    report = _verification(tmp_path, "bad.json", "sha256:" + "e" * 64)
    assert _preview(tmp_path, "third", "--expect-candidate", report) == 2
    err = capsys.readouterr().err
    assert "not the pages the submission verifier recomputed" in err
    assert rendered["candidate_fingerprint"] in err


def test_review_preview_refuses_a_locale_set_the_verifier_never_rendered(rendered, tmp_path, capsys):
    """Different locale sets make different page bytes on purpose (a page names the other
    languages it exists in), so the mismatch is explained here rather than surfacing as
    an unreadable fingerprint difference."""
    report = _verification(
        tmp_path, "narrow.json", rendered["candidate_fingerprint"], locales=("en",)
    )
    assert _preview(tmp_path, "fourth", "--expect-candidate", report) == 2
    assert "not comparable" in capsys.readouterr().err


def test_review_preview_refuses_a_submission_render_with_nothing_to_compare(tmp_path, capsys):
    """``--hash-only`` is the submission path's marker: on it the comparison is mandatory,
    so a preview that would put un-recomputed bytes in front of a human never renders."""
    fx.build_topic(tmp_path / "topics")
    envelope = tmp_path / "envelope.json"
    envelope.write_text(json.dumps({"members": []}), encoding="utf-8")
    assert _preview(tmp_path, "fifth", "--hash-only", str(envelope)) == 2
    assert "--expect-candidate" in capsys.readouterr().err
