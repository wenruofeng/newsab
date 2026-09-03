"""The stable CLI entry points, exercised the way a contributor would type them."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from submission_fixture import REPO, fx

pytestmark = pytest.mark.cli_e2e


def _run(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = ":".join(
        str(REPO / "packages" / name)
        for name in ("schema", "corpus", "a1", "editorial", "publish", "submission")
    )
    return subprocess.run(
        [sys.executable, "-m", "newsab_submission", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_pack_inspect_verify_cli(fixture_tree, tmp_path):
    root, _ = fixture_tree
    archive = tmp_path / "cli.tgz"
    packed = _run(
        "pack", str(root / "topics"), fx.TOPIC_ID, "--out", str(archive),
        "--submission-id", "SUB-c11c11c11c11c11c",
        "--created-at", "2026-09-01T12:00:00+00:00",
        # No --locales: exactly README's command. The packer derives the two languages
        # the synthetic page is written in instead of the whole SITE_LOCALES set.
        "--json",
    )
    assert packed.returncode == 0, packed.stderr
    assert json.loads(packed.stdout)["topic_id"] == fx.TOPIC_ID

    inspected = _run("inspect", str(archive), "--json")
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout)["ok"] is True

    verified = _run("verify", str(archive), "--json")
    assert verified.returncode == 0, verified.stderr
    report = json.loads(verified.stdout)
    assert report["ok"] is True and "g2" in report["gates"]


def test_cli_refusal_is_structured_and_exit_2(tmp_path):
    junk = tmp_path / "junk.tgz"
    junk.write_bytes(b"not an archive")
    result = _run("verify", str(junk))
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["refused"] is True
    assert payload["issues"][0]["code"] == "G0_ARCHIVE_UNREADABLE"
