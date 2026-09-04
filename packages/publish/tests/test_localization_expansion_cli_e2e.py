"""Pins the full command sequence ``skills/publish/references/localization.md``'s
"Expanding" section documents for a topic's first release: ``prepare`` -> ``activate``
(the reviewed languages) -> ``backfill-locales`` (widening to a language the site has
since learned), run as real subprocess CLI invocations exactly as an operator types them.

Nothing exercised this end to end before this test was written — it is a command sequence
that had never had test coverage from end to end. Three things this test locks down, all
discovered against a real nine-locale launch:

1. A topic that has never shipped and whose site metadata has no approved category
   mapping yet dies in ``prepare`` with "site metadata has no approved taxonomy mapping" —
   ``adopt-taxonomy`` (reading the touchpoint-two-written ``TopicCategoryApproval`` off
   disk) is what clears that, and ``prepare`` succeeds right after with no other change.
2. ``backfill-locales --topic <t>`` for a topic with no live publication fails with a
   message naming the ``prepare`` command to run first, instead of silently reporting a
   zero-outcome batch.
3. Once live, widening the locale set through ``backfill-locales`` supersedes the
   publication and its equivalence proof records which whitelisted rendering rules
   actually moved between the signed bytes and the candidate — evidence, read back from
   the written record rather than assumed.

Every artifact is built from schema-valid Python objects in ``tmp_path``, following
``examples/synthetic-topic/demo_fixture.py`` and ``test_lifecycle_e2e.py`` — no dependency
on this machine's real ``topics/`` or ``site/`` trees.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.cli_e2e

REPO = Path(__file__).resolve().parents[3]
EXAMPLE_DIR = REPO / "examples" / "synthetic-topic"
sys.path.insert(0, str(EXAMPLE_DIR))
import demo_fixture as fx  # noqa: E402

from newsab_schema.artifacts import append_manifest, run_set_hash  # noqa: E402
from newsab_schema.models.manifest import ManifestEntry  # noqa: E402
from newsab_schema.paths import SitePaths, TopicPaths  # noqa: E402

from newsab_publish.builder import (  # noqa: E402
    default_theme_registry_path,
    render_candidate_bundle,
    resolve_inputs,
)
from newsab_publish.metadata import SiteCategory, SiteMetadata  # noqa: E402
from newsab_publish.themes import load_theme_registry, resolve_theme  # noqa: E402

BASE_URL = "https://example.org"
NEW_LOCALE = "fr"
EXPANSION_RUN_ID = "edt-202609030906-f1000007"


def _run(*args: str) -> subprocess.CompletedProcess:
    """Invoke ``newsab_publish`` exactly as documented: ``python -m newsab_publish ...``."""
    env = os.environ.copy()
    env["PYTHONPATH"] = ":".join(
        str(REPO / "packages" / name)
        for name in ("schema", "corpus", "a1", "editorial", "publish")
    )
    return subprocess.run(
        [sys.executable, "-m", "newsab_publish", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _add_locale(node, new_locale: str, source_locale: str = "en"):
    """Recursively duplicate every ``{"values": {lang: text}}`` leaf into ``new_locale``.

    Structural, not field-name-based (mirrors ``reviewed_equivalence.project_page``'s own
    recognition rule) so a render-localize expansion run that adds a language to *every*
    multi-language field in one page — title, intro, quotes, lexicon, angle prose — can be
    built without hand-listing each field.
    """
    if isinstance(node, dict):
        values = node.get("values")
        if (
            set(node) == {"values"}
            and isinstance(values, dict)
            and all(isinstance(v, str) for v in values.values())
        ):
            if source_locale in values and new_locale not in values:
                values = dict(values)
                values[new_locale] = f"[{new_locale}] {values[source_locale]}"
            return {"values": values}
        return {k: _add_locale(v, new_locale, source_locale) for k, v in node.items()}
    if isinstance(node, list):
        return [_add_locale(item, new_locale, source_locale) for item in node]
    return node


# ----------------------------------------------------------------------------------
# fixtures: the synthetic topic, a site metadata revision with the per-topic taxonomy
# gate turned ON and no mapping yet, and the reviewed zh-CN page hash the reviewer would
# have actually read at touchpoint two.
# ----------------------------------------------------------------------------------


@pytest.fixture
def topics_root(tmp_path):
    root = tmp_path / "topics"
    fx.build_topic(root)
    return root


@pytest.fixture
def site_root(tmp_path):
    return tmp_path / "site"


@pytest.fixture
def metadata_path(tmp_path):
    return tmp_path / "site_metadata.json"


@pytest.fixture
def metadata(metadata_path):
    """``site-metadata-1.1.0``: the per-topic taxonomy approval gate is live, and — unlike
    ``demo_fixture.build_metadata`` — this fixture's topic starts with **no** mapping, so
    the first ``prepare`` genuinely dies on it (point 1 above)."""
    metadata = SiteMetadata(
        metadata_version="site-metadata-1.1.0",
        taxonomy_version="taxonomy-1.0.0",
        locales=["en", "zh-CN"],
        categories=[
            SiteCategory(
                category_id="world",
                labels={"en": "World", "zh-CN": "国际"},
            )
        ],
    )
    metadata_path.write_text(metadata.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return metadata


def _reviewed_zh_hash(topics_root, metadata, scratch) -> str:
    resolved = resolve_inputs(topics_root, fx.TOPIC_ID, fx.PAGE_RUN_ID)
    registry = load_theme_registry(default_theme_registry_path())
    theme = resolve_theme(None, registry)
    bundles, _, _ = render_candidate_bundle(
        resolved, metadata.locales, scratch, m2=True, theme=theme
    )
    return next(b.page_hash for b in bundles if b.locale == fx.REVIEW_LOCALE)


@pytest.fixture
def reviewed_hash(topics_root, metadata, tmp_path):
    scratch = tmp_path / "scratch-review"
    scratch.mkdir()
    return _reviewed_zh_hash(topics_root, metadata, scratch)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def review_path(site_root, reviewed_hash, tmp_path):
    """The ``PublicationReview`` the reviewer's touchpoint-two click would have written."""
    return _write_json(
        tmp_path / "review.json",
        {
            "approval_id": f"APR-{fx.TOPIC_ID}-0123abcd",
            "reviewer_id": "test-founder",
            "decided_at": "2026-09-03T12:00:00Z",
            "locale": fx.REVIEW_LOCALE,
            "page_hash": reviewed_hash,
            "reviewed_locales": ["en", "zh-CN"],
        },
    )


