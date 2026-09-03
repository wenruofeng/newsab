"""The calibration tool: the qa-0.5.0 candidate-package table, from the real machine.

Runs :func:`newsab_a1.qa_analyze.analyse_qa` — the production code path, production seed,
production draw count — over every topic's *active* corpus/questions/answers/category-map
runs, once per candidate threshold package, and prints the comparison table the user
signs.  Nothing is written into any topic; the sweep is read-only.

The packages (all qa-0.5.0 candidates use the readable-cluster universe):

* ``LEGACY`` — what is on the site today: qa-0.4.0 thresholds over **all** clusters.
  The baseline every impact statement diffs against.
* ``P0`` — qa-0.4.0 thresholds, readable universe: proves the denominator fix alone
  does not revive the silence tab.
* ``P1``–``P4`` — Jeffreys rate prior × ``silent_max_rate`` ∈ {0.15, 0.20} ×
  ``attention_gap_min_abs_diff`` ∈ {0.25, 0.20} (the retrospective §6.3 grid).
* ``L1``–``L4`` — an experiment: ``loud_min_rate`` ∈ {0.30, 0.40} ×
  ``silent_max_rate`` ∈ {0.15, 0.20}; the absolute loud-side floor replaces the
  relative-difference clause entirely.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Optional, Sequence

from newsab_schema.enums import FindingKind, FindingStrength
from newsab_schema.io import ArtifactError, read_jsonl, read_yaml
from newsab_schema.models.category_map import CategoryMap
from newsab_schema.models.qa import ClusterAnswer, QuestionSet
from newsab_schema.paths import TopicPaths
from newsab_schema.store import load_corpus_run, load_run_articles

from .qa_analyze import QAAnalysisRun, QAThresholds, analyse_qa

_BASE = QAThresholds()  # qa-0.5.0 defaults: production seed and draw count

#: name -> (thresholds, readable_universe).  Order is presentation order.
PACKAGES: dict[str, tuple[QAThresholds, bool]] = {
    "LEGACY": (
        replace(
            _BASE,
            thresholds_version="qa-0.4.0",
            calibrated=True,
            silent_max_rate=0.10,
            rate_pseudo_total=2.0,
        ),
        False,
    ),
    "P0": (
        replace(_BASE, silent_max_rate=0.10, rate_pseudo_total=2.0, calibrated=False),
        True,
    ),
    "P1": (replace(_BASE, silent_max_rate=0.15, attention_gap_min_abs_diff=0.25), True),
    "P2": (replace(_BASE, silent_max_rate=0.15, attention_gap_min_abs_diff=0.20), True),
    "P3": (replace(_BASE, silent_max_rate=0.20, attention_gap_min_abs_diff=0.25), True),
    "P4": (replace(_BASE, silent_max_rate=0.20, attention_gap_min_abs_diff=0.20), True),
    "L1": (replace(_BASE, silent_max_rate=0.15, loud_min_rate=0.30), True),
    "L2": (replace(_BASE, silent_max_rate=0.15, loud_min_rate=0.40), True),
    "L3": (replace(_BASE, silent_max_rate=0.20, loud_min_rate=0.30), True),
    "L4": (replace(_BASE, silent_max_rate=0.20, loud_min_rate=0.40), True),
}


def _package_label(name: str, t: QAThresholds) -> str:
    prior = "uniform" if t.rate_pseudo_total == 2.0 else "Jeffreys"
    if t.loud_min_rate is not None:
        clause = f"lmin={t.loud_min_rate:.2f}"
    else:
        clause = f"mdiff={t.attention_gap_min_abs_diff:.2f}"
    return f"{prior}, smax={t.silent_max_rate:.2f}, {clause}"


def sweep_topic(topics_root: Path, topic_id: str) -> dict[str, QAAnalysisRun]:
    """Every package's full production run for one topic, keyed by package name."""
    paths = TopicPaths.for_topic(topics_root, topic_id)
    corpus_run = load_corpus_run(paths)
    access_levels = {
        a.article_id: a.access_level.value
        for a in load_run_articles(paths, corpus_run.run_id)
    }
    question_set = read_yaml(paths.questions, QuestionSet)
    answers = read_jsonl(paths.answers, ClusterAnswer)
    category_map = None
    if paths.active_run_id("normalization") and paths.category_map.exists():
        category_map = CategoryMap.model_validate_json(
            paths.category_map.read_text(encoding="utf-8")
        )
    out: dict[str, QAAnalysisRun] = {}
    for name, (thresholds, readable) in PACKAGES.items():
        out[name] = analyse_qa(
            question_set,
            answers,
            corpus_run,
            topic_id=topic_id,
            thresholds=thresholds,
            category_map=category_map,
            access_levels=access_levels if readable else None,
        )
    return out


