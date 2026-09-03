"""Annotate's preflight refuses a corpus that still owes retryable backfill debt.

The cell-coverage gate counts ``group × term_variant`` cells, not outlets, so a
``backfill_debt`` entry used to ride the chain unread and later re-read as "handled"
(search-strategy §1's Indonesia case). This script is where the chain now stops: fresh
debt goes back to collect; exhausted debt passes but is printed for the run report and
touchpoint two. The first regression case is a real corpus's leftover debt on
``aabb-lake-story-2026``.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsab_schema.models import BackfillDebt
from newsab_schema.paths import TopicPaths

REPO = Path(__file__).resolve().parents[1]
PREFLIGHT = REPO / "skills" / "annotate" / "scripts" / "preflight.py"
TOPIC = "test-topic-2026"
RUN = "s2s-202608301200-abcdef01"


def _load():
    sys.path.insert(0, str(PREFLIGHT.parent))  # the script does `import _bootstrap`
    try:
        spec = importlib.util.spec_from_file_location("newsab_annotate_preflight", PREFLIGHT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(PREFLIGHT.parent))
    return module


_preflight = _load()


def _run(*args: object) -> SimpleNamespace:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = _preflight.main([str(arg) for arg in args])
    return SimpleNamespace(returncode=code, stdout=out.getvalue(), stderr=err.getvalue())


def _topic(tmp_path: Path, debts: list[dict], active: bool = True) -> Path:
    root = tmp_path / "topics"
    run_dir = root / TOPIC / "corpus" / "versions" / RUN
    run_dir.mkdir(parents=True)
    (run_dir / "corpus_run.json").write_text(
        json.dumps({"run_id": RUN, "backfill_debt": debts}), encoding="utf-8"
    )
    if active:
        manifest_dir = root / TOPIC / "manifest"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "active.json").write_text(json.dumps({"corpus": RUN}), encoding="utf-8")
    return root


def debt(**overrides) -> dict:
    entry = {"source_id": "outlet", "cell": "all-cells", "reason": "engine walled"}
    entry.update(overrides)
    return entry


def test_fresh_debt_is_refused_back_to_collect(tmp_path):
    root = _topic(tmp_path, [debt(), debt(source_id="other", retries=2)])
    result = _run(root, TOPIC)
    assert result.returncode == 1
    assert "REFUSED" in result.stderr and "--retry-debt" in result.stderr
    assert "outlet:all-cells: retries 0/2" in result.stdout


def test_exhausted_debt_passes_but_is_printed_for_the_report(tmp_path):
    root = _topic(
        tmp_path,
        [debt(retries=2), debt(source_id="telegraph_uk", retry_futile=True)],
    )
    result = _run(root, TOPIC)
    assert result.returncode == 0, result.stderr
    assert "telegraph_uk:all-cells: retry_futile — budget spent" in result.stdout
    assert "touchpoint two" in result.stdout


def test_no_debt_passes_quietly(tmp_path):
    root = _topic(tmp_path, [])
    result = _run(root, TOPIC)
    assert result.returncode == 0
    assert "owes no backfill debt" in result.stdout


def test_missing_active_corpus_run_is_refused(tmp_path):
    root = _topic(tmp_path, [], active=False)
    result = _run(root, TOPIC)
    assert result.returncode == 1
    assert "no active corpus run" in result.stderr


@pytest.mark.cli_e2e
def test_real_cli_smoke(tmp_path):
    root = _topic(tmp_path, [debt()])
    result = subprocess.run(
        [sys.executable, str(PREFLIGHT), str(root), TOPIC],
        capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode == 1
    assert "REFUSED" in result.stderr


@pytest.mark.parametrize(
    ("debts", "expected"),
    [([debt()], 1), ([debt(retries=2)], 0), ([], 0)],
)
def test_gate_matches_the_synthetic_active_record(tmp_path, debts, expected):
    topics_root = _topic(tmp_path, debts)
    payload = json.loads(
        TopicPaths.for_topic(topics_root, TOPIC).corpus_run_file(RUN).read_text(
            encoding="utf-8"
        )
    )
    derived = 1 if any(
        not BackfillDebt.model_validate(item).budget_exhausted
        for item in payload.get("backfill_debt") or []
    ) else 0
    assert derived == expected
    assert _run(topics_root, TOPIC).returncode == expected