@pytest.fixture
def taxonomy_approval_path(site_root, reviewed_hash):
    """The dashboard's ``topic-categories-<topic>-<hash8>.json`` from the same click."""
    hash8 = reviewed_hash[7:15]
    return _write_json(
        SitePaths.at(site_root).ensure().private_dir / "approvals"
        / f"topic-categories-{fx.TOPIC_ID}-{hash8}.json",
        {
            "approval_id": f"taxonomy-topic-{fx.TOPIC_ID}-2026-09-03",
            "topic_id": fx.TOPIC_ID,
            "reviewer_id": "test-founder",
            "decision": "approved",
            "decided_at": "2026-09-03T12:00:00Z",
            "category_ids": ["world"],
            "note": {"text": "synthetic taxonomy approval", "lang": "en"},
        },
    )


# ----------------------------------------------------------------------------------
# point 1: prepare dies on the missing taxonomy mapping; adopt-taxonomy clears it.
# ----------------------------------------------------------------------------------


def test_prepare_dies_on_missing_taxonomy_then_succeeds_after_adopt_taxonomy(
    topics_root, site_root, metadata_path, review_path, taxonomy_approval_path
):
    first = _run(
        "prepare", str(topics_root), str(site_root), fx.TOPIC_ID,
        "--page-run", fx.PAGE_RUN_ID, "--review", str(review_path),
        "--site-metadata", str(metadata_path),
    )
    assert first.returncode == 2
    assert "no approved taxonomy mapping" in first.stderr

    adopted = _run(
        "adopt-taxonomy", str(site_root), fx.TOPIC_ID,
        "--approval", str(taxonomy_approval_path),
        "--site-metadata", str(metadata_path),
    )
    assert adopted.returncode == 0, adopted.stderr
    payload = json.loads(adopted.stdout)
    assert payload["status"] == "adopted"
    assert payload["category_ids"] == ["world"]
    on_disk = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert on_disk["topic_categories"][fx.TOPIC_ID] == ["world"]

    # Replaying the same adopt is a reported no-op, never a duplicate append.
    replay = _run(
        "adopt-taxonomy", str(site_root), fx.TOPIC_ID,
        "--approval", str(taxonomy_approval_path),
        "--site-metadata", str(metadata_path),
    )
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["status"] == "already-adopted"

    second = _run(
        "prepare", str(topics_root), str(site_root), fx.TOPIC_ID,
        "--page-run", fx.PAGE_RUN_ID, "--review", str(review_path),
        "--site-metadata", str(metadata_path),
    )
    assert second.returncode == 0, second.stderr
    assert "site metadata has no approved taxonomy mapping" not in second.stderr