def _gap_rows(runs_by_topic: dict[str, dict[str, QAAnalysisRun]]) -> list[dict]:
    """One row per (topic, question) that fires in at least one package."""
    rows: list[dict] = []
    for topic_id, runs in runs_by_topic.items():
        fired = sorted(
            {
                qid
                for run in runs.values()
                for qid, s in run.question_stats.items()
                if s["attention_gap"]
            }
        )
        for qid in fired:
            per_package: dict[str, Optional[float]] = {}
            for name, run in runs.items():
                s = run.question_stats[qid]
                per_package[name] = s["attention_gap_stability"] if s["attention_gap"] else None
            # Observed rates come from the readable universe (any qa-0.5.0 package).
            stats = runs["P3"].question_stats[qid]
            sides = {
                g: f"{v['clusters_addressed']}/{v['clusters_total']}"
                for g, v in stats["groups"].items()
            }
            quiet = stats["attention_gap_quiet_group"]
            rows.append(
                {
                    "topic": topic_id,
                    "question": qid,
                    "text": stats["question"],
                    "quiet_group": quiet,
                    "rates": sides,
                    "fires": per_package,
                }
            )
    return rows


def _pool(run: QAAnalysisRun) -> dict[str, tuple[str, str]]:
    return {
        f.question_id: (f.kind.value, f.strength.value)
        for f in run.findings
        if f.strength != FindingStrength.UNSUPPORTED
    }


def _pool_delta(legacy: QAAnalysisRun, candidate: QAAnalysisRun) -> list[str]:
    """Human-readable pool changes candidate-vs-legacy for one topic."""
    old, new = _pool(legacy), _pool(candidate)
    notes: list[str] = []
    for qid in sorted(set(old) | set(new)):
        if qid in old and qid not in new:
            notes.append(f"{qid}: {old[qid][0]}/{old[qid][1]} → out of pool")
        elif qid not in old:
            notes.append(f"{qid}: entered pool as {new[qid][0]}/{new[qid][1]}")
        elif old[qid] != new[qid]:
            notes.append(
                f"{qid}: {old[qid][0]}/{old[qid][1]} → {new[qid][0]}/{new[qid][1]}"
            )
    return notes


