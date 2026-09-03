"""Round-trip and determinism: pack → G0 → G1 → G2 on the public synthetic fixture."""

from __future__ import annotations

import json
import tarfile

import pytest

from submission_fixture import fx, pack_fixture

from newsab_publish.builder import resolve_inputs
from newsab_schema.models.manifest import file_digest
from newsab_submission.envelope import CLOSURE_STAGES, ENVELOPE_MEMBER
from newsab_submission.g0 import inspect_archive
from newsab_submission.resolver import resolve_submission_inputs
from newsab_submission.verify import verify_archive


def test_pack_report_shape(good_archive):
    _, report = good_archive
    assert report["operation"] == "create"
    assert report["topic_id"] == fx.TOPIC_ID
    assert report["page_run_id"] == fx.PAGE_RUN_ID
    assert report["archive_sha256"].startswith("sha256:")
    assert report["members"] > 10


def test_envelope_is_first_member_and_paths_are_canonical(good_archive):
    archive, _ = good_archive
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
    assert names[0] == ENVELOPE_MEMBER
    assert names[1:] == sorted(names[1:])
    for name in names[1:]:
        assert name.startswith("topic/") or name == "sources/registry.yaml"
    assert not any(name.endswith(".html") for name in names)


def test_inspect_streams_without_extraction(good_archive):
    archive, _ = good_archive
    report = inspect_archive(archive)
    assert report.member_count == len(tarfile.open(archive, "r:gz").getnames())
    assert report.total_uncompressed > report.archive_bytes / 100


def test_verify_roundtrip(good_archive):
    archive, packed = good_archive
    report = verify_archive(archive)
    assert report["ok"] is True
    assert report["submission_id"] == packed["submission_id"]
    stages = [pin["stage"] for pin in report["gates"]["g1"]["run_closure"]]
    assert stages == list(CLOSURE_STAGES)
    g2 = report["gates"]["g2"]
    assert g2["findings"] == 3
    assert g2["candidate_fingerprint"].startswith("sha256:")


def test_pack_is_deterministic(fixture_tree, tmp_path):
    root, _ = fixture_tree
    first = pack_fixture(root, tmp_path / "a.tgz")
    second = pack_fixture(root, tmp_path / "b.tgz")
    assert first["archive_sha256"] == second["archive_sha256"]
    assert file_digest(tmp_path / "a.tgz") == file_digest(tmp_path / "b.tgz")


def test_resolver_parity_with_stage8(fixture_tree):
    """The submission resolver and the builder must agree on an overlay-free closure."""
    root, _ = fixture_tree
    ours = resolve_submission_inputs(
        root / "topics", fx.TOPIC_ID, fx.PAGE_RUN_ID, overlay={}
    )
    theirs = resolve_inputs(root / "topics", fx.TOPIC_ID, fx.PAGE_RUN_ID)
    assert tuple(ours.pins) == tuple(theirs.pins)
    assert ours.topics_by_article_bytes == theirs.topics_by_article_bytes
    assert ours.source_registry_bytes == theirs.source_registry_bytes


def test_withdraw_archive_carries_no_closure(fixture_tree, tmp_path):
    root, _ = fixture_tree
    out = tmp_path / "withdraw.tgz"
    report = pack_fixture(
        root,
        out,
        operation="withdraw",
        prior_publication_id="PUB-aabb-river-light-2026-000000000000",
    )
    assert report["members"] == 1
    with tarfile.open(out, "r:gz") as tar:
        assert tar.getnames() == [ENVELOPE_MEMBER]
        envelope = json.load(tar.extractfile(ENVELOPE_MEMBER))
    assert envelope["operation"] == "withdraw"
    verified = verify_archive(out)
    assert verified["ok"] is True
    assert "g2" not in verified["gates"]


def test_pack_refuses_unsupported_locale(fixture_tree, tmp_path):
    root, _ = fixture_tree
    with pytest.raises(Exception, match="locales"):
        pack_fixture(root, tmp_path / "bad.tgz", requested_locales=("de",))


def test_pack_defaults_to_the_locales_the_page_carries(fixture_tree, tmp_path):
    """README's bare ``pack`` must verify: a two-language page asks for two locales,
    not the whole growing SITE_LOCALES set the trusted renderer would refuse."""
    root, _ = fixture_tree
    out = tmp_path / "default.tgz"
    pack_fixture(root, out, requested_locales=None)
    with tarfile.open(out, "r:gz") as tar:
        envelope = json.load(tar.extractfile(ENVELOPE_MEMBER))
    assert set(envelope["requested_locales"]) == {"en", "zh-CN"}
    assert verify_archive(out)["ok"] is True
