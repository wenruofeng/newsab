from __future__ import annotations

import os

import pytest

from newsab_publish.builder import (
    PACKAGE_VERSION,
    event_time,
    _load_topics_by_article,
    load_submission_provenance,
    submission_topics_root,
    SUPPORTED_PACKAGE_VERSIONS,
    _is_canonical_public,
    _registry_from_bytes,
    _run_closure_matches,
    bytes_digest,
    directory_fingerprint,
    resolve_publication_locales,
    scan_public_bundle,
    write_closed_file,
)
from newsab_schema.io import ArtifactError
from newsab_schema.models.publication import TopicRunPin
from newsab_schema.paths import SitePaths, TopicPaths


def test_directory_fingerprint_is_path_and_byte_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    write_closed_file(first, "zh-CN/index.html", b"home\n")
    write_closed_file(first, "robots.txt", b"User-agent: *\n")
    write_closed_file(second, "robots.txt", b"User-agent: *\n")
    write_closed_file(second, "zh-CN/index.html", b"home\n")

    assert directory_fingerprint(first) == directory_fingerprint(second)
    assert bytes_digest(b"home\n").startswith("sha256:")


def test_closed_output_rejects_escape_duplicate_symlink_and_private_markers(tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    with pytest.raises(ArtifactError, match="unsafe public output"):
        write_closed_file(root, "../escape", b"bad")
    write_closed_file(root, "index.html", b"safe")
    with pytest.raises(ArtifactError, match="repeats"):
        write_closed_file(root, "index.html", b"again")

    marker = root / "marker.html"
    marker.write_text("corpus/articles/private.json", encoding="utf-8")
    with pytest.raises(ArtifactError, match="forbidden marker"):
        scan_public_bundle(root)
    marker.unlink()

    target = root / "target.txt"
    target.write_text("safe", encoding="utf-8")
    link = root / "link.txt"
    os.symlink(target, link)
    with pytest.raises(ArtifactError, match="symlink"):
        scan_public_bundle(root)


def test_public_scan_rejects_executable_input(tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    script = root / "run.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    with pytest.raises(ArtifactError, match="executable"):
        scan_public_bundle(root)


def test_public_scan_reads_markers_in_non_utf8_files(tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    binary = root / "asset.bin"
    binary.write_bytes(b"\xff\xfe\x00" + b"corpus/articles/leak.json" + b"\x00")
    with pytest.raises(ArtifactError, match="forbidden marker"):
        scan_public_bundle(root)


def test_release_and_catalog_authority_only_follow_the_canonical_public_tree(tmp_path):
    site_paths = SitePaths.at(tmp_path / "site").ensure()
    assert _is_canonical_public(site_paths, tmp_path / "site" / "public")
    assert not _is_canonical_public(site_paths, tmp_path / "preview")
    assert not _is_canonical_public(site_paths, tmp_path / "site")


def test_current_producer_is_among_the_supported_versions():
    assert PACKAGE_VERSION in SUPPORTED_PACKAGE_VERSIONS
    assert "publish-0.1.0" in SUPPORTED_PACKAGE_VERSIONS
    assert "publish-0.2.0" in SUPPORTED_PACKAGE_VERSIONS


def _pin(
    stage: str,
    fingerprint: str,
    *,
    run_id: str = "scp-20260821005016059108-a7c0fe01",
) -> TopicRunPin:
    return TopicRunPin(
        topic_id="aabb-old-map-2005",
        stage=stage,
        run_id=run_id,
        artifact_fingerprint=fingerprint,
    )


def test_run_closure_accepts_only_the_audited_scope_fingerprint_migration():
    legacy = _pin(
        "scope",
        "sha256:092264c48f30f732c1d61a6fa16861ec78a8e4a626d4a803f8466358d1ba0450",
    )
    migrated = _pin(
        "scope",
        "sha256:497e362a186c45993e805b0ed0449e152e18f37427cbe659f57d69e98fbdc79d",
    )
    assert _run_closure_matches([legacy], [migrated])
    assert _run_closure_matches([migrated], [migrated])

    unknown = _pin("scope", "sha256:" + "0" * 64)
    changed_run = migrated.model_copy(
        update={"run_id": "scp-20260821005016059108-b7c0fe02"}
    )
    changed_stage = migrated.model_copy(update={"stage": "corpus"})
    assert not _run_closure_matches([legacy], [unknown])
    assert not _run_closure_matches([legacy], [changed_run])
    assert not _run_closure_matches([legacy], [changed_stage])
    assert not _run_closure_matches([legacy], [migrated, migrated])


def test_rerender_tier_is_decided_by_liveness_not_by_producer_version():
    """Regression: a *superseded* record that happened to share the current
    producer version was asked to re-render with today's renderer and necessarily
    failed, because the renderer moved after it was stamped.  The
    re-render tier is liveness: live for the topic, or a candidate the event stream has
    never touched."""
    from types import SimpleNamespace

    from newsab_publish.builder import _live_publication_ids

    events = [
        # publish A; supersede A → B; publish D; withdraw D.
        SimpleNamespace(publication_id="PUB-t1-a", replacement_publication_id=None),
        SimpleNamespace(publication_id="PUB-t1-a", replacement_publication_id="PUB-t1-b"),
        SimpleNamespace(publication_id="PUB-t2-d", replacement_publication_id=None),
        SimpleNamespace(publication_id="PUB-t2-d", replacement_publication_id=None),
    ]
    publications = {name: object() for name in ("PUB-t1-a", "PUB-t1-b", "PUB-t1-c", "PUB-t2-d")}
    selector = SimpleNamespace(publications={"t1": "PUB-t1-b"})

    tier = _live_publication_ids(publications, events, selector)

    # The live replacement and the never-activated reviewed candidate re-render; the
    # superseded and the withdrawn records answer to their archived bundles only,
    # whatever producer stamped them.
    assert tier == frozenset({"PUB-t1-b", "PUB-t1-c"})


def test_registry_from_bytes_round_trips_and_defaults_empty():
    assert _registry_from_bytes(b"").sources == []
    from pathlib import Path

    payload = (Path(__file__).parents[3] / "sources" / "registry.yaml").read_bytes()
    registry = _registry_from_bytes(payload)
    assert registry.sources, "the real registry must round-trip through the pinned bytes"


def test_an_events_time_is_when_it_happens_not_when_it_was_approved():
    """Regression: a batch authorized in one sitting could not be activated.

    Five topics approved in the review shell get five approvals stamped inside the same
    second, and the order they are activated in has nothing to do with the order they were
    signed in.  Reading ``occurred_at`` straight off the approval therefore produced a
    chain that stepped backwards, and the fifth ``activate`` was refused with the whole
    production tree already half-replaced.
    """
    from datetime import datetime, timedelta, timezone

    from newsab_schema.common import Provenance
    from newsab_schema.models.publication import HumanApproval, PublicationEvent

    def approval(second: int) -> HumanApproval:
        return HumanApproval(
            approval_id="APR-aabb-river-light-2026-0123abcd",
            reviewer_id="founder",
            decided_at=datetime(2026, 8, 27, 18, 44, second, tzinfo=timezone.utc),
        )

    def event(when: datetime) -> PublicationEvent:
        return PublicationEvent(
            event_id="EVT-20260827184448-0123abcd",
            event_type="publish",
            publication_id="PUB-aabb-river-light-2026-0123456789ab",
            publication_hash="sha256:" + "a" * 64,
            approval=approval(48),
            occurred_at=when,
            provenance=Provenance(
                skill_version="publish-0.4.0",
                model_id=None,
                run_id="evt-x",
                timestamp=when,
            ),
        )

    now = datetime(2026, 8, 27, 18, 52, 32, tzinfo=timezone.utc)
    head = event(datetime(2026, 8, 27, 18, 44, 48, tzinfo=timezone.utc))

    # The approval signed a second *earlier* than the chain head no longer drags the event
    # backwards: it happens now, after both.
    assert event_time(approval(47), [head], now=now) == now

    # A clock behind the approval or behind the chain still cannot step backwards.
    stale = datetime(2026, 8, 27, 18, 40, 0, tzinfo=timezone.utc)
    assert event_time(approval(47), [], now=stale) == approval(47).decided_at
    assert event_time(approval(47), [head], now=stale) == head.occurred_at

    # And the sub-second part is dropped, so two events in one second compare equal
    # rather than by a precision the chain never records.
    assert event_time(approval(47), [], now=now + timedelta(microseconds=7)) == now


def test_publication_locales_default_to_the_whole_site_localization_set(metadata):
    # One file names every language the site ships; nobody retypes it at a call site.
    assert resolve_publication_locales(metadata, "zh-CN") == tuple(metadata.locales)
    assert "en" in metadata.locales


def test_publication_always_ships_the_pivot_and_the_reviewers_language(metadata):
    # The reviewer signs the page, not one rendering of it: narrowing the set to their
    # own language is what once left publications with no English page at all.
    with pytest.raises(ArtifactError) as missing_pivot:
        resolve_publication_locales(metadata, "zh-CN", ["zh-CN"])
    assert "'en'" in str(missing_pivot.value)

    with pytest.raises(ArtifactError) as missing_reviewer:
        resolve_publication_locales(metadata, "zh-CN", ["en"])
    assert "'zh-CN'" in str(missing_reviewer.value)

    # A narrower explicit build is still allowed once it clears the floor.
    assert resolve_publication_locales(metadata, "zh-CN", ["en", "zh-CN"]) == ("en", "zh-CN")


def test_a_language_the_chrome_cannot_speak_is_named_not_crashed_on(metadata):
    # The half-added language: content metadata lists it, the renderer's own strings do
    # not.  ``de`` is outside the halo's nine, so it stays the half-added case now that
    # the halo's own LTR languages have moved into ``SITE_LOCALES``.
    with pytest.raises(ArtifactError) as excinfo:
        resolve_publication_locales(metadata, "zh-CN", ["en", "zh-CN", "de"])
    assert "site chrome has no strings" in str(excinfo.value)
    assert "de" in str(excinfo.value)


def test_topics_by_article_prefers_the_shipped_map(tmp_path):
    """An imported submission namespace has the derived map and no staging inputs.

    Deriving from an absent staging directory is not an error — it is an empty mapping,
    which renders a page with an empty concept cloud while every gate recomputed the full
    one.  The shipped file has to win wherever it exists.
    """
    import json

    paths = TopicPaths.for_topic(tmp_path, "aabb-river-light-2026").ensure()
    shipped = paths.corpus_dir / "topics_by_article.json"
    shipped.parent.mkdir(parents=True, exist_ok=True)

    # No shipped file and no staging notes: nothing to show, and that is not a failure.
    assert _load_topics_by_article(paths)[0] == {}

    mapping = {"JP_0123abcd": [{"pivot_en": "a concept", "source_phrase": "原文"}]}
    shipped.write_text(json.dumps(mapping), encoding="utf-8")
    loaded, payload = _load_topics_by_article(paths)
    assert loaded == mapping
    from newsab_publish.builder import canonical_json_bytes

    assert payload == canonical_json_bytes(mapping)

    shipped.write_text("[]", encoding="utf-8")
    with pytest.raises(ArtifactError, match="must be a JSON object"):
        _load_topics_by_article(paths)
    shipped.write_text("{", encoding="utf-8")
    with pytest.raises(ArtifactError, match="not valid JSON"):
        _load_topics_by_article(paths)


def _import_fixture(site_root, *, submission_id="SUB-0123456789abcdef", topic_id="aabb-river-light-2026", ok=True, run_id="g3-20260903195201547723-9d4865d1"):
    """The shape `newsab_intake.import_submission` leaves on disk."""
    import json

    base = site_root / "submissions" / "imported" / submission_id
    (base / "namespace" / "ns_1" / "topics" / topic_id).mkdir(parents=True)
    (base / "import.json").write_text(json.dumps({
        "submission_id": submission_id,
        "source_topic_id": topic_id,
        "namespace_path": "namespace/ns_1",
        "archive_sha256": "sha256:" + "9" * 64,
        "verification_ok": True,
    }), encoding="utf-8")
    (base / "envelope.json").write_text(
        json.dumps({"sponsor": {"anonymous": False, "display_name": "A Contributor"}}),
        encoding="utf-8",
    )
    (base / "g3").mkdir()
    (base / "g3" / "record.json").write_text(json.dumps({
        "ok": ok,
        "archive_sha256": "sha256:" + "9" * 64,
        "run_id": run_id,
    }), encoding="utf-8")
    return base


def test_a_submission_publication_is_resolved_from_its_own_record(tmp_path):
    """Every rebuild walks all live publications with one --topics-root.

    A submitted topic is not in that tree, so the record has to carry where it is — and
    it may not be published at all without the independent audit pinned.
    """
    import json

    from newsab_schema.io import ArtifactError
    from newsab_schema.paths import SitePaths

    site = SitePaths.at(tmp_path / "site")
    _import_fixture(site.root)
    provenance = load_submission_provenance(site, "SUB-0123456789abcdef", "aabb-river-light-2026")
    assert provenance.audit_run_id == "g3-20260903195201547723-9d4865d1"
    assert provenance.archive_hash == "sha256:" + "9" * 64
    assert provenance.sponsor.display_name == "A Contributor"
    assert provenance.topics_root == site.root / "submissions" / "imported" / "SUB-0123456789abcdef" / "namespace" / "ns_1" / "topics"
    assert submission_topics_root(site, "SUB-0123456789abcdef") == provenance.topics_root

    # The record's own answer wins over the caller's root, and only for a submission.
    class _Record:
        submission_id = "SUB-0123456789abcdef"

    from newsab_publish.builder import publication_topics_root

    assert publication_topics_root(tmp_path / "topics", site, _Record()) == provenance.topics_root
    _Record.submission_id = None
    assert publication_topics_root(tmp_path / "topics", site, _Record()) == tmp_path / "topics"

    # A different topic, and a G3 record that did not pass, are both refusals.
    with pytest.raises(ArtifactError, match="imported topic"):
        load_submission_provenance(site, "SUB-0123456789abcdef", "aabb-other-2026")
    failed = SitePaths.at(tmp_path / "failed")
    base = _import_fixture(failed.root, ok=False)
    with pytest.raises(ArtifactError, match="no clean G3 record"):
        load_submission_provenance(failed, "SUB-0123456789abcdef", "aabb-river-light-2026")

    # A clean audit with no run id cannot be pinned, so it cannot be published from.
    payload = json.loads((base / "g3" / "record.json").read_text(encoding="utf-8"))
    (base / "g3" / "record.json").write_text(
        json.dumps({**payload, "ok": True, "run_id": ""}), encoding="utf-8"
    )
    with pytest.raises(ArtifactError, match="no run_id to pin"):
        load_submission_provenance(failed, "SUB-0123456789abcdef", "aabb-river-light-2026")
