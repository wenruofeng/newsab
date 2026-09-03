#!/usr/bin/env python3
"""Evaluate a spot-check judge **panel** against its escalation triggers, deterministically.

The judges supply scores and prose.  They do **not** decide whether the page reaches the
reviewer: the triggers in ``references/judge.md`` are arithmetic, so they are evaluated
here (D10).  A judge that could also rule on its own scores would have every incentive to
score the page it just read as fine.

The pass is a **panel**: the same packet goes to N independent judges in
parallel, and this script unions their findings — the merged score of an axis is the worst
score any judge gave it.  One judge pass has low recall (rounds two and three of a serial
run kept reporting true defects on untouched text), and serial rounds bought that recall
at 96 minutes of wall clock.  A panel buys it in one round.

What makes the check independent is the judges' *input*, not their vendor: they see the
judge packet and the rubric, never the writer's reasoning.  Judges on the writer's model
are allowed and recorded; the model ids are printed so the run report can state what ran.

    # discovery panel
    python check_judge.py --judge judge.1.1.json --judge judge.1.2.json \
        --judge judge.1.3.json --judge-model <id> --writer-model <id> \
        --page <page.json> --out judge.panel.1.json

    # confirmation panel, after one fix pass
    python check_judge.py --judge judge.2.1.json --judge judge.2.2.json \
        --judge judge.2.3.json --judge-model <id> --writer-model <id> \
        --page <fixed page.json> --previous judge.panel.1.json --out judge.panel.2.json

``--previous`` turns on the churn check: the panel record carries a hash per page locus,
so this run knows exactly which loci the fix pass rewrote.  **Churn is a new fault on
rewritten text, and nothing else** — a new fault on untouched text is discovery variance
and gets fixed like any other.

Exit codes: 0 clean · 1 escalates, run the fix pass · 2 inputs missing or malformed
· 3 stop and hand to a human (churn, or the panel budget is spent).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _judge_panel as panel

AXES = (
    "evidence_entailment",
    "symmetry",
    "silence_and_strength",
    "scope_discipline",
    "overall_impression",
)
LIST_FIELDS = ("unverified_readings", "contradicted_notes")

#: A discovery panel is what replaces serial rounds, so it needs enough judges to have
#: recall; a confirmation panel re-reads a page one panel already passed.
MIN_PANEL = {1: 3}
MIN_PANEL_LATER = 2
#: Discovery + fix + confirmation is the flow.  A third panel exists only for the case
#: where confirmation found pre-existing defects on untouched text; after it, a human.
MAX_ROUNDS = 3


def escalations(merged: dict) -> list[str]:
    """The rubric's triggers, evaluated on the merged panel rather than asked about."""
    out: list[str] = []
    scores = {axis: merged["scores"][axis]["score"] for axis in AXES}
    zeros = sorted(a for a, s in scores.items() if s == 0)
    ones = sorted(a for a, s in scores.items() if s == 1)
    if zeros:
        out.append(f"judge_zero: score 0 on {', '.join(zeros)}")
    if len(ones) >= 2:
        out.append(f"judge_two_ones: score 1 on {', '.join(ones)}")
    # One member's lone 1 can be score variance (a re-score of byte-identical text has
    # come back different); two members independently scoring the *same* axis 1 cannot,
    # and a 2-of-3 entailment fault has shipped through exactly this gap.  Agreement
    # raises severity here; it still never drops a finding.
    consensus = sorted(
        axis
        for axis, entry in merged["scores"].items()
        if axis in AXES
        and sum(1 for member in entry["judges"] if member["score"] == 1) >= 2
    )
    if consensus and not len(ones) >= 2:
        out.append(
            "judge_consensus_one: two or more members scored 1 on "
            + ", ".join(consensus)
        )
    if merged.get("unverified_readings"):
        out.append(
            "unverified_reading: " + ", ".join(merged["unverified_readings"])
        )
    if merged.get("contradicted_notes"):
        out.append("contradicted_note: " + ", ".join(merged["contradicted_notes"]))
    return out


