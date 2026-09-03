#!/usr/bin/env python3
"""Deterministic checks and assembly for the normalize stage's category map.

    check      validate a draft (or final) map against the topic's active question set
               and answers run; print the raw → merged tally diff per question
    plan       read pass A's draft and print whether a second pass is owed at all, and
               on which questions — the intersection is a subset of pass A, so a
               second pass over a question pass A left alone cannot change the map
    intersect  two-pass self-consistency: keep only merge groups both drafts agree on
               (as equivalence classes; canonical/rationale from the first draft)
    assemble   stamp headers + provenance onto an agreed draft and write
               category_map.json + two_pass.json into a prepared normalization run dir

    python scripts/check_map.py check topics <topic_id> draft.json
    python scripts/check_map.py plan draft_a.json
    python scripts/check_map.py intersect draft_a.json draft_b.json --out agreed.json
    python scripts/check_map.py assemble topics <topic_id> agreed.json \
        --run-id nrm-… --model-id <model> --two-pass-json @two_pass.json

Exit codes: 0 ok · 1 check failed / groups dropped · 2 inputs missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap  # noqa: F401

from newsab_schema.common import Provenance
from newsab_schema.io import ArtifactError, read_jsonl, read_yaml
from newsab_schema.models.category_map import CategoryMap
from newsab_schema.models.qa import ANSWER_CATEGORY_UNCLEAR, ClusterAnswer, QuestionSet
from newsab_schema.paths import TopicPaths

def _skill_version() -> str:
    """Read the version from the sibling SKILL.md so provenance cannot drift from it."""
    import re

    text = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r'^\s*(?:newsab-)?version:\s*"?([0-9][\w.]*)"?\s*$', text, re.MULTILINE)
    if match is None:
        raise ArtifactError("skills/normalize/SKILL.md has no parseable 'version:' line")
    return f"normalize-{match.group(1)}"


SKILL_VERSION = _skill_version()


def _load_draft(path: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"cannot read draft {path}: {exc}")
    if not isinstance(payload, dict) or not isinstance(payload.get("merges"), dict):
        raise ArtifactError(f"{path}: a draft is {{\"merges\": {{…}}}}")
    return payload


def _as_map(draft: dict, paths: TopicPaths, run_id: str, model_id: str) -> CategoryMap:
    """Validate a draft by lifting it into a full CategoryMap with the active headers."""
    question_set = read_yaml(paths.questions, QuestionSet)
    answers_run = paths.active_run_id("answers") or "unversioned"
    return CategoryMap.model_validate(
        {
            "topic_id": paths.topic_id,
            "question_set_version": question_set.question_set_version,
            "answers_run_id": answers_run,
            "merges": draft["merges"],
            "provenance": {
                "skill_version": SKILL_VERSION,
                "model_id": model_id,
                "run_id": run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
    )


def _observed(paths: TopicPaths) -> dict[str, dict[str, dict[str, int]]]:
    """question_id -> group_id -> raw comparable category counts."""
    answers = read_jsonl(paths.answers, ClusterAnswer)
    observed: dict[str, dict[str, dict[str, int]]] = {}
    for a in answers:
        if not a.addressed or a.answer_category == ANSWER_CATEGORY_UNCLEAR:
            continue
        counts = observed.setdefault(a.question_id, {}).setdefault(a.group_id, {})
        counts[a.answer_category] = counts.get(a.answer_category, 0) + 1
    return observed


def cmd_check(args: argparse.Namespace) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    try:
        draft = _load_draft(args.draft)
        cmap = _as_map(draft, paths, run_id="nrm-000000000000-00000000", model_id="draft-check")
        question_set = read_yaml(paths.questions, QuestionSet)
        observed = _observed(paths)
    except (ArtifactError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    active = {q.question_id for q in question_set.active}
    for question_id, groups in cmap.merges.items():
        if question_id not in active:
            errors.append(f"{question_id}: not an active question of this topic")
            continue
        vocabulary = set()
        for side_counts in observed.get(question_id, {}).values():
            vocabulary |= set(side_counts)
        for group in groups:
            for member in group.members:
                if member not in vocabulary:
                    errors.append(
                        f"{question_id}: member {member!r} was never observed in the "
                        "active answers run — merges cover observed categories only"
                    )
            if group.canonical not in vocabulary:
                warnings.append(
                    f"{question_id}: canonical {group.canonical!r} is a fresh umbrella "
                    "spelling (not itself observed) — allowed, review it"
                )

    for question_id in sorted(cmap.merges):
        if question_id not in active:
            continue
        print(f"{question_id}")
        for group_id, raw in sorted(observed.get(question_id, {}).items()):
            merged: dict[str, int] = {}
            for category, count in raw.items():
                canonical = cmap.project(question_id, category)
                merged[canonical] = merged.get(canonical, 0) + count
            if merged != raw:
                print(f"  {group_id} raw:    {dict(sorted(raw.items(), key=lambda kv: -kv[1]))}")
                print(f"  {group_id} merged: {dict(sorted(merged.items(), key=lambda kv: -kv[1]))}")
            else:
                print(f"  {group_id}: unchanged")

    for warning in warnings:
        print(f"warning: {warning}")
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    if not any(merges for merges in draft.get("merges", {}).values()):
        print("map ok — identity map: no merges, raw and merged tallies are identical")
    else:
        print("map ok")
    # The tallies above are this run's; name it, so the two-pass record's
    # ``answers_run_id`` is read off the topic rather than remembered.
    print(f"active answers run: {paths.active_run_id('answers') or '(none)'}")
    return 0


def _classes(draft: dict) -> dict[str, set[frozenset[str]]]:
    """question_id -> the set of merge equivalence classes (members ∪ canonical)."""
    out: dict[str, set[frozenset[str]]] = {}
    for question_id, groups in draft["merges"].items():
        out[question_id] = {
            frozenset(set(g["members"]) | {g["canonical"]}) for g in groups
        }
    return out


TWO_PASS_REQUIRED = (
    "answers_run_id",
    "pass_a_groups",
    "pass_b_questions",
    "pass_b_groups",
    "dropped",
)
TWO_PASS_OPTIONAL = ("both_passes_rejected", "sent_upstream")

TWO_PASS_DOC = """the two-pass record is a JSON object (inline or @file):
  {"answers_run_id": "ans-…", "pass_a_groups": 0, "pass_b_questions": [],
   "pass_b_groups": null, "dropped": 0,
   "both_passes_rejected": "…optional prose…", "sent_upstream": "…optional prose…"}