# ----------------------------------------------------------------------------------
# point 2: backfill-locales on a never-shipped topic names the prepare command to run.
# ----------------------------------------------------------------------------------


def test_backfill_locales_on_a_never_shipped_topic_names_the_prepare_command(
    topics_root, site_root, metadata_path, metadata
):
    # No prepare/activate has happened yet in this test — the topic has no publication
    # of any kind, live or otherwise.
    result = _run(
        "backfill-locales", str(topics_root), str(site_root),
        "--site-metadata", str(metadata_path), "--base-url", BASE_URL,
        "--reason", "site learned a language", "--topic", fx.TOPIC_ID,
    )
    assert result.returncode == 1
    assert "prepare" in result.stdout
    assert fx.TOPIC_ID in result.stdout
    assert "no live publication" in result.stdout
    # The hint names a real, runnable command shape: topics_root, site_root, topic_id
    # and --site-metadata all appear verbatim, and the active editorial run this fixture
    # actually has is named rather than a placeholder.
    assert str(topics_root) in result.stdout
    assert str(site_root) in result.stdout
    assert str(metadata_path) in result.stdout
    assert fx.PAGE_RUN_ID in result.stdout


# ----------------------------------------------------------------------------------
# point 3: the full sequence — prepare -> activate -> backfill-locales — and what the
# equivalence proof records.
# ----------------------------------------------------------------------------------


@pytest.fixture
def live_publication(
    topics_root, site_root, metadata_path, review_path, taxonomy_approval_path
):
    """Ship the topic in its two reviewed languages: adopt-taxonomy, prepare, activate."""
    adopted = _run(
        "adopt-taxonomy", str(site_root), fx.TOPIC_ID,
        "--approval", str(taxonomy_approval_path), "--site-metadata", str(metadata_path),
    )
    assert adopted.returncode == 0, adopted.stderr

    prepared = _run(
        "prepare", str(topics_root), str(site_root), fx.TOPIC_ID,
        "--page-run", fx.PAGE_RUN_ID, "--review", str(review_path),
        "--site-metadata", str(metadata_path),
    )
    assert prepared.returncode == 0, prepared.stderr
    publication_id = prepared.stdout.splitlines()[0].strip()

    approval_path = _write_json(
        Path(site_root) / "private" / "approvals" / f"activate-{publication_id}.json",
        {
            "approval_id": f"APR-{fx.TOPIC_ID}-1123abcd",
            "reviewer_id": "test-founder",
            "decided_at": "2026-09-03T12:05:00Z",
        },
    )
    production_dir = Path(site_root) / "public"
    activated = _run(
        "activate", str(topics_root), str(site_root), publication_id,
        "--approval", str(approval_path), "--site-metadata", str(metadata_path),
        "--production", str(production_dir), "--base-url", BASE_URL,
        "--build-date", "2026-09-03",
    )
    assert activated.returncode == 0, activated.stderr
    return publication_id, production_dir


def _build_expansion_run(topics_root):
    """A render-localize expansion run: the same closure, one new locale added
    everywhere, exactly what ``localization.md``'s "Expanding" section describes a
    render-localize agent producing before a locale backfill."""
    paths = TopicPaths.for_topic(topics_root, fx.TOPIC_ID)
    reviewed_page = json.loads(
        (paths.stage_run_dir("editorial", fx.PAGE_RUN_ID) / "page.json").read_text(
            encoding="utf-8"
        )
    )
    expanded = copy.deepcopy(reviewed_page)
    expanded = _add_locale(expanded, NEW_LOCALE, source_locale="en")
    expanded["provenance"] = dict(
        expanded["provenance"], run_id=EXPANSION_RUN_ID, timestamp=fx.NOW.isoformat()
    )
    run_dir = paths.stage_run_dir("editorial", EXPANSION_RUN_ID)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "page.json").write_text(json.dumps(expanded), encoding="utf-8")
    append_manifest(
        paths,
        ManifestEntry(
            skill_id="render-localize",
            skill_version="0.1.0",
            model_id="fixture-model",
            run_id=EXPANSION_RUN_ID,
            topic_id=fx.TOPIC_ID,
            stage="editorial",
            inputs=[
                fx.CORPUS_RUN_ID,
                fx.QUESTIONS_RUN_ID,
                fx.ANSWERS_RUN_ID,
                fx.NORMALIZATION_RUN_ID,
                fx.QA_RUN_ID,
            ],
            output_set_hash=run_set_hash(paths, "editorial", EXPANSION_RUN_ID),
            timestamp=fx.NOW,
        ),
        activate_stage="editorial",
    )


