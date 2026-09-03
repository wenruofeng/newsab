"""Adversarial archives (plan §9-P2 exit): every bad package fails with a structured
error before any model or agent stage — nothing from an archive is ever executed.

Each case starts from the good synthetic archive and rewrites it at the tar level, so
the failures exercise the real streaming reader, not shortcuts in the packer.
"""

from __future__ import annotations

import gzip
import io
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from submission_fixture import build_tree, fx, pack_fixture

from newsab_schema.models.manifest import file_digest
from newsab_submission.envelope import ENVELOPE_MEMBER
from newsab_submission.errors import SubmissionRefused
from newsab_submission.g0 import ArchiveLimits, inspect_archive
from newsab_submission.verify import verify_archive


def load_entries(archive: Path) -> list[tuple[tarfile.TarInfo, bytes | None]]:
    entries = []
    with tarfile.open(archive, "r:gz") as tar:
        for info in tar:
            stream = tar.extractfile(info)
            entries.append((info, stream.read() if stream is not None else None))
    return entries


def write_entries(path: Path, entries) -> Path:
    with open(path, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tar:
                for info, payload in entries:
                    tar.addfile(info, io.BytesIO(payload) if payload is not None else None)
    return path


def data_entry(name: str, payload: bytes, **attrs) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    info.mtime = 0
    for key, value in attrs.items():
        setattr(info, key, value)
    return info, payload


def rewrite_envelope(entries, mutate) -> None:
    """Apply ``mutate(payload_dict)`` to the envelope entry in place."""
    info, payload = entries[0]
    assert info.name == ENVELOPE_MEMBER
    body = json.loads(payload.decode("utf-8"))
    mutate(body)
    new = (json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    info.size = len(new)
    entries[0] = (info, new)


def expect_refusal(archive: Path, code: str) -> SubmissionRefused:
    with pytest.raises(SubmissionRefused) as caught:
        verify_archive(archive)
    codes = [issue.code for issue in caught.value.issues]
    assert code in codes, f"expected {code}, got {codes}"
    return caught.value


# --- G0: structural safety ---------------------------------------------------------


def test_traversal_path_refused(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    entries.append(data_entry("topic/../../evil.json", b"{}"))
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G0_PATH_TRAVERSAL")


def test_absolute_path_refused(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    entries.append(data_entry("/etc/evil.json", b"{}"))
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G0_PATH_TRAVERSAL")


def test_symlink_refused(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    info = tarfile.TarInfo(name="topic/link.json")
    info.type = tarfile.SYMTYPE
    info.linkname = "../../outside"
    entries.append((info, None))
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G0_MEMBER_TYPE")


def test_html_member_refused(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    entries.append(data_entry("topic/page.html", b"<script>alert(1)</script>"))
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G0_EXTENSION_FORBIDDEN")


def test_script_member_refused(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    entries.append(data_entry("topic/setup.py", b"import os"))
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G0_EXTENSION_FORBIDDEN")


def test_duplicate_path_refused(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    entries.append(data_entry("topic/topic_manifest.yaml", b"topic_id: fake"))
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G0_PATH_DUPLICATE")


def test_envelope_must_come_first(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    entries.append(entries.pop(0))
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G0_ENVELOPE_FIRST")


def test_zip_bomb_metadata_refused(good_archive, tmp_path):
    """A tiny archive expanding into a huge member trips the streaming caps."""
    entries = load_entries(good_archive[0])
    entries.append(data_entry("topic/bomb.json", b"\0" * (8 * 1024 * 1024)))
    bomb = write_entries(tmp_path / "t.tgz", entries)
    with pytest.raises(SubmissionRefused) as caught:
        inspect_archive(bomb, ArchiveLimits(max_total_uncompressed=1024 * 1024))
    assert caught.value.issues[0].code == "G0_TOTAL_TOO_LARGE"
    with pytest.raises(SubmissionRefused) as caught:
        inspect_archive(bomb, ArchiveLimits(max_compression_ratio=10.0))
    assert caught.value.issues[0].code == "G0_COMPRESSION_RATIO"


def test_not_an_archive_refused(tmp_path):
    junk = tmp_path / "junk.tgz"
    junk.write_bytes(b"certainly not a tarball")
    with pytest.raises(SubmissionRefused) as caught:
        inspect_archive(junk)
    assert caught.value.issues[0].code == "G0_ARCHIVE_UNREADABLE"


# --- G1: protocol and closure ------------------------------------------------------


def test_hash_mismatch_refused(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    for index, (info, payload) in enumerate(entries):
        if info.name.endswith("questions.yaml"):
            tampered = payload + b"\n# tampered\n"
            info.size = len(tampered)
            entries[index] = (info, tampered)
            break
    else:
        pytest.fail("fixture archive has no questions.yaml")
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G1_MEMBER_HASH_MISMATCH")


def test_undeclared_member_refused(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    entries.append(data_entry("topic/corpus/extra.json", b"{}"))
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G1_MEMBER_UNDECLARED")


def test_declared_but_missing_member_refused(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    entries = [
        (info, payload)
        for info, payload in entries
        if not info.name.endswith("question_stats.json")
    ]
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G1_MEMBER_MISSING")


def test_member_outside_closure_refused(good_archive, tmp_path):
    from newsab_submission.closure import sha256_bytes

    entries = load_entries(good_archive[0])
    payload = b'{"unrelated": true}'
    entries.append(data_entry("topic/corpus/articles/ZZ_deadbeef.json", payload))
    rewrite_envelope(
        entries,
        lambda body: body["members"].append(
            {
                "path": "topic/corpus/articles/ZZ_deadbeef.json",
                "sha256": sha256_bytes(payload),
                "size_bytes": len(payload),
                "kind": "included",
            }
        ),
    )
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G1_MEMBER_OUTSIDE_CLOSURE")


def test_missing_run_refused(good_archive, tmp_path):
    """Dropping a pinned run's files (with a matching envelope) breaks closure resolution."""
    entries = load_entries(good_archive[0])
    prefix = f"topic/analysis/{fx.QA_RUN_ID}/"
    entries = [(info, payload) for info, payload in entries if not info.name.startswith(prefix)]
    rewrite_envelope(
        entries,
        lambda body: body.update(
            members=[m for m in body["members"] if not m["path"].startswith(prefix)]
        ),
    )
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G1_CLOSURE_RESOLUTION")


def test_unsupported_protocol_refused(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    rewrite_envelope(entries, lambda body: body.update(protocol_version="1.0.0"))
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G1_PROTOCOL_UNSUPPORTED")


def test_hash_only_outside_page_previews_refused(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    rewrite_envelope(
        entries,
        lambda body: body["members"].append(
            {
                "path": "topic/corpus/evil.html",
                "sha256": "sha256:" + "0" * 64,
                "size_bytes": 4,
                "kind": "hash_only",
            }
        ),
    )
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G1_HASH_ONLY_DISALLOWED")


# --- G2: trusted recomputation -----------------------------------------------------


def test_tampered_finding_survives_g1_but_fails_g2(tmp_path):
    """A self-consistent tamper (bytes, manifest and envelope all rewritten) still
    fails: the trusted analyzer recomputes the findings from the archived inputs."""
    root = tmp_path / "tree"
    paths = build_tree(root)
    findings_path = paths.a1_run_dir(fx.QA_RUN_ID) / "findings.jsonl"
    lines = findings_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["stability"] = 0.42
    lines[0] = json.dumps(record, ensure_ascii=False, sort_keys=True)
    findings_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    manifest_path = paths.manifest
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    relative = findings_path.relative_to(paths.root).as_posix()
    for row in rows:
        if row["run_id"] == fx.QA_RUN_ID:
            row["output_hashes"][relative] = file_digest(findings_path)
    manifest_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    archive = tmp_path / "tampered.tgz"
    pack_fixture(root, archive)
    refusal = expect_refusal(archive, "G2_ANALYSIS_MISMATCH")
    assert refusal.issues[0].gate == "G2"


def test_revise_operation_refused_by_name(good_archive, tmp_path):
    """No revision procedure — the refusal names the withdraw-then-create path."""
    entries = load_entries(good_archive[0])
    rewrite_envelope(entries, lambda body: body.update(operation="revise", prior_publication_id="PUB-x-000000000000"))
    refusal = expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G1_ENVELOPE_SCHEMA")
    assert any("revision is not offered" in issue.message for issue in refusal.issues)


def test_withdraw_with_data_members_refused(good_archive, tmp_path):
    entries = load_entries(good_archive[0])
    rewrite_envelope(entries, lambda body: body.update(operation="withdraw", prior_publication_id="PUB-x-000000000000"))
    expect_refusal(write_entries(tmp_path / "t.tgz", entries), "G1_ENVELOPE_SCHEMA")