pass_b_groups is null exactly when the second pass was skipped;
answers_run_id names the answers run the two passes actually judged, and `assemble`
refuses it unless it is the topic's active answers run."""


def _group_count(draft: dict) -> int:
    return sum(len(groups) for groups in draft["merges"].values())


def _pass_b_scope(draft: dict) -> list[str]:
    """The questions a second pass can still change: the ones pass A drew groups on."""
    return sorted(q for q, groups in draft["merges"].items() if groups)


def _load_two_pass(raw: str) -> dict:
    """Parse ``--two-pass-json`` (inline JSON or ``@path``) and check its shape."""
    text = raw
    if raw.startswith("@"):
        try:
            text = Path(raw[1:]).read_text(encoding="utf-8")
        except OSError as exc:
            raise ArtifactError(f"cannot read two-pass record {raw[1:]}: {exc}")
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"--two-pass-json is not valid JSON: {exc}\n{TWO_PASS_DOC}")
    if not isinstance(record, dict):
        raise ArtifactError(f"--two-pass-json must be an object\n{TWO_PASS_DOC}")
    missing = [key for key in TWO_PASS_REQUIRED if key not in record]
    if missing:
        raise ArtifactError(
            f"two-pass record is missing {', '.join(missing)}\n{TWO_PASS_DOC}"
        )
    unknown = sorted(set(record) - set(TWO_PASS_REQUIRED) - set(TWO_PASS_OPTIONAL))
    if unknown:
        raise ArtifactError(
            f"two-pass record has unknown key(s): {', '.join(unknown)}\n{TWO_PASS_DOC}"
        )
    for key in ("pass_a_groups", "dropped"):
        if not isinstance(record[key], int) or isinstance(record[key], bool) or record[key] < 0:
            raise ArtifactError(f"two-pass record: {key} must be a non-negative integer")
    if record["pass_b_groups"] is not None and (
        not isinstance(record["pass_b_groups"], int)
        or isinstance(record["pass_b_groups"], bool)
        or record["pass_b_groups"] < 0
    ):
        raise ArtifactError(
            "two-pass record: pass_b_groups must be a non-negative integer, or null "
            "when the second pass was skipped"
        )
    if not isinstance(record["answers_run_id"], str) or not record["answers_run_id"].strip():
        raise ArtifactError(
            "two-pass record: answers_run_id must be the id of the answers run the two "
            "passes judged"
        )
    scope = record["pass_b_questions"]
    if not isinstance(scope, list) or not all(isinstance(q, str) for q in scope):
        raise ArtifactError("two-pass record: pass_b_questions must be a list of question ids")
    for key in TWO_PASS_OPTIONAL:
        if key in record and not isinstance(record[key], str):
            raise ArtifactError(f"two-pass record: {key} must be a string")
    return record