def test_full_sequence_prepare_activate_backfill_locales_widens_and_supersedes(
    topics_root, site_root, metadata_path, live_publication
):
    old_publication_id, production_dir = live_publication
    # Confirm the two-locale release is really live before widening it.
    assert (production_dir / fx.REVIEW_LOCALE / "topics" / fx.TOPIC_ID / "index.html").is_file()
    assert not (production_dir / NEW_LOCALE).exists()

    _build_expansion_run(topics_root)

    # The site learns a language: widen site_metadata.locales and give the one taxonomy
    # category a label in it too (SiteMetadata._controlled_taxonomy requires every
    # *live* site locale to be covered).
    on_disk = json.loads(metadata_path.read_text(encoding="utf-8"))
    on_disk["locales"] = ["en", "zh-CN", NEW_LOCALE]
    for category in on_disk["categories"]:
        category["labels"][NEW_LOCALE] = f"[{NEW_LOCALE}] " + category["labels"]["en"]
    SiteMetadata.model_validate(on_disk)  # fails loudly here, not inside the subprocess
    metadata_path.write_text(json.dumps(on_disk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    backfilled = _run(
        "backfill-locales", str(topics_root), str(site_root),
        "--site-metadata", str(metadata_path), "--production", str(production_dir),
        "--base-url", BASE_URL, "--reason", "the site learned French; backfilling live topics",
        "--topic", fx.TOPIC_ID,
    )
    assert backfilled.returncode == 0, backfilled.stdout + backfilled.stderr
    assert "superseded" in backfilled.stdout
    assert "1 superseded, 0 skipped, 0 failed" in backfilled.stdout

    # The widened publication is now live, in all three locales.
    assert (production_dir / NEW_LOCALE / "topics" / fx.TOPIC_ID / "index.html").is_file()
    site_paths = SitePaths.at(site_root)
    selector = json.loads(site_paths.production_selector.read_text(encoding="utf-8"))
    new_publication_id = selector["publications"][fx.TOPIC_ID]
    assert new_publication_id != old_publication_id

    record = json.loads(
        (site_paths.publications_dir / new_publication_id / "publication.json").read_text(
            encoding="utf-8"
        )
    )
    proof = record["reviewed_equivalence"]
    assert proof is not None
    assert proof["signed_page_hash"] == json.loads(
        (site_paths.publications_dir / old_publication_id / "publication.json").read_text(
            encoding="utf-8"
        )
    )["review"]["page_hash"]

    fired = {rule for rule, count in proof["whitelisted_differences"].items() if count}
    # Evidence, read back from the record rather than assumed: report exactly what fired,
    # so a future change to the renderer or the whitelist shows up here as a failing
    # assertion instead of silent drift.
    assert fired, "widening the locale set moved nothing the whitelist accounts for"
    assert fired <= {
        "locale-alternates",
        "locale-switcher",
        "content-direction",
        "provenance-lineage",
        "provenance-language-count",
        "stat-tooltip-wording",
    }
    # An expansion run is by definition a new run, so its self-description (run id /
    # timestamp) always differs from the signed baseline's — this is the one rule that
    # must always fire, and on this fixture it is the *only* one that does: nothing else
    # in the reviewed zh-CN page's rendered bytes moved when the site went from two
    # locales to three (this fixture's page apparently does not render a distinct "N
    # languages" note the "provenance-language-count" rule would need to redact, unlike
    # a real nine-locale launch's page; the exact rule set is what this assertion pins).
    assert fired == {"provenance-lineage"}

    # verify-candidate independently replays the same proof from disk.
    verified = _run("verify-candidate", str(topics_root), str(site_root), new_publication_id)
    assert verified.returncode == 0, verified.stderr
