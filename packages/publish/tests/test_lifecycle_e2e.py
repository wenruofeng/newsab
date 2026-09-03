"""End-to-end coverage of the publish package's full lifecycle: prepare ->
verify-candidate -> activate -> verify-site.

Manual testing is the only prior coverage of this whole chain; every piece has
its own unit tests, but nothing exercised the lifecycle end to end.  Everything here runs
against a synthetic fixture topic (``lifecycle_fixture.py``, built from schema-valid
Python objects in ``tmp_path``) — no dependency on this machine's real ``topics/`` or
``site/`` trees, so this lane stays outside ``repo_artifact``.

What each test asserts traces back to ``docs/artifact_versioning.md``:

* prepare's candidate hashes match the disk bytes it just wrote (§1: a run record is
  immutable once written) and a second ``prepare`` of the same reviewed bytes is refused
  rather than silently reusing or overwriting it (§6.1: ``write_publication`` "refuses any
  overwrite");
* ``verify-candidate`` re-derives the stored bundle fingerprint from disk and is
  idempotent, and catches one tampered byte in the stored bundle;
* ``activate`` flips the site's active-publication pointer (§6: "mutable status never
  enters the record" — the event stream is authority) and the derived production tree
  reflects it on disk;
* ``verify-site`` re-derives the deployed pages as "approved bytes ⊕ release origin"
  (§6 item 5) and is idempotent, and catches one tampered byte in the deployed tree.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

EXAMPLE_DIR = Path(__file__).resolve().parents[3] / "examples" / "synthetic-topic"
sys.path.insert(0, str(EXAMPLE_DIR))
import demo_fixture as fx  # noqa: E402
from newsab_publish.builder import (
    bytes_digest,
    default_theme_registry_path,
    directory_fingerprint,
    activate_publication,
    prepare_publication,
    render_candidate_bundle,
    resolve_inputs,
    verify_candidate,
    verify_site,
)
from newsab_publish.themes import load_theme_registry, resolve_theme
from newsab_schema.io import ArtifactError
from newsab_schema.models.publication import HumanApproval, PublicationReview
from newsab_schema.paths import SitePaths

BASE_URL = "https://example.org"
BUILD_DATE = date(2026, 8, 29)


# --------------------------------------------------------------------------------------
# fixtures: a fresh synthetic topic + site-metadata revision per test, then a reviewed
# candidate built from them, then that candidate activated onto a fresh production tree.
# --------------------------------------------------------------------------------------


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
    return fx.build_metadata(metadata_path)


def _reviewed_page_hash(topics_root, metadata, scratch) -> str:
    """Render once, off to the side, to learn the exact bytes a reviewer is about to
    sign — this is what the render-localize reviewer actually approves at touchpoint
    two; ``prepare_publication`` then re-proves the same bytes twice more on its own."""
    resolved = resolve_inputs(topics_root, fx.TOPIC_ID, fx.PAGE_RUN_ID)
    registry = load_theme_registry(default_theme_registry_path())
    theme = resolve_theme(None, registry)
    bundles, _, _ = render_candidate_bundle(
        resolved, metadata.locales, scratch, m2=True, theme=theme
    )
    return next(b.page_hash for b in bundles if b.locale == fx.REVIEW_LOCALE)


def _review(page_hash: str, *, approval_suffix: str = "0123abcd") -> PublicationReview:
    return PublicationReview(
        approval_id=f"APR-aabb-river-light-{approval_suffix}",
        reviewer_id="test-founder",
        decided_at=datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
        locale=fx.REVIEW_LOCALE,
        page_hash=page_hash,
    )


@pytest.fixture
def prepared(topics_root, site_root, metadata, metadata_path, tmp_path):
    scratch = tmp_path / "scratch-review"
    scratch.mkdir()
    review = _review(_reviewed_page_hash(topics_root, metadata, scratch))
    return prepare_publication(
        topics_root,
        site_root,
        fx.TOPIC_ID,
        page_run_id=fx.PAGE_RUN_ID,
        review=review,
        metadata=metadata,
        metadata_path=metadata_path,
    )


@pytest.fixture
def activated(prepared, topics_root, site_root, metadata):
    production_dir = site_root / "public"
    approval = HumanApproval(
        approval_id="APR-aabb-river-light-1123abcd",
        reviewer_id="test-founder",
        decided_at=datetime(2026, 8, 29, 12, 5, tzinfo=timezone.utc),
    )
    event = activate_publication(
        topics_root,
        site_root,
        prepared.publication_id,
        approval=approval,
        metadata=metadata,
        production_dir=production_dir,
        base_url=BASE_URL,
        build_date=BUILD_DATE,
    )
    return SimpleNamespace(
        event=event,
        production_dir=production_dir,
        publication_id=prepared.publication_id,
    )


def _page_path(root, locale: str):
    return root / locale / "topics" / fx.TOPIC_ID / "index.html"


# --------------------------------------------------------------------------------------
# (a) prepare produces a candidate whose recorded hashes match the disk bytes, and the
#     candidate is immutable once written (artifact_versioning.md §1, §6.1).
# --------------------------------------------------------------------------------------


def test_prepare_produces_a_candidate_whose_hashes_match_disk_bytes(prepared, site_root):
    site_paths = SitePaths.at(site_root)
    bundle_dir = site_paths.publication_dir(prepared.publication_id) / "bundle"

    assert directory_fingerprint(bundle_dir) == prepared.public_bundle_fingerprint
    for locale_bundle in prepared.locales:
        page_bytes = _page_path(bundle_dir, locale_bundle.locale).read_bytes()
        assert bytes_digest(page_bytes) == locale_bundle.page_hash
    # The reviewed locale's bytes are exactly the ones the review record signed.
    reviewed_bytes = _page_path(bundle_dir, prepared.review.locale).read_bytes()
    assert bytes_digest(reviewed_bytes) == prepared.review.page_hash


def test_prepare_refuses_to_reprepare_the_same_reviewed_bytes(
    prepared, topics_root, site_root, metadata, metadata_path, tmp_path
):
    """§6.1: ``write_publication`` "refuses any overwrite" — a second prepare of the
    exact same reviewed bytes must not silently reuse or replace the immutable candidate
    it already wrote."""
    scratch = tmp_path / "scratch-review-again"
    scratch.mkdir()
    review = _review(_reviewed_page_hash(topics_root, metadata, scratch))
    with pytest.raises(ArtifactError, match="refusing to overwrite"):
        prepare_publication(
            topics_root,
            site_root,
            fx.TOPIC_ID,
            page_run_id=fx.PAGE_RUN_ID,
            review=review,
            metadata=metadata,
            metadata_path=metadata_path,
        )


# --------------------------------------------------------------------------------------
# (b) verify-candidate passes untouched and fails on one tampered bundle byte; idempotent.
# --------------------------------------------------------------------------------------


def test_verify_candidate_passes_on_the_untouched_candidate_and_is_idempotent(
    prepared, topics_root, site_root
):
    first = verify_candidate(topics_root, site_root, prepared.publication_id)
    second = verify_candidate(topics_root, site_root, prepared.publication_id)
    assert first == second == prepared


def test_verify_candidate_fails_when_a_bundle_byte_is_tampered(
    prepared, topics_root, site_root
):
    site_paths = SitePaths.at(site_root)
    bundle_dir = site_paths.publication_dir(prepared.publication_id) / "bundle"
    target = _page_path(bundle_dir, prepared.review.locale)
    original = target.read_bytes()
    target.write_bytes(original.replace(b"</html>", b"<!--tampered--></html>", 1))
    try:
        with pytest.raises(ArtifactError):
            verify_candidate(topics_root, site_root, prepared.publication_id)
    finally:
        target.write_bytes(original)
    # Restoring the exact bytes makes it verifiable again — the check is over content,
    # not over having-ever-been-touched.
    verify_candidate(topics_root, site_root, prepared.publication_id)


# --------------------------------------------------------------------------------------
# (c) activate flips the active pointer / production state, correctly reflected on disk.
# --------------------------------------------------------------------------------------


def test_activate_flips_the_active_pointer_and_deploys_the_candidate(
    activated, site_root
):
    site_paths = SitePaths.at(site_root)
    assert activated.event.event_type.value == "publish"

    stored_selector = __import__("json").loads(
        site_paths.production_selector.read_text(encoding="utf-8")
    )
    assert stored_selector["publications"][fx.TOPIC_ID] == activated.publication_id

    deployed = _page_path(activated.production_dir, fx.REVIEW_LOCALE)
    assert deployed.is_file()
    assert (site_paths.production_dir / "release.json").is_file()


def test_activate_of_a_second_candidate_supersedes_the_first(
    activated, topics_root, site_root, metadata, metadata_path, tmp_path
):
    """The lifecycle's other transition: a live topic re-prepared and re-activated
    supersedes, rather than duplicates, the previously live publication (§6: "the event
    stream is authority")."""
    # A second, distinct reviewer decision on the *same* approved bytes is enough to mint
    # a second publication_id (the id folds the review's approval_id in).
    scratch = tmp_path / "scratch-review-second"
    scratch.mkdir()
    review = _review(
        _reviewed_page_hash(topics_root, metadata, scratch), approval_suffix="2223abcd"
    )
    second = prepare_publication(
        topics_root,
        site_root,
        fx.TOPIC_ID,
        page_run_id=fx.PAGE_RUN_ID,
        review=review,
        metadata=metadata,
        metadata_path=metadata_path,
    )
    assert second.publication_id != activated.publication_id

    approval = HumanApproval(
        approval_id="APR-aabb-river-light-3123abcd",
        reviewer_id="test-founder",
        decided_at=datetime(2026, 8, 29, 12, 10, tzinfo=timezone.utc),
    )
    with pytest.raises(ArtifactError, match="supersede requires an explicit approved reason"):
        activate_publication(
            topics_root,
            site_root,
            second.publication_id,
            approval=approval,
            metadata=metadata,
            production_dir=activated.production_dir,
            base_url=BASE_URL,
            build_date=BUILD_DATE,
        )

    from newsab_schema.common import LangText

    event = activate_publication(
        topics_root,
        site_root,
        second.publication_id,
        approval=approval,
        metadata=metadata,
        production_dir=activated.production_dir,
        base_url=BASE_URL,
        build_date=BUILD_DATE,
        reason=LangText(text="testing the supersede transition", lang="en"),
    )
    assert event.event_type.value == "supersede"
    assert event.publication_id == activated.publication_id
    assert event.replacement_publication_id == second.publication_id

    site_paths = SitePaths.at(site_root)
    stored_selector = __import__("json").loads(
        site_paths.production_selector.read_text(encoding="utf-8")
    )
    assert stored_selector["publications"][fx.TOPIC_ID] == second.publication_id


# --------------------------------------------------------------------------------------
# (d) verify-site passes on the activated site and fails after tampering with a deployed
#     page; idempotent.
# --------------------------------------------------------------------------------------


def test_verify_site_passes_on_the_activated_site_and_is_idempotent(
    activated, topics_root, site_root, metadata
):
    first = verify_site(topics_root, site_root, activated.production_dir, metadata=metadata)
    second = verify_site(topics_root, site_root, activated.production_dir, metadata=metadata)
    assert first == second
    assert first == directory_fingerprint(activated.production_dir)


def test_verify_site_fails_when_a_deployed_page_is_tampered(
    activated, topics_root, site_root, metadata
):
    target = _page_path(activated.production_dir, fx.REVIEW_LOCALE)
    original = target.read_bytes()
    target.write_bytes(original.replace(b"</html>", b"<!--tampered--></html>", 1))
    try:
        with pytest.raises(ArtifactError):
            verify_site(topics_root, site_root, activated.production_dir, metadata=metadata)
    finally:
        target.write_bytes(original)
    # Restored bytes verify again — same "content, not history" discipline as (b).
    verify_site(topics_root, site_root, activated.production_dir, metadata=metadata)