def _check_two_pass(record: dict, cmap) -> list[str]:
    """The self-consistency rules that tie the record to the map it is filed with.

    ``agreed = A ∩ B ⊆ A``: when pass A drew nothing, no second pass can change the
    outcome, so running one is a proven no-op and the record must say it was skipped.
    """
    final_groups = sum(len(groups) for groups in cmap.merges.values())
    errors: list[str] = []
    if record["pass_a_groups"] == 0:
        if record["pass_b_groups"] is not None or record["pass_b_questions"]:
            errors.append(
                "pass A drew no groups, so the intersection is empty whatever the second "
                "pass says — the second pass must be skipped "
                "(pass_b_groups: null, pass_b_questions: [])"
            )
        if record["dropped"]:
            errors.append("pass A drew no groups, so nothing can have been dropped")
        if final_groups:
            errors.append(
                f"the assembled map has {final_groups} group(s) but the record says pass A "
                "drew none — the map cannot contain what no pass proposed"
            )
        return errors
    if record["pass_b_groups"] is None:
        errors.append(
            f"pass A drew {record['pass_a_groups']} group(s): a second pass is owed on "
            f"{', '.join(_scope_hint(cmap)) or 'those questions'} before any of them may ship"
        )
        return errors
    if not record["pass_b_questions"]:
        errors.append("pass_b_questions is empty but the second pass reports groups")
    unjudged = [q for q in sorted(cmap.merges) if q not in set(record["pass_b_questions"])]
    if unjudged:
        errors.append(
            "questions in the map that the second pass never judged: " + ", ".join(unjudged)
        )
    if final_groups > record["pass_a_groups"]:
        errors.append(
            f"the map has {final_groups} group(s) but pass A drew {record['pass_a_groups']}"
        )
    if final_groups > record["pass_b_groups"]:
        errors.append(
            f"the map has {final_groups} group(s) but pass B drew {record['pass_b_groups']}"
        )
    expected = (record["pass_a_groups"] - final_groups) + (record["pass_b_groups"] - final_groups)
    if expected >= 0 and record["dropped"] != expected:
        errors.append(
            f"dropped={record['dropped']} does not match the drafts: "
            f"(A {record['pass_a_groups']} - agreed {final_groups}) + "
            f"(B {record['pass_b_groups']} - agreed {final_groups}) = {expected} "
            "— use the count intersect printed"
        )
    return errors


def _scope_hint(cmap) -> list[str]:
    return sorted(cmap.merges)


def cmd_plan(args: argparse.Namespace) -> int:
    """Say whether pass B is owed, and on which questions."""
    try:
        draft = _load_draft(args.draft_a)
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    scope = _pass_b_scope(draft)
    groups = _group_count(draft)
    skeleton = {
        "answers_run_id": args.answers_run_id or "<the ans-… run these passes judged>",
        "pass_a_groups": groups,
        "pass_b_questions": scope,
        "pass_b_groups": None,
        "dropped": 0,
    }
    if not scope:
        print(
            "pass A drew no groups — skip the second pass: the agreed map is "
            "A ∩ B ⊆ A = {}, so pass B cannot change it."
        )
        print(f"assemble {args.draft_a} directly, with --two-pass-json:")
    else:
        print(f"pass A drew {groups} group(s) on {len(scope)} question(s) — pass B is owed on:")
        for question_id in scope:
            print(f"  {question_id}")
        print("judge only those questions in the second pass, then intersect; --two-pass-json:")
    print(json.dumps(skeleton, ensure_ascii=False, sort_keys=True))
    return 0


