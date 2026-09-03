#!/usr/bin/env python3
"""Print one question's full normalization input: question + guidance + both sides'
category tallies + every category's answer summaries + verbatim evidence sentences.

The normalize judgement must see a question's whole vocabulary at once (no streaming
merges — references/coding_practices.md §1), so this prints everything per question.

    python scripts/show_tallies.py topics <topic_id> --list
    python scripts/show_tallies.py topics <topic_id> --question QST-aabb-river-light-002
    python scripts/show_tallies.py topics <topic_id>            # every question

Exit codes: 0 ok · 2 inputs missing.
"""

from __future__ import annotations

import argparse
import sys

import _bootstrap  # noqa: F401

from newsab_schema.io import ArtifactError, read_jsonl, read_yaml
from newsab_schema.models.qa import ANSWER_CATEGORY_UNCLEAR, ClusterAnswer, QuestionSet
from newsab_schema.paths import TopicPaths
from newsab_schema.store import load_run_articles

MAX_EVIDENCE_PER_CATEGORY = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("topics_root")
    parser.add_argument("topic_id")
    parser.add_argument("--question", help="one QST-… id (default: every active question)")
    parser.add_argument("--list", action="store_true", help="one line per question, no detail")
    args = parser.parse_args(argv)

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    try:
        question_set = read_yaml(paths.questions, QuestionSet)
        answers = read_jsonl(paths.answers, ClusterAnswer)
        articles = load_run_articles(paths)
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    sentences: dict[str, str] = {}
    for article in articles:
        for paragraph in article.structured_text:
            for sentence in paragraph.sentences:
                sid = f"{article.article_id}:P{paragraph.index:02d}:S{sentence.index:02d}"
                sentences[sid] = sentence.text

    by_question: dict[str, list[ClusterAnswer]] = {}
    for a in answers:
        if a.addressed:
            by_question.setdefault(a.question_id, []).append(a)

    selected = [q for q in question_set.active if not args.question or q.question_id == args.question]
    if args.question and not selected:
        print(f"no active question {args.question}", file=sys.stderr)
        return 2

    for question in selected:
        rows = by_question.get(question.question_id, [])
        if args.list:
            comparable = [a for a in rows if a.answer_category != ANSWER_CATEGORY_UNCLEAR]
            categories = sorted({a.answer_category for a in comparable})
            print(f"{question.question_id}  categories={len(categories)}  answers={len(rows)}")
            continue
        print("=" * 78)
        print(f"{question.question_id}  [{question.tier.value}]")
        print(f"Q: {question.text.get('en')}")
        if question.category_guidance is not None:
            print(f"guidance: {question.category_guidance.text}")
        for group in sorted({a.group_id for a in rows}):
            side = [a for a in rows if a.group_id == group]
            counts: dict[str, list[ClusterAnswer]] = {}
            for a in side:
                counts.setdefault(a.answer_category, []).append(a)
            print(f"\n--- side {group}: {len(side)} addressed answers, {len(counts)} categories")
            for category, members in sorted(counts.items(), key=lambda kv: (-len(kv[1]), kv[0])):
                marker = " (unclear — never merged)" if category == ANSWER_CATEGORY_UNCLEAR else ""
                print(f"\n  {category}  ×{len(members)}{marker}")
                for a in sorted(members, key=lambda x: x.answer_id):
                    summary = a.answer_summary.text if a.answer_summary else ""
                    print(f"    [{a.reporting_cluster_id}] {summary}")
                shown = 0
                for a in sorted(members, key=lambda x: x.answer_id):
                    for sid in a.evidence[:1]:
                        text = sentences.get(sid)
                        if text:
                            print(f"    » {sid}: {text}")
                            shown += 1
                        break
                    if shown >= MAX_EVIDENCE_PER_CATEGORY:
                        break
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
