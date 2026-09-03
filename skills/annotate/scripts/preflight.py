#!/usr/bin/env python3
"""Refuse to annotate a corpus whose collect round still owes retryable backfill debt.

A ``backfill_debt`` entry used to be invisible to every gate — the cell coverage
check counts ``group × term_variant`` cells, not outlets, so a debt rode the chain
unread and later re-read as "handled" (search-strategy §1's Indonesia case cost ~25
articles on one side's denominator). This gate is where the chain stops instead:

* the **active** corpus run carries a debt whose retry budget is not spent
  → exit 1: back to collect for a targeted retry (only the debt cells, ``site:``
  routing per search-strategy §1b, at most ``BACKFILL_RETRY_BUDGET`` rounds);
* every remaining debt's budget is spent (``retries`` at the cap, or ``retry_futile``)
  → exit 0, but the residual list is printed — quote it in the run report so it
  reaches touchpoint two;
* no debt → exit 0.

    python skills/annotate/scripts/preflight.py topics aabb-lake-story-2026
"""

from __future__ import annotations

import argparse
import json
import sys

import _bootstrap  # noqa: F401

from newsab_schema.models.corpus import BACKFILL_RETRY_BUDGET, BackfillDebt
from newsab_schema.paths import TopicPaths


def _state(debt: BackfillDebt) -> str:
    if debt.retry_futile:
        return "retry_futile — budget spent"
    tail = " — budget spent" if debt.budget_exhausted else ""
    return f"retries {debt.retries}/{BACKFILL_RETRY_BUDGET}{tail}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root")
    ap.add_argument("topic_id")
    args = ap.parse_args(argv)

    paths = TopicPaths.for_topic(args.root, args.topic_id)
    run_id = paths.active_run_id("corpus")
    if run_id is None:
        print(f"{args.topic_id}: no active corpus run — build the corpus first", file=sys.stderr)
        return 1
    record = paths.corpus_run_file(run_id)
    try:
        payload = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read {record}: {exc}", file=sys.stderr)
        return 1
    debts = [BackfillDebt.model_validate(d) for d in payload.get("backfill_debt") or []]

    if not debts:
        print(f"{args.topic_id}: active corpus run {run_id} owes no backfill debt")
        return 0

    print(f"{args.topic_id}: active corpus run {run_id} owes {len(debts)} backfill debt(s)")
    for debt in debts:
        print(f"  {debt.key}: {_state(debt)}")
        print(f"    reason: {debt.reason}")

    fresh = [d for d in debts if not d.budget_exhausted]
    if fresh:
        print(
            f"\nREFUSED: {len(fresh)} debt(s) still have retry budget. Back to collect for a "
            f"targeted retry — re-run only the debt cells (site: routing, "
            f"search-strategy §1b), log the query lines as usual, then rebuild with "
            f"--close-debt for cells that yielded, --retry-debt for cells that failed "
            f"again, --futile-debt for a miss no retry can change.",
            file=sys.stderr,
        )
        return 1

    print(
        "\nevery debt's budget is spent — annotate may proceed. Quote the residual list "
        "above in the run report; it rides to touchpoint two as a known limit of this corpus."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
