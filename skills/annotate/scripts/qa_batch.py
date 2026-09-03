#!/usr/bin/env python3
"""Author Q×A questions and answers as compact batches, then assemble run directories.

Full records repeat ``topic_id``, ``question_set_version``, ``group_id``, ``provenance``
and hand-minted IDs on every line — four chances per record to introduce a mismatch the
schema rejects at the very end of the pass.  So the annotating run writes *compact*
lines carrying only its judgements; this script checks them against the corpus while the
cluster is still in front of the annotator, and a deterministic step mints IDs and
provenance for the whole pass at once.  Serial order is batch order, so the same batches
always assemble to the same IDs.

Question batch (JSONL, one object per line, order = QST serial order):

    {"tier": "template", "template_key": "responsibility",
     "text": {"en": "Who or what is blamed?", "zh-CN": "谁被归咎？", "id": "..."},
     "rationale": "template standard, worded for this topic",
     "category_guidance": "name the blamed actor: us_government, universities, ..."}

When the manifest carries a human-required question seed, exactly one semantically
equivalent question row also declares ``"covers_required_seeds": ["SQ-001"]``.  The
checker verifies complete one-to-one coverage; the declaration is a design-time audit and
is deliberately not copied into ``QuestionSet``, so it cannot privilege an angle later.

Answer batch (JSONL, one object per line):

    {"cluster_id": "RC-CN-02cf559b", "question_id": "QST-aabb-river-light-001",
     "addressed": true, "summary": "新规被呈现为……", "category": "policy_change",
     "evidence": ["CN_02cf559b:P01:S01"],
     "notes": "范塔·欧 = Fanta Aw（另一译名 范塔·阿夫），归一为同一说话人"}

``addressed: false`` lines carry cluster_id, question_id, addressed only.
(``confidence`` is retired; old batches still carrying it stay valid.)
``topic_id``, ``group_id`` and ``question_set_version`` are filled from the corpus
and active question set. New summaries default to English pivot; ``dump-answers`` emits
``summary_lang`` and ``model_id`` only to preserve an older record during incremental
assembly — a carried answer keeps the model that actually wrote it, and only genuinely new
answers are attributed to the model of the run assembling them.

    python scripts/qa_batch.py check-questions topics <topic> qbatch.jsonl
    python scripts/qa_batch.py assemble-questions topics <topic> qbatch.jsonl \
        --run-id <qst_run_id> --model-id <model>
    python scripts/qa_batch.py dump-questions topics <topic>            # active set -> batch
    python scripts/qa_batch.py check    topics <topic> batch1.jsonl [batch2.jsonl ...] \
        [--scope-clusters RC-CN-...,RC-CN-...] [--scope-questions QST-...,QST-...]
    python scripts/qa_batch.py assemble topics <topic> batch1.jsonl ... \
        --run-id <ans_run_id> --model-id <model>
    python scripts/qa_batch.py dump-answers topics <topic>              # active run -> batch

``check`` also prints, per shard, each question's addressed rate: annotator convention
drift is invisible inside one batch and reads downstream as a real side difference.
``check`` also prints, per question, the category tally across both sides — read it
before assembling: ``us_govt`` next to ``us_government`` is a normalisation defect that
is cheap now and a wrong count later.

Exit codes: 0 clean · 1 problems found · 2 inputs missing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap  # noqa: F401

from newsab_schema.common import Provenance
from newsab_schema.io import ArtifactError, read_jsonl, read_yaml, write_jsonl, write_yaml
from newsab_schema.models.qa import ClusterAnswer, Question, QuestionSet
from newsab_schema.models.corpus import TopicManifest
from newsab_schema.paths import TopicPaths
from newsab_schema.store import load_corpus_run, load_run_articles
from newsab_schema.validate import validate_answers

def _skill_version() -> str:
    """Read the version from the sibling SKILL.md so provenance cannot drift from it."""
    text = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r'^\s*(?:newsab-)?version:\s*"?([0-9][\w.]*)"?\s*$', text, re.MULTILINE)
    if match is None:
        raise ArtifactError("skills/annotate/SKILL.md has no parseable 'version:' line")
    return f"annotate-{match.group(1)}"


SKILL_VERSION = _skill_version()

_YEAR_SUFFIX = re.compile(r"-\d{4}$")


def topic_slug(topic_id: str) -> str:
    return _YEAR_SUFFIX.sub("", topic_id)


def _load_batches(files: list[str]) -> list[tuple[str, int, dict]]:
    rows: list[tuple[str, int, dict]] = []
    for name in files:
        path = Path(name)
        if not path.exists():
            raise ArtifactError(f"missing batch file {path}")
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                rows.append((str(path), lineno, json.loads(raw)))
            except json.JSONDecodeError as exc:
                raise ArtifactError(f"{path}:{lineno}: not JSON: {exc}") from exc
    return rows


def _compact(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:400]


# --- questions --------------------------------------------------------------------------


#: The versioned question set is a documented input to the write stage, so any prose that
#: names a seed's origin or mandate hands the writer the preference value_chain.md orders
#: stripped before analyze ("the mandate is removed from the versioned question set",
#: non-negotiable 9).  The mechanical fields are dropped at build; this refuses the prose
#: leak (rationales have named a seed as required in exactly those words).
_MANDATE_LEAK = re.compile(
    r"founder|mandate[sd]?\b|covers_required|\bSQ-\d|required question|reference question",
    re.IGNORECASE,
)


def _build_questions(rows, topic_id: str, provenance: Provenance, run_id: str):
    slug = topic_slug(topic_id)
    questions: list[Question] = []
    problems: list[str] = []
    for serial, (source, lineno, row) in enumerate(rows, start=1):
        where = f"{source}:{lineno}"
        for field in ("rationale", "category_guidance"):
            leak = _MANDATE_LEAK.search(str(row.get(field) or ""))
            if leak:
                problems.append(
                    f"{where}: {field} leaks the seed mandate ({leak.group(0)!r}); "
                    "write it from reader value and corpus semantics — the writer must "
                    "not see which questions a human mandated"
                )
        payload = {
            "question_id": f"QST-{slug}-{serial:03d}",
            "topic_id": topic_id,
            "tier": row.get("tier"),
            "template_key": row.get("template_key"),
            "text": {"values": row.get("text", {})},
            "rationale": {"text": row.get("rationale", ""), "lang": "en"},
            "category_guidance": (
                {"text": row["category_guidance"], "lang": "en"}
                if row.get("category_guidance")
                else None
            ),
            "status": row.get("status", "active"),
            "provenance": provenance.model_dump(mode="json"),
        }
        try:
            questions.append(Question.model_validate(payload))
        except Exception as exc:
            problems.append(f"{where}: {_compact(exc)}")
    if not problems:
        try:
            return (
                QuestionSet(
                    topic_id=topic_id,
                    question_set_version=run_id,
                    questions=questions,
                    provenance=provenance,
                ),
                problems,
            )
        except Exception as exc:
            problems.append(_compact(exc))
    return None, problems


def cmd_questions(args, mode: str) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    rows = _load_batches(args.batches)
    run_id = args.run_id or "qst-000000000000-00000000"
    provenance = Provenance(
        skill_version=SKILL_VERSION,
        model_id=args.model_id,
        run_id=run_id,
        timestamp=datetime.now(timezone.utc),
    )
    question_set, problems = _build_questions(rows, args.topic_id, provenance, run_id)
    manifest = read_yaml(paths.topic_manifest, TopicManifest)
    required = {
        seed.seed_id: seed
        for seed in manifest.question_seeds
        if seed.mandate.value == "required"
    }
    coverage: dict[str, list[int]] = {seed_id: [] for seed_id in required}
    for serial, (source, lineno, row) in enumerate(rows, start=1):
        declared = row.get("covers_required_seeds", [])
        if not isinstance(declared, list) or any(not isinstance(item, str) for item in declared):
            problems.append(
                f"{source}:{lineno}: covers_required_seeds must be a list of seed ids"
            )
            continue
        for seed_id in declared:
            if seed_id not in required:
                problems.append(
                    f"{source}:{lineno}: {seed_id!r} is not a human-required question seed"
                )
                continue
            coverage[seed_id].append(serial)
    for seed_id, serials in coverage.items():
        if not serials:
            problems.append(
                f"required seed {seed_id} has no semantically equivalent question row; "
                "add covers_required_seeds to that row"
            )
        elif len(serials) > 1:
            problems.append(
                f"required seed {seed_id} is claimed by multiple question rows {serials}; "
                "choose the single semantically equivalent question"
            )
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    if problems:
        print(f"\n{len(problems)} problem(s) — nothing written.")
        return 1

    templates = [q for q in question_set.active if q.tier.value == "template"]
    readers = [q for q in question_set.active if q.tier.value == "reader"]
    print(f"questions: {len(question_set.questions)} "
          f"({len(templates)} template, {len(readers)} reader)")
    for q in question_set.questions:
        key = q.template_key.value if q.template_key else "reader"
        print(f"  {q.question_id}  [{key}]  {q.text.get('en')}")
    for seed_id, serials in coverage.items():
        if serials:
            print(f"  required {seed_id} -> {question_set.questions[serials[0] - 1].question_id}")

    if mode == "check":
        print("\nquestion batch is clean.")
        return 0
    run_dir = paths.stage_run_dir("questions", args.run_id)
    if not run_dir.exists():
        print(
            f"missing {run_dir} — run `python -m newsab_schema prepare-run "
            f"{args.topics_root} {args.topic_id} questions {args.run_id}` first",
            file=sys.stderr,
        )
        return 2
    write_yaml(run_dir / "questions.yaml", question_set)
    print(f"\nwrote {run_dir}/questions.yaml")
    return 0


def cmd_dump_questions(args) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    if not paths.questions.exists():
        print("no active question set", file=sys.stderr)
        return 2
    question_set = read_yaml(paths.questions, QuestionSet)
    for q in question_set.questions:
        row = {
            "tier": q.tier.value,
            "template_key": q.template_key.value if q.template_key else None,
            "text": dict(q.text.values),
            "rationale": q.rationale.text,
            "category_guidance": q.category_guidance.text if q.category_guidance else None,
            "status": q.status.value,
        }
        print(json.dumps({k: v for k, v in row.items() if v is not None}, ensure_ascii=False))
    return 0


# --- answers ----------------------------------------------------------------------------


def _build_answers(rows, topic_id, question_set, articles, cluster_assignment, provenance):
    slug = topic_slug(topic_id)
    by_question = {q.question_id: q for q in question_set.questions}
    answers: list[ClusterAnswer] = []
    problems: list[str] = []
    serial = 0
    clusters = set(cluster_assignment.values())

    for source, lineno, row in rows:
        where = f"{source}:{lineno}"
        cluster_id = row.get("cluster_id")
        question_id = row.get("question_id")
        if cluster_id not in clusters:
            problems.append(f"{where}: {cluster_id!r} is not a cluster of the active corpus run")
            continue
        if question_id not in by_question:
            problems.append(f"{where}: {question_id!r} is not in the active question set")
            continue
        group_id = cluster_id.split("-")[1].lower()
        addressed = row.get("addressed")
        summary = row.get("summary")
        serial += 1
        payload = {
            "answer_id": f"ANS-{slug}-{serial:06d}",
            "topic_id": topic_id,
            "question_id": question_id,
            "question_set_version": question_set.question_set_version,
            "reporting_cluster_id": cluster_id,
            "group_id": group_id,
            "addressed": addressed,
            "answer_summary": (
                {"text": summary, "lang": row.get("summary_lang", "en")}
                if summary
                else None
            ),
            "answer_category": row.get("category"),
            "evidence": row.get("evidence", []),
            "confidence": row.get("confidence"),
            "notes": ({"text": row["notes"], "lang": "en"} if row.get("notes") else None),
            # A row that names its own author keeps it; only genuinely new answers are
            # attributed to this run's model.  `run_id` and `timestamp` still move, because
            # this run really is the one that assembled the record.
            "provenance": {
                **provenance.model_dump(mode="json"),
                **({"model_id": row["model_id"]} if row.get("model_id") else {}),
            },
        }
        try:
            answers.append(ClusterAnswer.model_validate(payload))
        except Exception as exc:
            serial -= 1
            problems.append(f"{where}: {_compact(exc)}")
    return answers, problems


def _category_tally(answers, question_set) -> None:
    by_question: dict[str, dict[str, dict[str, int]]] = {}
    for a in answers:
        if a.answer_category:
            by_question.setdefault(a.question_id, {}).setdefault(
                a.answer_category, {}
            ).setdefault(a.group_id, 0)
        if a.answer_category:
            by_question[a.question_id][a.answer_category][a.group_id] = (
                by_question[a.question_id][a.answer_category].get(a.group_id, 0) + 1
            )
    print("\ncategory tallies (read for near-duplicates before assembling):")
    for question_id in sorted(by_question):
        q = question_set.by_id(question_id)
        label = q.text.get("en") if q else "?"
        print(f"  {question_id}  {label}")
        for category, groups in sorted(by_question[question_id].items()):
            counts = ", ".join(f"{g}={n}" for g, n in sorted(groups.items()))
            print(f"    {category:<40} {counts}")


def _shard_drift(rows, question_set) -> None:
    """Per-shard addressed rates, so convention drift cannot pass as a side difference.

    Ten independent annotators each settle their own micro-conventions about what counts as
    answering a question.  That is tolerable noise while the shards are interleaved across
    both sides — it lands on both denominators.  It stops being noise the moment a shard
    boundary coincides with a *group* boundary: then one side was read by the strict
    annotators and the other by the lenient ones, and the difference in addressed rate is
    indistinguishable, downstream, from a real attention gap.

    So this prints what no per-batch check can see: the same question read by different
    workers, side by side.  It gates nothing (a genuine side difference looks the same in
    this table); it puts the comparison in front of the integrator before assembly.
    """
    shards = sorted({source for source, _, _ in rows})
    if len(shards) < 2:
        return
    groups_by_shard: dict[str, set[str]] = {}
    counts: dict[str, dict[str, list[int]]] = {}
    for source, _, row in rows:
        cluster_id = row.get("cluster_id") or ""
        parts = cluster_id.split("-")
        if len(parts) > 1:
            groups_by_shard.setdefault(source, set()).add(parts[1].lower())
        question_id = row.get("question_id")
        if not question_id:
            continue
        cell = counts.setdefault(question_id, {}).setdefault(source, [0, 0])
        cell[1] += 1
        if row.get("addressed"):
            cell[0] += 1

    all_groups = set().union(*groups_by_shard.values()) if groups_by_shard else set()
    single = [s for s, g in groups_by_shard.items() if len(g) == 1]
    if len(all_groups) > 1 and len(single) == len(shards):
        print("\n  DRIFT: every shard covers one side only. Convention drift between "
              "annotators now lands on one denominator and will read downstream as a real "
              "attention gap. Interleave the next split, and read the table below closely.")

    print("\nper-shard addressed rate (convention drift, not a finding — read before assembling):")
    header = "".join(f"{Path(s).name[:14]:>16}" for s in shards)
    print(f"  {'question':<26}{header}{'spread':>9}")
    for question_id in sorted(counts):
        rates, cells = [], ""
        for source in shards:
            addressed, total = counts[question_id].get(source, (0, 0))
            if total:
                rate = addressed / total
                rates.append(rate)
                cells += f"{f'{addressed}/{total} {rate:.0%}':>16}"
            else:
                cells += f"{'—':>16}"
        spread = f"{max(rates) - min(rates):.0%}" if len(rates) > 1 else "—"
        print(f"  {question_id:<26}{cells}{spread:>9}")


def cmd_answers(args, mode: str) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    try:
        run = load_corpus_run(paths)
        articles = load_run_articles(paths)
        if not paths.questions.exists():
            print("no active question set — run the questions phase first", file=sys.stderr)
            return 2
        question_set = read_yaml(paths.questions, QuestionSet)
        rows = _load_batches(args.batches)
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if mode == "assemble" and not (args.run_id and args.model_id):
        print("assemble needs --run-id and --model-id", file=sys.stderr)
        return 2

    cluster_assignment = run.cluster_assignment
    provenance = Provenance(
        skill_version=SKILL_VERSION,
        model_id=args.model_id,
        run_id=args.run_id or "ans-000000000000-00000000",
        timestamp=datetime.now(timezone.utc),
    )
    answers, problems = _build_answers(
        rows, args.topic_id, question_set, articles, cluster_assignment, provenance
    )

    # Cross-record checks: anchors exist, anchors stay inside the cluster, language,
    # duplicates, and — for check mode with a scope — coverage of scope × active questions.
    scoped_assignment = cluster_assignment
    if args.scope_clusters:
        wanted = {c.strip() for c in args.scope_clusters.split(",") if c.strip()}
        scoped_assignment = {
            aid: cid for aid, cid in cluster_assignment.items() if cid in wanted
        }
    scope_questions = None
    if mode == "check" and args.scope_questions:
        scope_questions = [q.strip() for q in args.scope_questions.split(",") if q.strip()]
    report = validate_answers(
        answers,
        question_set,
        articles,
        cluster_assignment=scoped_assignment if mode == "check" else cluster_assignment,
        scope_questions=scope_questions,
        # Anchors the last rebuild rewrote in place.  They resolve, so nothing else here
        # would notice that the answer citing one now quotes a different sentence.
        retexted_anchors=run.retexted_anchors,
    )
    for finding in report.errors:
        problems.append(f"{finding.code}: {finding.target} — {finding.message}")

    print(f"answers: {len(answers)} "
          f"({sum(1 for a in answers if a.addressed)} addressed, "
          f"{sum(1 for a in answers if not a.addressed)} silent)")
    if answers:
        _category_tally(answers, question_set)
        if mode == "check":
            _shard_drift(rows, question_set)
    for problem in problems:
        print(f"  PROBLEM: {problem}")
    if problems:
        print(f"\n{len(problems)} problem(s) — nothing written.")
        return 1
    if mode == "check":
        print("\nbatch is clean.")
        return 0

    run_dir = paths.stage_run_dir("answers", args.run_id)
    if not run_dir.exists():
        print(
            f"missing {run_dir} — run `python -m newsab_schema prepare-run "
            f"{args.topics_root} {args.topic_id} answers {args.run_id}` first",
            file=sys.stderr,
        )
        return 2
    write_jsonl(run_dir / "answers.jsonl", answers)
    print(f"\nwrote {run_dir}/answers.jsonl")
    return 0


def cmd_dump_answers(args) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    if not paths.answers.exists():
        print("no active answers run", file=sys.stderr)
        return 2
    for a in read_jsonl(paths.answers, ClusterAnswer):
        row = {
            "cluster_id": a.reporting_cluster_id,
            "question_id": a.question_id,
            "addressed": a.addressed,
            "summary": a.answer_summary.text if a.answer_summary else None,
            "summary_lang": a.answer_summary.lang if a.answer_summary else None,
            "category": a.answer_category,
            "evidence": a.evidence or None,
            "confidence": a.confidence,
            "notes": a.notes.text if a.notes else None,
            # Who actually wrote this answer.  Carried rows keep it so that re-assembling a
            # run does not restamp them with whichever model happened to run the increment:
            # after two or three incremental passes every answer would otherwise claim to
            # have been written by the last model to touch the topic.
            "model_id": a.provenance.model_id,
        }
        print(json.dumps({k: v for k, v in row.items() if v is not None}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "mode",
        choices=[
            "check-questions",
            "assemble-questions",
            "dump-questions",
            "check",
            "assemble",
            "dump-answers",
        ],
    )
    parser.add_argument("topics_root")
    parser.add_argument("topic_id")
    parser.add_argument("batches", nargs="*")
    parser.add_argument("--run-id", help="required for assemble modes")
    parser.add_argument("--model-id", help="required for assemble modes")
    parser.add_argument(
        "--scope-clusters",
        help="comma-separated cluster IDs this batch is responsible for; coverage is "
        "checked against them instead of the whole corpus",
    )
    parser.add_argument(
        "--scope-questions",
        help="comma-separated question IDs this batch is responsible for; coverage is "
        "checked against them instead of every active question. Use it for an incremental "
        "shard answering only new questions — otherwise the carried questions read as holes",
    )
    args = parser.parse_args(argv)

    try:
        if args.mode == "dump-questions":
            return cmd_dump_questions(args)
        if args.mode == "dump-answers":
            return cmd_dump_answers(args)
        if not args.batches:
            print("this mode needs at least one batch file", file=sys.stderr)
            return 2
        if args.mode in ("check-questions", "assemble-questions"):
            if args.mode == "assemble-questions" and not (args.run_id and args.model_id):
                print("assemble-questions needs --run-id and --model-id", file=sys.stderr)
                return 2
            return cmd_questions(args, "check" if args.mode == "check-questions" else "assemble")
        return cmd_answers(args, args.mode)
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