def _models(args, count: int) -> list[str] | None:
    given = args.judge_model
    if len(given) == 1:
        return given * count
    if len(given) == count:
        return list(given)
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--judge",
        required=True,
        action="append",
        default=[],
        help="one judge's output JSON; repeat once per panel member",
    )
    ap.add_argument(
        "--judge-model",
        required=True,
        action="append",
        default=[],
        help="model id, once for the whole panel or once per --judge, in order",
    )
    ap.add_argument("--writer-model", help="recorded for provenance; not a gate")
    ap.add_argument("--page", help="the page.json this panel judged (hashes its loci)")
    ap.add_argument("--previous", help="the previous round's panel record; enables the churn check")
    ap.add_argument("--round", type=int, help="default: 1, or the previous round + 1")
    ap.add_argument("--out", help="write the merged panel record here")
    ap.add_argument(
        "--panel-min",
        type=int,
        help="override the minimum panel size (record why in the run report)",
    )
    args = ap.parse_args(argv)

    previous: dict = {}
    if args.previous:
        prev_path = Path(args.previous)
        if not prev_path.exists():
            print(f"missing previous panel record {prev_path}", file=sys.stderr)
            return 2
        try:
            previous = json.loads(prev_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"previous panel record is not JSON: {exc}", file=sys.stderr)
            return 2
        if not args.page:
            print(
                "--previous needs --page: churn is defined against the loci the fix "
                "pass rewrote, which is a diff of the two pages the panels judged",
                file=sys.stderr,
            )
            return 2

    round_no = args.round or (int(previous.get("round", 0)) + 1 if previous else 1)
    minimum = args.panel_min or MIN_PANEL.get(round_no, MIN_PANEL_LATER)
    if len(args.judge) < minimum:
        print(
            f"round {round_no} needs at least {minimum} independent judges on the same "
            f"packet, got {len(args.judge)}. One judge per round is the serial flow "
            f"this panel replaced; pass --panel-min to deviate deliberately.",
            file=sys.stderr,
        )
        return 2

    models = _models(args, len(args.judge))
    if models is None:
        print(
            f"--judge-model given {len(args.judge_model)} times for "
            f"{len(args.judge)} judges: pass it once for the whole panel or once per "
            f"judge, in the same order",
            file=sys.stderr,
        )
        return 2

    docs: list[dict] = []
    raw: list[str] = []
    for path_str in args.judge:
        path = Path(path_str)
        if not path.exists():
            print(f"missing judge file {path}", file=sys.stderr)
            return 2
        raw.append(path.read_text(encoding="utf-8"))
        try:
            docs.append(panel.load_judge(path, AXES))
        except ValueError as exc:
            print(f"malformed judge output: {exc}", file=sys.stderr)
            return 2

    rubrics = {str(doc.get("rubric_version", "")) for doc in docs}
    if len(rubrics) > 1:
        print(
            "panel members judged against different rubric versions "
            f"({', '.join(sorted(rubrics))}); re-run the odd one out on the current "
            "references/judge.md",
            file=sys.stderr,
        )
        return 2

    page: dict = {}
    if args.page:
        page_path = Path(args.page)
        if not page_path.exists():
            print(f"missing page {page_path}", file=sys.stderr)
            return 2
        try:
            page = json.loads(page_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"page is not JSON: {exc}", file=sys.stderr)
            return 2

    try:
        merged = panel.merge_panel(
            docs,
            axes=AXES,
            list_fields=LIST_FIELDS,
            ids=panel.id_locus_map(page) if page else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        print(f"malformed judge output: {exc}", file=sys.stderr)
        return 2

    merged["round"] = round_no
    merged["judges"] = [
        {"file": p, "model": m, "rubric_version": d.get("rubric_version")}
        for p, m, d in zip(args.judge, models, docs)
    ]
    if page:
        merged["page"] = args.page
        merged["page_loci"] = panel.page_loci(page)
    triggered = escalations(merged)
    merged["escalations"] = triggered

    rewritten: list[str] = []
    if previous:
        rewritten = panel.rewritten_loci(
            previous.get("page_loci") or {}, merged.get("page_loci") or {}
        )
        merged["rewritten_loci"] = rewritten
        merged["findings"] = panel.classify_findings(
            merged["findings"], previous, rewritten
        )

    churn = [f for f in merged["findings"] if f.get("classification") == "churn"]

    # ---- report -------------------------------------------------------------------
    print(f"round {round_no}  ·  panel of {len(docs)}  ·  rubric {sorted(rubrics)[0] or '(unversioned)'}")
    for entry in merged["judges"]:
        print(f"  judge {entry['file']}  ·  model {entry['model']}")
    if args.writer_model:
        print(f"  writer model {args.writer_model}")
        if args.writer_model in models:
            print(
                "  note: a panel member ran on the writer's model — independence here "
                "is the packet, not the model"
            )
    if len(set(models)) == 1 and len(docs) > 1:
        print(
            "  note: the whole panel ran on one model — the union buys recall across "
            "independent reads, not across vendors"
        )
    duplicates = len(raw) - len(set(raw))
    if duplicates:
        print(
            f"  WARNING: {duplicates} judge file(s) are byte-identical to another — "
            "a copied pass is not an independent read"
        )
    print()

    for axis in AXES:
        entry = merged["scores"][axis]
        spread = "/".join(str(item["score"]) for item in entry["judges"])
        print(f"{axis:22s} {entry['score']}  (panel {spread})")
        for item in entry["judges"]:
            if item["score"] < 2 and item["note"]:
                print(f"    judge {item['judge']}: {item['note']}")

    unlocated = [f for f in merged["findings"] if not f["locus"]]
    if unlocated:
        print(
            f"\nWARNING: {len(unlocated)} finding(s) name no page locus "
            "(angle N / intro / title / lexicon) — they cannot be classified against "
            "the fix pass; triage them by hand"
        )

    if merged["findings"]:
        print("\nfindings (union across the panel):")
        for finding in merged["findings"]:
            label = finding.get("classification")
            where = finding["locus"] or "(no locus named)"
            print(
                f"  - {finding['kind']:28s} {where:12s} {finding['agreement']}"
                + (f"  [{label}]" if label else "")
            )
            for detail in finding["detail"]:
                print(f"      {detail}")

    if previous:
        print(
            "\nrewritten since the last panel: "
            + (", ".join(rewritten) if rewritten else "nothing")
        )

    # ---- verdict ------------------------------------------------------------------
    if churn:
        merged["verdict"], code = "stop", 3
        tail = [
            "\nSTOP — the fix pass introduced new defects on the text it rewrote "
            "(churn); a human rules before this page goes any further:"
        ] + [
            f"  - {f['kind']} on {f['locus']} ({f['agreement']})" for f in churn
        ]
    elif not triggered:
        merged["verdict"], code = "clean", 0
        tail = ["\nno escalation trigger fired — proceed to localization"]
    elif round_no >= MAX_ROUNDS:
        merged["verdict"], code = "stop", 3
        tail = [
            f"\nSTOP — round {round_no} of at most {MAX_ROUNDS} still escalates; a human "
            "rules with every round's findings in front of them:"
        ] + [f"  - {line}" for line in triggered]
    else:
        merged["verdict"], code = "fix", 1
        tail = [
            "\nESCALATES — run one fix pass on exactly these, then the next panel:"
        ] + [f"  - {line}" for line in triggered]

    if args.out:
        Path(args.out).write_text(
            json.dumps(merged, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\npanel record written to {args.out}")
    for line in tail:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