def cmd_intersect(args: argparse.Namespace) -> int:
    try:
        first = _load_draft(args.draft_a)
        second = _load_draft(args.draft_b)
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not _group_count(first):
        print(
            "note: pass A drew no groups — this intersection was decided before pass B "
            "ran; `plan` would have skipped it"
        )
    classes_b = _classes(second)
    agreed: dict[str, list[dict]] = {}
    dropped = 0
    for question_id, groups in first["merges"].items():
        keep = []
        for group in groups:
            cls = frozenset(set(group["members"]) | {group["canonical"]})
            if cls in classes_b.get(question_id, set()):
                keep.append(group)
            else:
                dropped += 1
                print(f"dropped (passes disagree): {question_id} {sorted(cls)}")
        if keep:
            agreed[question_id] = keep
    for question_id, classes in classes_b.items():
        first_classes = _classes(first).get(question_id, set())
        for cls in classes - first_classes:
            dropped += 1
            print(f"dropped (passes disagree): {question_id} {sorted(cls)}")
    Path(args.out).write_text(
        json.dumps({"merges": agreed}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    kept = sum(len(v) for v in agreed.values())
    print(f"agreed groups: {kept} · dropped: {dropped} · wrote {args.out}")
    return 0


def cmd_assemble(args: argparse.Namespace) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    run_dir = paths.stage_run_dir("normalization", args.run_id)
    if not run_dir.is_dir():
        print(f"run directory not prepared: {run_dir} (use prepare-run)", file=sys.stderr)
        return 2
    target = run_dir / "category_map.json"
    if target.exists():
        print(f"refusing to overwrite immutable artifact: {target}", file=sys.stderr)
        return 1
    two_pass_target = run_dir / "two_pass.json"
    if two_pass_target.exists():
        print(f"refusing to overwrite immutable artifact: {two_pass_target}", file=sys.stderr)
        return 1
    try:
        draft = _load_draft(args.draft)
        cmap = _as_map(draft, paths, run_id=args.run_id, model_id=args.model_id)
        two_pass = _load_two_pass(args.two_pass_json)
    except (ArtifactError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    # Same sentinel :func:`_as_map` stamps into the map header, so the two artifacts of a
    # run always name the answers run the same way.
    active_answers = paths.active_run_id("answers") or "unversioned"
    if two_pass["answers_run_id"] != active_answers:
        # Two normalize runs have been filed whose two_pass.json were byte-identical
        # while claiming to have judged different answers runs.  A record that has to
        # name its own answers run cannot be copied forward without saying so.
        print(
            f"error: the two-pass record says it judged answers run "
            f"{two_pass['answers_run_id']!r}, but this topic's active answers run is "
            f"{active_answers!r} — judge the active answers, or activate the run you "
            "judged; never re-file an older run's record",
            file=sys.stderr,
        )
        return 1
    errors = _check_two_pass(two_pass, cmap)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    target.write_text(cmap.model_dump_json(indent=2) + "\n", encoding="utf-8")
    two_pass_target.write_text(
        json.dumps(two_pass, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    groups = sum(len(v) for v in cmap.merges.values())
    members = sum(len(g.members) for v in cmap.merges.values() for g in v)
    print(f"wrote {target}")
    print(f"wrote {two_pass_target}")
    print(f"questions_with_merges={len(cmap.merges)} merge_groups={groups} categories_merged={members}")
    print(
        "second pass: "
        + ("skipped (pass A drew nothing)" if two_pass["pass_b_groups"] is None
           else f"{two_pass['pass_b_groups']} group(s) over "
                f"{len(two_pass['pass_b_questions'])} question(s), dropped {two_pass['dropped']}")
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="validate a draft against the topic's artifacts")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("draft")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("plan", help="is a second pass owed, and on which questions")
    p.add_argument("draft_a")
    p.add_argument(
        "--answers-run-id",
        help="fill the two-pass skeleton's answers_run_id (as `check` printed it)",
    )
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("intersect", help="keep only groups two drafts agree on")
    p.add_argument("draft_a")
    p.add_argument("draft_b")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_intersect)

    p = sub.add_parser("assemble", help="stamp headers and write into a prepared run dir")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("draft")
    p.add_argument("--run-id", required=True)
    p.add_argument("--model-id", required=True)
    p.add_argument(
        "--two-pass-json",
        required=True,
        help="the two-pass record, inline JSON or @path — see `plan` for the skeleton",
    )
    p.set_defaults(func=cmd_assemble)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