def render_markdown(runs_by_topic: dict[str, dict[str, QAAnalysisRun]]) -> str:
    names = list(PACKAGES)
    lines: list[str] = []
    lines.append("## Package definitions")
    lines.append("")
    lines.append("| package | universe | rate prior | smax | separation clause |")
    lines.append("|---|---|---|---|---|")
    for name, (t, readable) in PACKAGES.items():
        prior = "uniform (+1,+1)" if t.rate_pseudo_total == 2.0 else "Jeffreys (+½,+½)"
        clause = (
            f"loud ≥ {t.loud_min_rate:.2f} (absolute)"
            if t.loud_min_rate is not None
            else f"loud − quiet ≥ {t.attention_gap_min_abs_diff:.2f} (relative)"
        )
        lines.append(
            f"| {name} | {'readable' if readable else 'all'} clusters | {prior} "
            f"| {t.silent_max_rate:.2f} | {clause} |"
        )
    lines.append("")

    lines.append("## Universe (all → readable clusters per side)")
    lines.append("")
    lines.append("| topic | sides |")
    lines.append("|---|---|")
    for topic_id, runs in runs_by_topic.items():
        legacy, p0 = runs["LEGACY"], runs["P0"]
        parts = []
        for g in legacy.groups:
            # clusters_total is constant across questions; read it off any question.
            all_total = next(iter(legacy.question_stats.values()))["groups"][g]["clusters_total"]
            read_total = next(iter(p0.question_stats.values()))["groups"][g]["clusters_total"]
            parts.append(f"{g} {all_total}→{read_total}")
        lines.append(f"| {topic_id} | {', '.join(parts)} |")
    lines.append("")

    lines.append("## Attention-gap triggers (posterior p where fired; · = does not fire)")
    lines.append("")
    header = "| topic | question | quiet | rates (readable) | " + " | ".join(names) + " |"
    lines.append(header)
    lines.append("|---" * (4 + len(names)) + "|")
    rows = _gap_rows(runs_by_topic)
    for r in rows:
        cells = []
        for name in names:
            p = r["fires"][name]
            cells.append(f"**{p:.2f}**" if p is not None else "·")
        rates = ", ".join(f"{g}: {v}" for g, v in sorted(r["rates"].items()))
        lines.append(
            f"| {r['topic']} | {r['question']} | {r['quiet_group']} | {rates} | "
            + " | ".join(cells)
            + " |"
        )
    if not rows:
        lines.append("| (no package fires anywhere) |")
    lines.append("")

    lines.append("## Trigger counts")
    lines.append("")
    lines.append("| package | fired | supported | weak |")
    lines.append("|---|---|---|---|")
    for name in names:
        fired = supported = weak = 0
        for runs in runs_by_topic.values():
            for f in runs[name].findings:
                if f.kind == FindingKind.ATTENTION_GAP and f.strength != FindingStrength.UNSUPPORTED:
                    fired += 1
                    if f.strength == FindingStrength.SUPPORTED:
                        supported += 1
                    else:
                        weak += 1
        lines.append(f"| {name} | {fired} | {supported} | {weak} |")
    lines.append("")

    lines.append("## Candidate-pool changes vs LEGACY (per package with distinct pools)")
    lines.append("")
    for topic_id, runs in runs_by_topic.items():
        seen: dict[tuple[str, ...], list[str]] = {}
        for name in names[1:]:
            delta = tuple(_pool_delta(runs["LEGACY"], runs[name]))
            seen.setdefault(delta, []).append(name)
        for delta, pkgs in seen.items():
            if not delta:
                continue
            lines.append(f"- **{topic_id}** ({', '.join(pkgs)}):")
            for note in delta:
                lines.append(f"  - {note}")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="newsab-a1 qa-calibrate", description=__doc__
    )
    parser.add_argument("topics_root")
    parser.add_argument(
        "--topics",
        nargs="*",
        help="topic ids; default = every directory with active corpus+answers runs",
    )
    parser.add_argument("--json", dest="json_out", help="also dump the raw sweep as JSON")
    args = parser.parse_args(argv)

    root = Path(args.topics_root)
    topics = args.topics or sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and (p / "answers").exists() and (p / "corpus").exists()
    )
    runs_by_topic: dict[str, dict[str, QAAnalysisRun]] = {}
    for topic_id in topics:
        try:
            runs_by_topic[topic_id] = sweep_topic(root, topic_id)
        except (ArtifactError, FileNotFoundError, ValueError) as exc:
            print(f"skipping {topic_id}: {exc}", file=sys.stderr)

    print(render_markdown(runs_by_topic))

    if args.json_out:
        payload = {
            "packages": {
                name: {**t.to_dict(), "readable_universe": readable}
                for name, (t, readable) in PACKAGES.items()
            },
            "gap_rows": _gap_rows(runs_by_topic),
            "question_stats": {
                topic: {name: run.question_stats for name, run in runs.items()}
                for topic, runs in runs_by_topic.items()
            },
        }
        Path(args.json_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"json written to {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
