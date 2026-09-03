#!/usr/bin/env python3
"""Emit a structurally complete ReaderPage draft so nobody guesses the schema.

Pulls everything computable from the topic's artifacts — the four run IDs, every active
question for the lexicon, every observed answer category, every collect-stage topic pivot
the page will display, the group ids — and marks every judgement slot ``TODO`` while
keeping the file schema-valid.  Eligible findings are materialised with recomputed badges
and real anchors so the evidence-packet command can consume the draft before any prose is
written.  Authoritative schema: ``packages/schema/dist/reader_page.schema.json``.
The machine-owned page record requires no writer copy.

**The reader lexicon is inherited, not regenerated.**  Its four maps are reader copy a
writer wrote and a reviewer approved; only entries the topic has no wording for yet are
generated from the machine vocabulary (the annotation question, the raw counting key, the
English pivot).  Regenerating them silently reverts every reader-facing rewording on the
next rerun — a divergence headline that had a misleading statistic edited out of it came
back verbatim one rerun later, and only a human reading the page caught it.

    python skills/write/scripts/page_init.py <topics_root> <topic_id> \
        --qa-run <qa-run-id> -o draft_page.json

By default the previous wording comes from the topic's active editorial page; pass
``--previous-page <path>`` to name another one, or ``--no-inherit`` for a deliberately
blank slate (a first draft, or a rewrite that must start from the machine vocabulary).

Exit codes: 0 written · 2 inputs missing.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from newsab_editorial.page_checks import PLACEHOLDER_MODEL_ID, PLACEHOLDER_RUN_ID
from newsab_editorial.topics_raised import load_topics_by_article
from newsab_schema.io import read_yaml
from newsab_schema.models.corpus import TopicManifest
from newsab_schema.paths import TopicPaths


def _skill_version() -> str:
    text = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r'^\s*(?:newsab-)?version:\s*"?([0-9][\w.]*)"?\s*$', text, re.MULTILINE
    )
    return f"write-{match.group(1)}" if match else "write-unknown"


def _load_previous_lexicon(path: Path) -> tuple[dict, str | None]:
    """The reader wording an earlier page of this topic already carries.

    Returns ``(lexicon, questions_run_id)``.  A page that cannot be read is not a reason to
    fail — the draft is still writable, it just starts from the machine vocabulary — but it
    is reported, because silently starting blank is the whole defect this exists to prevent.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"could not read previous page {path}: {exc}", file=sys.stderr)
        return {}, None
    lexicon = payload.get("lexicon")
    if not isinstance(lexicon, dict):
        return {}, None
    run = (payload.get("how_we_counted") or {}).get("questions_run_id")
    return lexicon, run if isinstance(run, str) else None


