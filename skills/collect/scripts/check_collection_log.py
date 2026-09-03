#!/usr/bin/env python3
"""Validate a topic's collection log and report search coverage.

The collection log is the only artifact that answers "what would you have found if you had
searched differently?" (§3.3 S2), so it is checked mechanically rather than trusted:

* every line must validate against ``CollectionLogEntry`` — the model forbids extra fields,
  so a plausible-looking invented key is a silent data loss otherwise;
* every ``term_variant`` cell expected for a group must actually have been searched, because
  an unsearched cell is an invisible under-sample that later reads as a blind spot (§2.3);
* ``source_added`` entries must name what surfaced the outlet (D19), so a reviewer can tell
  a source entered the frame because it belongs there and not merely because it happened to
  cover this topic;
* the corpus must be *explainable by the log*: every article a round put in the corpus has
  to be claimed by some query's ``results_staged`` (see :func:`reconcile_staging`).

    python scripts/check_collection_log.py topics aabb-river-light-2026
    python scripts/check_collection_log.py topics aabb-river-light-2026 --expect cn=policy_name,framing_tighten
    python scripts/check_collection_log.py topics aabb-island-dance-2024 --reconcile-since 2026-08-01

Exit code 1 on any invalid line, any missing cell, or an unexplained corpus.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

import _bootstrap  # noqa: F401

from newsab_corpus.collection_log import (
    STAGED_REQUIRED_FROM,
    CollectionLogEntry,
    variant_coverage,
)
from newsab_schema.models.corpus import BACKFILL_RETRY_BUDGET, BackfillDebt
from newsab_schema.paths import TopicPaths

#: The reconciliation below became a gate from this date — the first full day after the
#: rule landed (2026-08-28), following the same convention as
#: ``newsab_corpus.collection_log.LAYER_REQUIRED_FROM``.  Records are immutable (§3.2):
#: a round that ran before the rule is not retroactively invalid and its log is not
#: rewritten to satisfy a later rule, so pre-cutoff rounds are reported as a warning with
#: the same numbers.  ``--reconcile-since`` moves the line, which is how history is
#: audited on purpose rather than by accident.
RECONCILE_REQUIRED_FROM = datetime(2026, 8, 29, tzinfo=timezone.utc)


def _parse_expect(values: list[str]) -> dict[str, list[str]]:
    expected: dict[str, list[str]] = {}
    for item in values:
        group, _, variants = item.partition("=")
        if not variants:
            raise SystemExit(f"--expect needs group=v1,v2 form, got {item!r}")
        expected[group] = [v for v in variants.split(",") if v]
    return expected


def _run_started_at(run_id: str) -> datetime | None:
    """UTC start time encoded in a ``{stage}-{yyyymmddHHMM[ssffffff]}-{hex}`` run id."""
    parts = run_id.split("-")
    if len(parts) != 3 or not parts[1].isdigit():
        return None
    stamp = parts[1]
    fmt = {12: "%Y%m%d%H%M", 20: "%Y%m%d%H%M%S%f"}.get(len(stamp))
    if fmt is None:
        return None
    try:
        return datetime.strptime(stamp, fmt).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _corpus_runs(paths: TopicPaths) -> list[tuple[datetime, str, Counter]]:
    """Every build this topic ever minted: ``(started_at, run_id, articles per group)``.

    Read from ``corpus_run.json`` rather than ``index.jsonl`` because the run record is the
    set the build pinned (R-2) and is the artifact git keeps.  Members are what the run saw,
    so a withdrawal is already out of the count.  A member's group is the lower-cased
    ``article_id`` prefix — ``Group`` validates that this *is* the ``group_id``.
    """
    versions = paths.stage_versions_dir("corpus")
    runs: list[tuple[datetime, str, Counter]] = []
    if not versions.is_dir():
        return runs
    for run_dir in sorted(versions.iterdir()):
        record = run_dir / "corpus_run.json"
        if not record.is_file():
            continue
        started = _run_started_at(run_dir.name)
        if started is None:
            continue
        try:
            payload = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        counts: Counter = Counter()
        for member in payload.get("articles") or []:
            prefix = str(member.get("article_id", "")).split("_")[0].upper()
            counts[prefix.lower()] += 1
        runs.append((started, run_dir.name, counts))
    runs.sort(key=lambda item: (item[0], item[1]))
    return runs


def _staging_counts(paths: TopicPaths) -> Counter:
    """Articles waiting in ``corpus/staging/``, per group, as declared by each YAML."""
    counts: Counter = Counter()
    staging = paths.staging_dir
    if not staging.is_dir():
        return counts
    for path in sorted(staging.glob("*.yaml")):
        if path.name.endswith(".template"):
            continue
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(payload, dict) and payload.get("group_id"):
            counts[str(payload["group_id"])] += 1
    return counts


def reconcile_staging(
    entries: list[CollectionLogEntry],
    paths: TopicPaths,
    cutoff: datetime,
) -> tuple[list[str], list[str]]:
    """Can the log account for the articles in the corpus?  Returns ``(lines, failures)``.

    The invariant, per group: **the articles this round added to the corpus must not
    outnumber what this round's queries say they staged.**  ``results_staged`` may legally
    over-count (one article surfacing in three queries is staged once but claimed three
    times), so the check is one-sided; what it forbids is the other direction, where
    articles appear that no logged query claims to have found.  That direction is the whole
    failure this exists for: ``aabb-island-dance-2024``'s first round logged 76 queries all reading
    ``results_staged: 0`` and built 41 articles, and every check of the day passed — the
    log had been hollowed out while still looking complete, and it is the only evidence
    anyone has about what a different search would have found.

    What is compared is the round, not the lifetime totals, so an old topic stays extendable:
    the articles a pre-cutoff round collected are the baseline — the newest build minted
    before the cutoff — and are never re-litigated, because their log predates the rule and
    records are immutable.  Both sides of the comparison are split at the *same* fixed
    cutoff rather than at the round's own first query: a log appended after its build (which
    the skill forbids and ``aabb-steppe-stone-2025`` did anyway) would otherwise land entirely
    after the build it explains and reconcile against an empty round.  A correction to an
    under-reported count is a new ``query`` line carrying ``corrects`` — never an edit.
    """
    runs = _corpus_runs(paths)
    staged = _staging_counts(paths)
    queries = [e for e in entries if e.kind == "query"]

    if runs:
        current, current_from = runs[-1][2], f"corpus run {runs[-1][1]}"
    elif staged:
        current, current_from = staged, "corpus/staging"
    else:
        return ["  reconciliation: no corpus run and nothing staged — nothing to explain"], []

    # Enforce on a round that ran under the rule.  A build minted after the cutoff counts
    # too — otherwise a round that logs no query at all would be the one thing that escapes
    # — but only when an earlier build gives it a baseline; without one there is no way to
    # tell a post-cutoff build of a pre-cutoff collection from a hollow log, and guessing
    # would fail rounds that were already in flight when the rule landed.  A wholly
    # pre-cutoff topic is still measured, over its whole life, and printed: the numbers are
    # what the operator audits history with, they just do not fail a run that predates them.
    post_cutoff = [e for e in queries if e.at >= cutoff]
    has_earlier_run = any(started < cutoff for started, _, _ in runs)
    enforced = bool(post_cutoff) or bool(runs and runs[-1][0] >= cutoff and has_earlier_run)
    # Not enforced: measure the topic's whole life instead, from before its first artifact,
    # so the operator still sees the gap.  Same arithmetic, printed rather than fatal.
    boundary = cutoff if enforced else min([e.at for e in queries] + [r[0] for r in runs] + [cutoff])
    baseline = next((counts for started, _, counts in reversed(runs) if started < boundary), Counter())
    in_round = [e for e in queries if e.at >= boundary]
    claimed: Counter = Counter()
    for entry in in_round:
        claimed[entry.group_id] += entry.results_staged or 0
    unrecorded = sum(1 for e in in_round if e.results_staged is None)

    lines = [
        f"  reconciliation: {current_from} vs {len(in_round)} query line(s) since "
        f"{boundary:%Y-%m-%dT%H:%M:%SZ}"
        + ("" if enforced else " — round predates the rule, reported not enforced")
    ]
    if runs and staged and sum(staged.values()) > sum(runs[-1][2].values()):
        lines.append(
            f"  WARN {sum(staged.values())} file(s) in corpus/staging but "
            f"{sum(runs[-1][2].values())} article(s) in the newest build — rebuild, then "
            f"re-run this check"
        )
    if unrecorded:
        lines.append(
            f"  WARN {unrecorded} query line(s) in this round record no results_staged; "
            f"counted as 0 — an unclaimed article is indistinguishable from an unlogged one. "
            f"Only a pre-{STAGED_REQUIRED_FROM:%Y-%m-%d} line can be missing it "
            f"(CollectionLogEntry now refuses one), and history is not rewritten"
        )

    failures: list[str] = []
    for group in sorted(set(current) | set(claimed) | set(baseline)):
        added = current.get(group, 0) - baseline.get(group, 0)
        if added <= 0:
            continue
        state = "OK" if added <= claimed[group] else f"UNEXPLAINED {added - claimed[group]}"
        lines.append(
            f"  reconciliation {group}: +{added} article(s) this round, "
            f"{claimed[group]} claimed by results_staged — {state}"
        )
        if added > claimed[group] and enforced:
            failures.append(
                f"group {group}: {added} article(s) entered the corpus this round but the "
                f"log's queries claim only {claimed[group]} staged. The log is the only "
                f"evidence of what a different search would have found, so an article no "
                f"query claims makes it unreadable. Log each query's real "
                f"--results-staged as it runs; to fix an under-reported count already "
                f"written, append a new query line carrying --corrects (never edit one)."
            )
    return lines, failures


def debt_lines(paths: TopicPaths) -> list[str]:
    """The newest build's ``backfill_debt``, so the Done gate's state is visible.

    Informational, never fatal here: a round may honestly end with a fresh debt it cannot
    retry in this session (an engine's verification wall). The refusal lives in annotate's
    preflight, which exits 1 while any debt still has retry budget; these lines are how the
    collect agent sees that coming.
    """
    newest: tuple[datetime, str] | None = None
    versions = paths.stage_versions_dir("corpus")
    if versions.is_dir():
        for run_dir in versions.iterdir():
            started = _run_started_at(run_dir.name)
            if started is None or not (run_dir / "corpus_run.json").is_file():
                continue
            if newest is None or (started, run_dir.name) > newest:
                newest = (started, run_dir.name)
    if newest is None:
        return []
    record = versions / newest[1] / "corpus_run.json"
    try:
        payload = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [f"  WARN unreadable corpus run record {record}"]
    debts = [BackfillDebt.model_validate(d) for d in payload.get("backfill_debt") or []]
    if not debts:
        return [f"  backfill debt: none on newest build {newest[1]}"]
    lines = [f"  backfill debt: {len(debts)} cell(s) owed on newest build {newest[1]}"]
    for debt in debts:
        state = (
            "retry_futile — budget spent" if debt.retry_futile
            else f"retries {debt.retries}/{BACKFILL_RETRY_BUDGET}"
            + (" — budget spent" if debt.budget_exhausted else "")
        )
        lines.append(f"    {debt.key}: {state}")
    if any(not d.budget_exhausted for d in debts):
        lines.append(
            "  WARN fresh debt above: collect is not Done until each is retried "
            f"(targeted, site: routing per search-strategy §1b, max {BACKFILL_RETRY_BUDGET} "
            "rounds), closed, or marked futile — annotate's preflight refuses the corpus "
            "until then"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("topic_id")
    ap.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="GROUP=V1,V2",
        help="term variants that group's media use; repeat per group",
    )
    ap.add_argument(
        "--reconcile-since",
        metavar="YYYY-MM-DD",
        help="enforce the staging reconciliation on rounds from this date "
             f"(default {RECONCILE_REQUIRED_FROM:%Y-%m-%d}); earlier dates audit history",
    )
    args = ap.parse_args(argv)

    cutoff = RECONCILE_REQUIRED_FROM
    if args.reconcile_since:
        try:
            cutoff = datetime.strptime(args.reconcile_since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise SystemExit(f"--reconcile-since needs YYYY-MM-DD, got {args.reconcile_since!r}")

    path = Path(args.root) / args.topic_id / "corpus" / "collection_log.jsonl"
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        print(f"missing {path}", file=sys.stderr)
        return 1

    entries: list[CollectionLogEntry] = []
    invalid = 0
    for lineno, line in enumerate(raw, start=1):
        if not line.strip():
            continue
        try:
            entries.append(CollectionLogEntry.model_validate(json.loads(line)))
        except Exception as exc:  # noqa: BLE001 - report, do not stop at the first
            invalid += 1
            first = str(exc).splitlines()
            detail = first[1].strip() if len(first) > 1 else first[0]
            print(f"line {lineno}: {detail}", file=sys.stderr)

    kinds = Counter(e.kind for e in entries)
    print(f"{path}: {len(entries)} valid, {invalid} invalid")
    print("  kinds: " + ", ".join(f"{k}={n}" for k, n in sorted(kinds.items())))

    for entry in entries:
        if entry.kind == "source_added":
            print(f"  source_added: {entry.source_id} via {entry.found_via!r}")

    missing_total = 0
    if args.expect:
        coverage = variant_coverage(entries, _parse_expect(args.expect))
        for group, result in sorted(coverage.items()):
            missing = result["missing"]
            missing_total += len(missing)
            state = "OK" if not missing else "MISSING " + ", ".join(missing)
            print(f"  variants {group}: searched {len(result['searched'])} — {state}")
    else:
        print("  variants: not checked (pass --expect GROUP=v1,v2 to check coverage)")

    paths = TopicPaths.for_topic(args.root, args.topic_id)
    lines, failures = reconcile_staging(entries, paths, cutoff)
    for line in lines:
        print(line)
    for line in debt_lines(paths):
        print(line)
    for failure in failures:
        print(f"ERROR {failure}", file=sys.stderr)

    return 1 if (invalid or missing_total or failures) else 0


if __name__ == "__main__":
    raise SystemExit(main())
