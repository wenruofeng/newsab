#!/usr/bin/env python3
"""Repin an existing reader page onto a newer analysis run, mechanically.

An incremental rerun almost never changes what a page *says*.  It changes the numbers the
page says it with, and it changes the ids those numbers are keyed to — and both changes are
deterministic, so neither is writing work.

Two things may move on a `newsab_a1 qa` run:

* **Finding ids in current runs are rank-free**, keyed by question serial and finding
  kind.  Legacy runs used rank-positional ids, and a finding can still be renamed if its
  kind changes.  The semantic key is ``(question_id, kind, secondary)``; this script uses
  that key to carry legacy pages forward and to detect meaning changes.
* **Badge numerators and denominators** recompute from the new group stats.  The checks in
  ``newsab_editorial page-check`` already know the right answer and print it; this applies
  it instead of making someone retype it, which is also non-negotiable 8's rule that no
  computed number in the master is ever hand-entered.

What it deliberately does **not** do is touch prose.  A claim whose text states a number
that no longer recomputes is reported and left alone, because rewording it is a judgement
about what the sentence now means.  That report is the actual writing task the rerun
generated, and it is usually a few sentences rather than a page.

    python skills/write/scripts/repin_page.py topics <topic_id> \
        --page   topics/<t>/editorial/versions/<old-edt>/page.json \
        --qa-run topics/<t>/analysis/<new-qa-run> \
        --out    topics/<t>/editorial/versions/<new-edt>/page.json

Add ``--dry-run`` to print the plan and write nothing.

Exit codes: 0 the page repinned and nothing is left for a human · 1 it repinned but prose
still cites numbers that moved (or something could not be remapped) · 2 inputs missing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from newsab_schema.models.page import ReaderPage

#: Digits inside a claim's text, per language.  Deliberately crude: this only ever asks
#: "does a human need to look at this sentence", never rewrites anything.
_NUMBER = re.compile(r"\d+")


def _key(finding: dict) -> tuple[str, str, bool]:
    return (finding["question_id"], finding["kind"], bool(finding.get("secondary", False)))


def _load_findings(run_dir: Path) -> tuple[dict, dict]:
    """``{finding_id: finding}`` and ``{(question, kind, secondary): finding_id}``."""
    path = run_dir / "findings.jsonl"
    by_id, by_key = {}, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        by_id[row["finding_id"]] = row
        by_key[_key(row)] = row["finding_id"]
    return by_id, by_key


def _group_stats(finding: dict, group_id: str) -> dict | None:
    return next((g for g in finding["groups"] if g["group_id"] == group_id), None)


def _recompute(finding: dict, group_id: str, selector: str) -> tuple[int, int] | str:
    stats = _group_stats(finding, group_id)
    if stats is None:
        return f"finding {finding['finding_id']} has no {group_id} side"
    if selector in ("", "addressed"):
        return stats["clusters_addressed"], stats["clusters_total"]
    if selector == "top_category":
        if stats.get("top_category_tied"):
            return (
                f"top_category is tied between {stats.get('top_categories')} — a badge "
                "cannot name a modal category here; switch the selector to addressed"
            )
        top = stats.get("top_category")
        return (stats.get("category_counts", {}).get(top, 0), stats["clusters_addressed"])
    return f"unknown badge selector {selector!r}"


def _repin_run_ids(
    payload: dict,
    run_json: dict,
    answers_run: str | None,
    questions_run: str | None,
) -> list[str]:
    """Move the page's computed-run pointers onto the analysis run's exact lineage."""
    pinned = run_json.get("inputs", run_json)
    hwc = payload.setdefault("how_we_counted", {})
    remaps: list[str] = []
    for field, value in (
        ("corpus_run_id", pinned.get("corpus_run_id")),
        ("questions_run_id", questions_run),
        ("answers_run_id", answers_run),
        ("qa_run_id", run_json.get("qa_run_id")),
    ):
        if value and hwc.get(field) != value:
            remaps.append(f"how_we_counted: {field} {hwc.get(field)} -> {value}")
            hwc[field] = value
    return remaps


def _analysis_lineage_runs(manifest: Path, qa_run_id: str) -> tuple[str | None, str | None]:
    """Return the answers and questions inputs pinned by one analysis manifest entry.

    The manifest is the dependency authority. In current runs both are direct analysis
    inputs; following the answers edge for questions keeps older, valid manifests
    repinnable without consulting mutable active pointers.
    """
    entries: dict[str, dict] = {}
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                entries[entry.get("run_id", "")] = entry

    qa_entry = entries.get(qa_run_id, {})
    qa_inputs = qa_entry.get("inputs", [])
    answers_run = next((value for value in qa_inputs if value.startswith("ans-")), None)
    questions_run = next((value for value in qa_inputs if value.startswith("qst-")), None)
    if questions_run is None and answers_run:
        answer_inputs = entries.get(answers_run, {}).get("inputs", [])
        questions_run = next(
            (value for value in answer_inputs if value.startswith("qst-")), None
        )
    return answers_run, questions_run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topics_root")
    ap.add_argument("topic_id")
    ap.add_argument("--page", required=True, help="the page.json to carry forward")
    ap.add_argument("--qa-run", required=True, help="the NEW analysis run directory")
    ap.add_argument("--old-qa-run", help="the run the page is pinned to; only needed when a "
                                         "finding id cannot be resolved from the page itself")
    ap.add_argument("--out", help="where to write the repinned page; omit with --dry-run")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    page_path, new_run = Path(args.page), Path(args.qa_run)
    if not page_path.exists() or not (new_run / "findings.jsonl").exists():
        print(f"missing input: {page_path} / {new_run}/findings.jsonl", file=sys.stderr)
        return 2
    if not args.dry_run and not args.out:
        print("--out is required unless --dry-run", file=sys.stderr)
        return 2

    problems: list[str] = []
    remaps: list[str] = []
    rebadged: list[str] = []
    prose: list[str] = []

    payload = json.loads(page_path.read_text(encoding="utf-8"))
    ReaderPage.model_validate(payload)  # fail early, with the schema's own message
    new_by_id, new_by_key = _load_findings(new_run)

    # `how_we_counted` is the page's own statement of what its numbers were computed from.
    # Carrying a page forward without moving it leaves every number correct and the page's
    # account of where they came from false — the one failure the output contract cannot
    # tolerate, since "recomputable from a stored run id" is the whole promise.
    run_json = json.loads((new_run / "run.json").read_text(encoding="utf-8"))
    # `run.json` records the corpus run it analysed but its answers/questions lineage is
    # authoritative in the manifest. Read those exact edges rather than assuming the
    # currently-active annotation artifacts are the ones this analysis actually saw.
    manifest = Path(args.topics_root) / args.topic_id / "manifest" / "manifest.jsonl"
    answers_run, questions_run = _analysis_lineage_runs(
        manifest, run_json.get("qa_run_id", "")
    )
    if questions_run is None:
        problems.append(
            f"analysis run {run_json.get('qa_run_id')} has no questions run in its "
            "manifest lineage; refusing to preserve a possibly stale questions pin"
        )
    remaps.extend(_repin_run_ids(payload, run_json, answers_run, questions_run))

    old_by_id: dict = {}
    if args.old_qa_run:
        old_by_id, _ = _load_findings(Path(args.old_qa_run))


    def resolve(old_id: str, question_id: str, kind_hint: str | None, secondary: bool) -> str | None:
        """The new id for a finding, keyed by meaning rather than by rank."""
        if old_id in old_by_id:
            wanted = _key(old_by_id[old_id])
        elif kind_hint is not None:
            wanted = (question_id, kind_hint, secondary)
        else:
            return None
        return new_by_key.get(wanted)

    for angle in payload["angles"]:
        where = f"angle {angle['rank']}"
        question_id = angle["question_id"]
        old_finding = angle["finding_id"]
        kind_hint = None
        if old_finding in new_by_id and new_by_id[old_finding]["question_id"] == question_id:
            new_finding = old_finding  # the rank happened not to move
        else:
            if old_finding in old_by_id:
                new_finding = resolve(old_finding, question_id, None, False)
            else:
                # No old run given: the angle's own question plus a primary (non-secondary)
                # finding is enough in every case the writer can produce.
                new_finding = next(
                    (fid for key, fid in new_by_key.items()
                     if key[0] == question_id and not key[2]),
                    None,
                )
            if new_finding is None:
                problems.append(
                    f"{where}: no finding in the new run answers {question_id} — the "
                    "question stopped producing one (often `insufficient`), so this angle "
                    "is a writing decision, not a repin"
                )
                continue
            remaps.append(f"{where}: finding {old_finding} -> {new_finding}")
            angle["finding_id"] = new_finding

        finding = new_by_id[angle["finding_id"]]
        if angle.get("kind") != finding["kind"]:
            problems.append(
                f"{where}: the finding changed kind, {angle.get('kind')!r} -> "
                f"{finding['kind']!r}. The card asserts a different relationship between "
                "the two sides than it did; this is a writing decision, not a repin"
            )
        if finding.get("strength") == "unsupported":
            problems.append(
                f"{where}: {finding['finding_id']} is now `unsupported` — an angle cannot "
                "assert it (V-3). Either the angle comes off the page or the rerun changed "
                "the story"
            )

        for side in angle.get("sides", []):
            badge = side["badge"]
            base, _, selector = badge["computed_from"].partition(":")
            badge["computed_from"] = (
                f"{angle['finding_id']}:{selector}" if selector else angle["finding_id"]
            )
            result = _recompute(finding, side["group_id"], selector)
            if isinstance(result, str):
                problems.append(f"{where} ({side['group_id']}): {result}")
                continue
            if (badge["numerator"], badge["denominator"]) != tuple(result):
                rebadged.append(
                    f"{where} ({side['group_id']}): {badge['numerator']}/{badge['denominator']}"
                    f" -> {result[0]}/{result[1]}"
                )
                badge["numerator"], badge["denominator"] = result
            # The label bound to a counted modal category must follow the category.
            if selector == "top_category":
                stats = _group_stats(finding, side["group_id"]) or {}
                if side.get("answer_category") and side["answer_category"] != stats.get("top_category"):
                    problems.append(
                        f"{where} ({side['group_id']}): the modal category moved from "
                        f"{side['answer_category']!r} to {stats.get('top_category')!r}; the "
                        "answer_label and the answer text describe the old one"
                    )

        # `caveat` is reader text with no computed_from; only `detail` carries claims.
        for field in ("detail",):
            for claim in angle.get(field) or []:
                ref = claim.get("computed_from")
                if not ref:
                    continue
                base, _, selector = ref.partition(":")
                target = resolve(base, question_id, None, False)
                if target is None:
                    target = next(
                        (fid for key, fid in new_by_key.items() if key[0] == question_id),
                        None,
                    )
                if target is None:
                    problems.append(f"{where} {field}: cannot remap computed_from {ref!r}")
                    continue
                if target != base:
                    remaps.append(f"{where} {field}: computed_from {base} -> {target}")
                    claim["computed_from"] = f"{target}:{selector}" if selector else target
                numbers = sorted({
                    n for text in (claim.get("text", {}).get("values") or {}).values()
                    for n in _NUMBER.findall(text)
                })
                if numbers:
                    prose.append(
                        f"{where} {field}: states {', '.join(numbers)} and is bound to "
                        f"{claim['computed_from']} — recheck the sentence against the new run"
                    )

    for line in remaps:
        print(f"  remap    {line}")
    for line in rebadged:
        print(f"  rebadge  {line}")
    for line in prose:
        print(f"  PROSE    {line}")
    for line in problems:
        print(f"  PROBLEM  {line}")

    try:
        ReaderPage.model_validate(payload)
    except Exception as exc:
        print(f"  PROBLEM  the repinned page no longer validates: {exc}")
        problems.append("schema")

    print(
        f"\n{len(remaps)} id remap(s), {len(rebadged)} badge(s) recomputed, "
        f"{len(prose)} claim(s) for a human to reread, {len(problems)} problem(s)"
    )
    if args.dry_run:
        print("dry run — nothing written")
        return 1 if (problems or prose) else 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"written  {out}")
    print("now run: python -m newsab_editorial page-check ... --langs en")
    return 1 if (problems or prose) else 0


if __name__ == "__main__":
    raise SystemExit(main())
