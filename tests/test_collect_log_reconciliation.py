"""The collection log has to account for the articles in the corpus.

``aabb-island-dance-2024``'s first round logged 76 queries, every one of them reading
``results_staged: 0``, and built 41 articles — and ``check_collection_log.py`` passed. The
log is the only artifact that answers "what would you have found if you had searched
differently?", so a log that explains none of the corpus is hollow while still looking
complete. These tests pin the reconciliation that now refuses it, and — as importantly —
the cases it must *not* refuse: over-counted claims, rounds that predate the rule, and
extensions whose baseline was collected under the old one.
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

REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "skills" / "collect" / "scripts" / "check_collection_log.py"
TOPIC = "test-topic-2026"

#: Either side of ``RECONCILE_REQUIRED_FROM`` (2026-08-29), for logs and for run ids.
BEFORE, AFTER = "2026-08-27", "2026-08-30"


def _load_check():
    """Import the script once; the behaviour tests call ``main(argv)`` in-process (a
    subprocess per case dominated this file's runtime).  The real CLI path keeps one
    subprocess smoke test at the bottom of the file."""
    sys.path.insert(0, str(CHECK.parent))  # the script does `import _bootstrap`
    try:
        spec = importlib.util.spec_from_file_location("newsab_check_collection_log", CHECK)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(CHECK.parent))
    return module


_check = _load_check()


def _run(*args: object) -> SimpleNamespace:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = _check.main([str(arg) for arg in args])
    return SimpleNamespace(returncode=code, stdout=out.getvalue(), stderr=err.getvalue())


def _query(group: str, at: str, staged: int | None, n: int = 1) -> list[dict]:
    rows = []
    for i in range(n):
        row = {
            "kind": "query",
            "at": f"{at}T12:00:{i % 60:02d}Z",
            "group_id": group,
            "query": f"query {i} for {group}",
            "engine_or_site": "web search",
            "results_seen": 10,
        }
        if staged is not None:
            row["results_staged"] = staged
        rows.append(row)
    return rows


def _topic(tmp_path: Path, log: list[dict], runs: dict[str, dict[str, int]] | None = None,
           staging: dict[str, int] | None = None) -> Path:
    """Minimal topic tree: a log, zero or more builds, optionally unbuilt staging files.

    ``runs`` maps ``yyyymmddHHMM`` -> ``{group: article count}``; ``staging`` maps
    ``group -> file count``.
    """
    root = tmp_path / "topics"
    corpus = root / TOPIC / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "collection_log.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in log), encoding="utf-8"
    )
    for stamp, counts in (runs or {}).items():
        run_dir = corpus / "versions" / f"s2s-{stamp}-abcdef01"
        run_dir.mkdir(parents=True)
        articles = [
            {"article_id": f"{group.upper()}_{index:08x}"}
            for group, count in sorted(counts.items())
            for index in range(count)
        ]
        (run_dir / "corpus_run.json").write_text(
            json.dumps({"run_id": run_dir.name, "articles": articles}), encoding="utf-8"
        )
    for group, count in (staging or {}).items():
        staging_dir = corpus / "staging"
        staging_dir.mkdir(exist_ok=True)
        for index in range(count):
            (staging_dir / f"{group}-{index:03d}-outlet.yaml").write_text(
                f"group_id: {group}\nurl: https://example.com/{group}/{index}\n", encoding="utf-8"
            )
    return root


def test_all_zero_staged_log_with_a_full_corpus_fails(tmp_path):
    # The sado round-1 shape, at its real scale: 76 queries claiming nothing, 41 articles.
    root = _topic(
        tmp_path,
        log=_query("jp", AFTER, 0, n=62) + _query("kr", AFTER, 0, n=14),
        runs={"202608301300": {"jp": 21, "kr": 20}},
    )
    result = _run(root, TOPIC)
    assert result.returncode == 1, result.stdout
    assert "group jp: 21 article(s) entered the corpus" in result.stderr
    assert "group kr: 20 article(s) entered the corpus" in result.stderr
    assert "--corrects" in result.stderr  # says how to fix it without editing history


def test_honest_round_passes_and_over_counting_is_allowed(tmp_path):
    # results_staged legitimately over-counts: one article found by three queries is staged
    # once and claimed three times.  Only the other direction is a finding.
    root = _topic(
        tmp_path,
        log=_query("jp", AFTER, 3, n=4) + _query("kr", AFTER, 2, n=4),
        runs={"202608301300": {"jp": 5, "kr": 8}},
    )
    result = _run(root, TOPIC)
    assert result.returncode == 0, result.stderr
    assert "reconciliation jp: +5 article(s) this round, 12 claimed" in result.stdout
    assert "UNEXPLAINED" not in result.stdout


def test_one_group_short_is_reported_alone(tmp_path):
    root = _topic(
        tmp_path,
        log=_query("jp", AFTER, 0, n=4) + _query("kr", AFTER, 4, n=4),
        runs={"202608301300": {"jp": 5, "kr": 8}},
    )
    result = _run(root, TOPIC)
    assert result.returncode == 1
    assert "group jp:" in result.stderr
    assert "group kr:" not in result.stderr
    assert "reconciliation kr: +8 article(s) this round, 16 claimed by results_staged — OK" in result.stdout


def test_a_round_that_predates_the_rule_is_reported_but_not_enforced(tmp_path):
    root = _topic(
        tmp_path,
        log=_query("jp", BEFORE, 0, n=8),
        runs={"202608271300": {"jp": 41}},
    )
    result = _run(root, TOPIC)
    assert result.returncode == 0, result.stderr
    assert "round predates the rule, reported not enforced" in result.stdout
    assert "reconciliation jp: +41 article(s) this round, 0 claimed" in result.stdout
    assert "UNEXPLAINED 41" in result.stdout


def test_reconcile_since_audits_a_round_that_predates_the_rule(tmp_path):
    root = _topic(
        tmp_path,
        log=_query("jp", BEFORE, 0, n=8),
        runs={"202608271300": {"jp": 41}},
    )
    result = _run(root, TOPIC, "--reconcile-since", "2026-08-01")
    assert result.returncode == 1
    assert "group jp: 41 article(s) entered the corpus" in result.stderr


def test_an_extension_is_judged_on_what_it_added_not_on_inherited_history(tmp_path):
    # Baseline collected under the old rule (and under-logged); the extension adds 4 and
    # claims 6.  The pre-cutoff 20 are never re-litigated — their log predates the rule and
    # records are immutable.
    root = _topic(
        tmp_path,
        log=_query("jp", BEFORE, 0, n=8) + _query("jp", AFTER, 3, n=2),
        runs={"202608271300": {"jp": 20}, "202608301300": {"jp": 24}},
    )
    result = _run(root, TOPIC)
    assert result.returncode == 0, result.stderr
    assert "reconciliation jp: +4 article(s) this round, 6 claimed" in result.stdout


def test_an_extension_that_under_claims_what_it_added_fails(tmp_path):
    root = _topic(
        tmp_path,
        log=_query("jp", BEFORE, 0, n=8) + _query("jp", AFTER, 1, n=2),
        runs={"202608271300": {"jp": 20}, "202608301300": {"jp": 24}},
    )
    result = _run(root, TOPIC)
    assert result.returncode == 1
    assert "group jp: 4 article(s) entered the corpus this round but the log's queries claim only 2" in result.stderr


def test_an_extension_that_logs_no_query_at_all_is_still_caught(tmp_path):
    # The escape hatch a round-start-scoped check would leave open: add articles, log
    # nothing.  The build itself is post-cutoff and an earlier build gives it a baseline.
    root = _topic(
        tmp_path,
        log=_query("jp", BEFORE, 5, n=4),
        runs={"202608271300": {"jp": 20}, "202608301300": {"jp": 24}},
    )
    result = _run(root, TOPIC)
    assert result.returncode == 1
    assert "group jp: 4 article(s) entered the corpus this round but the log's queries claim only 0" in result.stderr


def test_a_log_appended_after_its_build_still_reconciles(tmp_path):
    # aabb-steppe-stone-2025's real shape: every query line timestamped after the build it
    # explains.  Scoping the round by its own first query would compare that round against
    # a baseline that already contained everything, and check nothing at all.
    root = _topic(
        tmp_path,
        log=_query("jp", AFTER, 0, n=4),
        runs={"202608301200": {"jp": 12}},
    )
    result = _run(root, TOPIC)
    assert result.returncode == 1
    assert "group jp: 12 article(s) entered the corpus" in result.stderr


def test_staging_stands_in_for_a_corpus_that_was_never_built(tmp_path):
    root = _topic(tmp_path, log=_query("jp", AFTER, 0, n=4), staging={"jp": 6})
    result = _run(root, TOPIC)
    assert result.returncode == 1
    assert "corpus/staging vs 4 query line(s)" in result.stdout
    assert "group jp: 6 article(s) entered the corpus" in result.stderr


def test_unbuilt_staging_beside_a_build_warns_rather_than_reconciling_against_it(tmp_path):
    root = _topic(
        tmp_path,
        log=_query("jp", AFTER, 9, n=1),
        runs={"202608301300": {"jp": 5}},
        staging={"jp": 8},
    )
    result = _run(root, TOPIC)
    assert result.returncode == 0, result.stderr
    assert "WARN 8 file(s) in corpus/staging but 5 article(s) in the newest build" in result.stdout


def test_a_query_line_written_now_must_say_what_it_staged(tmp_path):
    """The omission and a real zero were indistinguishable, and the reconciliation
    had to read both as zero — so a round could be hollowed out one omitted field at a
    time while every line still validated. ``0`` is written, never left out."""
    root = _topic(
        tmp_path,
        log=_query("jp", AFTER, None, n=3) + _query("jp", AFTER, 4, n=1),
        runs={"202608301300": {"jp": 4}},
    )
    result = _run(root, TOPIC)
    assert result.returncode == 1
    assert "must record results_staged" in result.stderr


def test_history_that_omitted_results_staged_is_warned_not_rewritten(tmp_path):
    """Records are immutable (§3.2): a log written before the field was required keeps its
    silence and is reported with the numbers, not failed."""
    root = _topic(
        tmp_path,
        log=_query("jp", BEFORE, None, n=3) + _query("jp", BEFORE, 4, n=1),
        runs={"202608271300": {"jp": 4}},
    )
    result = _run(root, TOPIC)
    assert result.returncode == 0, result.stderr
    assert "WARN 3 query line(s) in this round record no results_staged" in result.stdout


def test_an_empty_topic_has_nothing_to_explain(tmp_path):
    root = _topic(tmp_path, log=_query("jp", AFTER, 0, n=2))
    result = _run(root, TOPIC)
    assert result.returncode == 0, result.stderr
    assert "nothing to explain" in result.stdout


def test_a_pre_rule_synthetic_topic_stays_compatible(tmp_path):
    root = _topic(
        tmp_path,
        log=_query("aa", BEFORE, None, n=3),
        runs={"202608271300": {"aa": 3}},
    )
    result = _run(root, TOPIC)
    assert result.returncode == 0, result.stderr


@pytest.mark.cli_e2e
def test_the_real_cli_still_boots_and_exits_zero(tmp_path):
    # Everything above calls ``main()`` in-process; this one subprocess keeps the
    # agent-facing entry point honest — shebang, ``_bootstrap``, the SystemExit code.
    root = _topic(
        tmp_path,
        log=_query("jp", AFTER, 3, n=4),
        runs={"202608301300": {"jp": 5}},
    )
    result = subprocess.run(
        [sys.executable, str(CHECK), str(root), TOPIC],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "reconciliation jp" in result.stdout