def _inherit(previous: dict, kind: str, key: str):
    """The previous page's wording for one lexicon key, or ``None``."""
    entry = (previous.get(kind) or {}).get(key)
    if isinstance(entry, dict) and isinstance(entry.get("values"), dict) and entry["values"]:
        return entry
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("topics_root")
    ap.add_argument("topic_id")
    ap.add_argument("--qa-run", required=True, help="the analyze run this page pins")
    ap.add_argument("-o", "--out", default="draft_page.json")
    ap.add_argument(
        "--previous-page",
        default=None,
        help="the page whose reader lexicon this draft inherits (default: the topic's "
        "active editorial page)",
    )
    ap.add_argument(
        "--no-inherit",
        action="store_true",
        help="start the reader lexicon from the machine vocabulary instead of the "
        "previous page — for a first draft, or a deliberate rewrite",
    )
    args = ap.parse_args(argv)

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    if not paths.topic_manifest.exists():
        print(f"no topic manifest: {paths.topic_manifest}", file=sys.stderr)
        return 2
    manifest = read_yaml(paths.topic_manifest, TopicManifest)

    stats_path = paths.root / "analysis" / args.qa_run / "question_stats.json"
    if not stats_path.exists():
        print(f"no question_stats.json under {stats_path.parent}", file=sys.stderr)
        return 2
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    findings_path = stats_path.with_name("findings.jsonl")
    findings = [
        json.loads(line)
        for line in findings_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    eligible = [row for row in findings if row.get("strength") in {"supported", "weak"}]
    if not eligible:
        print(f"no supported or weak findings under {stats_path.parent}", file=sys.stderr)
        return 2

    questions_run = paths.active_run_id("questions")
    answers_run = paths.active_run_id("answers")
    corpus_run = paths.active_run_id("corpus")
    if not (questions_run and answers_run and corpus_run):
        print("missing an active questions/answers/corpus run", file=sys.stderr)
        return 2

    previous: dict = {}
    previous_from: Path | None = None
    previous_questions_run: str | None = None
    if args.no_inherit:
        pass
    elif args.previous_page:
        candidate = Path(args.previous_page)
        if not candidate.is_file():
            print(f"no previous page: {candidate}", file=sys.stderr)
            return 2
        previous, previous_questions_run = _load_previous_lexicon(candidate)
        previous_from = candidate
    elif paths.editorial_page.is_file():
        previous, previous_questions_run = _load_previous_lexicon(paths.editorial_page)
        previous_from = paths.editorial_page

    question_ids = (
        sorted(stats.get("questions", stats).keys()) if isinstance(stats, dict) else []
    )
    categories: set[str] = set()
    per_question = stats.get("questions", stats)
    for q in per_question.values():
        if isinstance(q, dict):
            for side in (q.get("groups") or {}).values():
                categories.update((side.get("category_counts") or {}).keys())

    group_ids = [g.group_id for g in manifest.groups]
    angles = []
    for rank, finding in enumerate(eligible[:6], 1):
        sides = []
        # Emit sides in the MANIFEST's group order, not the analysis run's.  The renderer
        # draws both the answer cards and the explanation columns in manifest order, so a
        # page whose sides are stored the other way round is one sort away from showing
        # each side's paragraph under the other side's card.
        finding_groups = sorted(
            finding["groups"],
            key=lambda g: group_ids.index(g["group_id"]) if g["group_id"] in group_ids else 9,
        )
        # An attention_gap angle always lays out the finding's quiet side as the silent
        # block: no answer card, no writer-picked quotes, an `addressed` badge, and a
        # paragraph that states annotation-layer near-silence (page_checks, qa-0.4.0).
        # The quiet side is chosen the same way page_checks chooses it.
        quiet_id = None
        if finding["kind"] == "attention_gap":
            quiet_id = min(
                finding_groups,
                key=lambda g: (
                    g["clusters_addressed"] / g["clusters_total"]
                    if g["clusters_total"]
                    else 0.0,
                    g["group_id"],
                ),
            )["group_id"]
        for group in finding_groups:
            category = group["top_category"]
            evidence = group.get("sample_evidence") or []
            silent = group["group_id"] == quiet_id
            selector = (
                "addressed"
                if silent or group.get("top_category_tied")
                else "top_category"
            )
            numerator = (
                group["clusters_addressed"]
                if selector == "addressed"
                else group["category_counts"][category]
            )
            denominator = (
                group["clusters_total"] if selector == "addressed"
                else group["clusters_addressed"]
            )
            if silent:
                sides.append(
                    {
                        "group_id": group["group_id"],
                        "answer": {
                            "claim_type": "corpus_aggregate",
                            "text": {
                                "values": {
                                    "en": "TODO: state the annotation-layer near-silence "
                                    "and what the few mentions were attached to; assert no "
                                    "answer for this side"
                                }
                            },
                            "evidence": evidence,
                            "computed_from": finding["finding_id"],
                        },
                        "answer_label": None,
                        "answer_category": None,
                        "quotes": [],
                        "badge": {
                            "group_id": group["group_id"],
                            "numerator": numerator,
                            "denominator": denominator,
                            "label": None,
                            "computed_from": f'{finding["finding_id"]}:addressed',
                        },
                        "is_silent_side": True,
                    }
                )
                continue
            sides.append(
                {
                    "group_id": group["group_id"],
                    "answer": {
                        "claim_type": "corpus_aggregate",
                        "text": {"values": {"en": "TODO: explain why this answer appears in the counted reports"}},
                        "evidence": evidence,
                        "computed_from": finding["finding_id"],
                    },
                    "answer_label": {"values": {"en": category.replace("_", " ")}},
                    "answer_category": category,
                    "quotes": [{"sentence_id": evidence[0]}],
                    "badge": {
                        "group_id": group["group_id"],
                        "numerator": numerator,
                        "denominator": denominator,
                        "label": None,
                        "computed_from": f'{finding["finding_id"]}:{selector}',
                    },
                    "is_silent_side": False,
                }
            )
        shared = None
        if finding["kind"] == "consensus" and len({s["answer_category"] for s in sides}) == 1:
            shared = {"values": {"en": sides[0]["answer_category"].replace("_", " ")}}
        angles.append(
            {
                "rank": rank,
                "question_id": finding["question_id"],
                "finding_id": finding["finding_id"],
                "kind": finding["kind"],
                "question_display": None,
                "sides": sides,
                "detail": [],
                "caveat": None,
                "editorial_interest": {"text": "TODO: explain why a reader cares", "lang": "en"},
                "shared_answer_label": shared,
                "commentary_joint": None,
            }
        )

    # The reader lexicon: the previous page's approved wording wherever the topic has some,
    # the machine vocabulary only for keys that have never been given reader words.  The
    # generated fallbacks below are placeholders the writer is expected to replace — the
    # annotation question is written for an annotator, and a counting key is not a phrase.
    lexicon: dict[str, dict] = {"questions": {}, "categories": {}, "topics": {}, "scope": {}}
    inherited_counts = {kind: 0 for kind in lexicon}

    def _entry(kind: str, key: str, generated):
        kept = _inherit(previous, kind, key)
        if kept is not None:
            inherited_counts[kind] += 1
            return kept
        return generated

    for qid in question_ids:
        lexicon["questions"][qid] = _entry(
            "questions", qid, {"values": {"en": per_question[qid]["question"]}}
        )
    for cat in sorted(categories):
        lexicon["categories"][cat] = _entry(
            "categories", cat, {"values": {"en": cat.replace("_", " ")}}
        )
    # Every collect-stage pivot the page displays needs reader wording or page-check fails:
    # the pivot is a cross-language concept key, never reader copy.
    pivots = sorted(
        {
            (entry.get("pivot_en") or "").strip()
            for entries in load_topics_by_article(paths).values()
            for entry in (entries or [])
            if (entry.get("pivot_en") or "").strip()
        }
    )
    for pivot in pivots:
        lexicon["topics"][pivot] = _entry("topics", pivot, {"values": {"en": pivot}})
    # Scope bullets are the manifest's English, which is hashed into the topic's approval
    # and cannot carry a translation; there is nothing to generate, only wording to keep.
    for phrase in [*manifest.include, *manifest.exclude]:
        kept = _inherit(previous, "scope", phrase)
        if kept is not None:
            inherited_counts["scope"] += 1
            lexicon["scope"][phrase] = kept

    intro_anchor = eligible[0]["groups"][0]["sample_evidence"][0]
    draft = {
        "topic_id": manifest.topic_id,
        "title": {"values": {"en": "TODO: reader-facing title"}},
        "intro": [
            {
                "claim_type": "source_claim",
                "text": {
                    "values": {
                        "en": "TODO: one fact per claim, 4-6 claims, each with its own anchor"
                    }
                },
                "evidence": [intro_anchor],
                "computed_from": None,
            }
        ],
        "hook": None,
        "angles": angles,
        "lexicon": lexicon,
        "visuals": [
            {
                "kind": "concept_cloud",
                "data_from": "qa_run:question_stats",
                "caption": {
                    "values": {"en": "Key concept cloud", "zh-CN": "关键概念云"}
                },
            }
        ],
        "how_we_counted": {
            "corpus_run_id": corpus_run,
            "questions_run_id": questions_run,
            "answers_run_id": answers_run,
            "qa_run_id": args.qa_run,
            "notes": [],
        },
        "provenance": {
            "skill_version": _skill_version(),
            # page-check refuses both placeholders: fill them with the page's
            # own run id and the writing model before step 4 can pass.
            "model_id": PLACEHOLDER_MODEL_ID,
            "run_id": PLACEHOLDER_RUN_ID,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    }
    out = Path(args.out)
    out.write_text(
        json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {out} — {len(question_ids)} lexicon questions, {len(categories)} categories, "
        f"{len(pivots)} topic pivots, {len(group_ids)} sides per angle, "
        f"{len(angles)} eligible angles. "
        "Every TODO is a writing decision; computed structure is ready for the evidence packet."
    )
    if previous_from is not None:
        kept = ", ".join(
            f"{count} {kind}" for kind, count in inherited_counts.items() if count
        )
        print(
            f"reader lexicon inherited from {previous_from}: {kept or 'nothing matched'}. "
            "Everything else is the machine vocabulary and reads like it — rewrite it."
        )
        if previous_questions_run and previous_questions_run != questions_run:
            print(
                f"NOTE the inherited wording was written against questions run "
                f"{previous_questions_run}, this page pins {questions_run}: re-read every "
                "inherited question against the annotation question it now stands for — a "
                "reader question must ask the same thing, never a different or narrower one.",
                file=sys.stderr,
            )
    else:
        print(
            "reader lexicon generated from the machine vocabulary (no previous page "
            "inherited); every question, category and topic label still needs reader words."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
