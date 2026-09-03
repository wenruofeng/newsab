#!/usr/bin/env python3
"""Evaluate a localization judge pass against its blocking triggers, deterministically.

The judge supplies scores and prose; whether the locale ships is decided here, by the
arithmetic in ``references/localization-judge.md`` (D10) — a judge that could also rule
on its own scores would have every incentive to pass the text it just read.  On this
path the verdict is a refusal, not an escalation: the languages this gate protects are
exactly the ones no human on the project reads (``skills/publish/references/
localization.md``), so a fired trigger sends the localization back to be fixed and
re-judged, never to a reviewer.

    python check_localization_judge.py --judge locjudge.<locale>.json \
        --judge-model <id> [--localizer-model <id>]

Exit codes: 0 the locale may ship · 1 blocked (fix and re-judge on a fresh packet)
· 2 inputs missing or malformed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AXES = (
    "meaning_fidelity",
    "quantity_and_provenance",
    "register_and_symmetry",
    "reader_fluency",
)


def _refs(entries: object) -> str:
    """Render the judge's reference list, whatever shape it chose (see check_judge.py)."""
    if not isinstance(entries, list):
        entries = [entries]
    out = []
    for entry in entries:
        if isinstance(entry, dict):
            for key in ("ref", "label", "where", "entry", "id"):
                if key in entry:
                    out.append(str(entry[key]))
                    break
            else:
                out.append("; ".join(f"{k}={v}" for k, v in entry.items()))
        else:
            out.append(str(entry))
    return ", ".join(out)


def blocks(judge: dict) -> list[str]:
    """The rubric's triggers, evaluated rather than asked about."""
    out: list[str] = []
    scores = {axis: int(judge["scores"][axis]["score"]) for axis in AXES}
    zeros = sorted(a for a, s in scores.items() if s == 0)
    ones = sorted(a for a, s in scores.items() if s == 1)
    if zeros:
        out.append(f"judge_zero: score 0 on {', '.join(zeros)}")
    if len(ones) >= 2:
        out.append(f"judge_two_ones: score 1 on {', '.join(ones)}")
    changes = judge.get("meaning_changes") or []
    if changes:
        out.append(f"meaning_change: {_refs(changes)}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--judge", required=True, help="localization judge output JSON")
    ap.add_argument("--judge-model", required=True)
    ap.add_argument("--localizer-model", help="recorded for provenance; not a gate")
    args = ap.parse_args(argv)

    path = Path(args.judge)
    if not path.exists():
        print(f"missing judge file {path}", file=sys.stderr)
        return 2
    try:
        judge = json.loads(path.read_text(encoding="utf-8"))
        missing = [a for a in AXES if a not in judge.get("scores", {})]
        if missing:
            print(f"judge output is missing axes: {', '.join(missing)}", file=sys.stderr)
            return 2
        locale = judge.get("locale")
        if not locale:
            print("judge output names no locale", file=sys.stderr)
            return 2
        triggered = blocks(judge)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"malformed judge output: {exc}", file=sys.stderr)
        return 2

    print(f"locale {locale}  ·  judge model {args.judge_model}", end="")
    print(f"  ·  localizer model {args.localizer_model}" if args.localizer_model else "")
    if args.localizer_model and args.judge_model == args.localizer_model:
        print("note: judge ran on the localizer's model — independence here is the packet, not the model")
    print()
    for axis in AXES:
        entry = judge["scores"][axis]
        print(f"{axis:24s} {entry['score']}  {entry.get('note', '')}")
    conversions = judge.get("checked_conversions") or []
    if conversions:
        print(f"\nconversions checked: {len(conversions)}")
    concerns = judge.get("pivot_concerns") or []
    if concerns:
        print(f"pivot concerns (advisory, for the run report): {_refs(concerns)}")
    if not triggered:
        print(f"\nno blocking trigger fired — {locale} may ship")
        return 0
    print(f"\nBLOCKED — {locale} does not ship; fix the localization and re-judge:")
    for line in triggered:
        print(f"  - {line}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
