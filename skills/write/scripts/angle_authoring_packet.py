#!/usr/bin/env python3
"""Build the evidence-first writing view for a ReaderPage's angle prose.

The page does not display an angle paragraph by itself. It displays a reader question,
two answer cards and their relation, then one explanation under each card (or one joint
explanation). This packet preserves that order and follows it with every counted report
behind each badge, including the annotation summary and all verbatim anchors.

It is deliberately a writing input, not a generated draft: deterministic code can expose
the evidence universe and the rendered frame, but only the write stage may synthesize the
shared causal or evidentiary route.

    python skills/write/scripts/angle_authoring_packet.py topics <topic_id> \
        --page <page.json> --qa-run topics/<topic_id>/analysis/<qa-run-id> \
        -o /tmp/angle_authoring_packet.md
"""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401

from newsab_editorial.evidence import AnswerIndex, SentenceIndex, counted_clusters
from newsab_editorial.page_checks import load_analysis_run, load_excluded_clusters
from newsab_schema.io import read_jsonl, read_yaml
from newsab_schema.models.corpus import TopicManifest
from newsab_schema.models.page import ReaderPage
from newsab_schema.models.qa import ClusterAnswer
from newsab_schema.paths import TopicPaths
from newsab_schema.readability import readable_clusters_of_articles
from newsab_schema.store import load_run_articles


def _multi(value, lang: str = "en") -> str:
    if value is None:
        return ""
    if hasattr(value, "get"):
        return value.get(lang) or value.get("en") or ""
    return str(value)


def _lang(value) -> str:
    return value.text if value is not None else ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("topics_root")
    ap.add_argument("topic_id")
    ap.add_argument("--page", required=True)
    ap.add_argument("--qa-run", required=True)
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args(argv)

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    page = ReaderPage.model_validate_json(Path(args.page).read_text(encoding="utf-8"))
    manifest = read_yaml(paths.topic_manifest, TopicManifest)
    articles = load_run_articles(paths)
    sentence_index = SentenceIndex(articles)
    # qa-0.5.0 counts only readable clusters, so the packet's evidence universe has to
    # be the same one the badge and page-check use (newsab_schema.readability).
    readable = readable_clusters_of_articles(articles)
    finding_rows, _ = load_analysis_run(Path(args.qa_run))
    findings = {finding.finding_id: finding for finding in finding_rows}
    answers = AnswerIndex(
        read_jsonl(paths.answers, ClusterAnswer),
        excluded_clusters=load_excluded_clusters(Path(args.qa_run)),
    )
    side_names = {group.group_id: _multi(group.short_label) for group in manifest.groups}

    out: list[str] = [
        f"# Angle authoring packet — {args.topic_id}",
        "",
        "Read each frame in this exact visible order: **Q → answer cards + relation → "
        "explanations**. The card already answers what; prose supplies why. On desktop, "
        "the two explanations are parallel columns directly under the cards.",
        "",
    ]

    for angle in page.angles:
        question = _multi(page.lexicon.questions.get(angle.question_id)) or _multi(
            angle.question_display
        )
        finding = findings.get(angle.finding_id)
        if finding is None:
            raise SystemExit(f"{angle.finding_id} is not present in {args.qa_run}")
        out.extend(
            [
                f"## Angle {angle.rank}: Q: {question}",
                "",
                f"Relation: **{angle.kind.value}** · strength: **{finding.strength.value}**",
                "",
            ]
        )
        if angle.shared_answer_label is not None:
            out.append(f"Shared card label: **{_multi(angle.shared_answer_label)}**")
            out.append("")

        per_question = answers.for_question(angle.question_id)
        for side in angle.sides:
            side_name = side_names.get(side.group_id, side.group_id)
            label = _multi(side.answer_label) or _multi(angle.shared_answer_label)
            out.extend(
                [
                    f"### Visible frame — {side_name} (`{side.group_id}`)",
                    "",
                    f"- card label: **{label or '[near-silence rendered by code]'}**",
                    f"- badge: **{side.badge.numerator}/{side.badge.denominator}**",
                    f"- current explanation: {_multi(side.answer.text)}",
                    "",
                    "#### Counted reports behind this card",
                    "",
                ]
            )
            if side.is_silent_side:
                clusters = sorted(
                    cluster_id
                    for cluster_id, answer in answers.for_group(
                        angle.question_id, side.group_id
                    ).items()
                    if answer.addressed and cluster_id in readable
                )
            else:
                clusters = counted_clusters(
                    side, angle, finding, answers, readable=readable
                )
                if len(clusters) != side.badge.numerator:
                    raise SystemExit(
                        f"angle {angle.rank} {side.group_id}: badge numerator "
                        f"{side.badge.numerator} != {len(clusters)} counted clusters"
                    )

            if not clusters:
                out.append("- No addressed report in the pinned sample.")
                out.append("")
                continue

            for cluster_id in clusters:
                answer = per_question.get(cluster_id)
                if answer is None:
                    raise SystemExit(
                        f"angle {angle.rank}: counted cluster {cluster_id} has no answer"
                    )
                out.append(
                    f"- `{cluster_id}` · category `{answer.answer_category}` · "
                    f"summary: {_lang(answer.answer_summary)}"
                )
                if answer.notes is not None:
                    out.append(f"  - annotation note: {_lang(answer.notes)}")
                for sentence_id in answer.evidence:
                    card = sentence_index.card(sentence_id)
                    if card is None:
                        raise SystemExit(f"anchor does not resolve: {sentence_id}")
                    out.append(
                        f"  - `{sentence_id}` ({card.source_name}, {card.publish_date}, "
                        f"{card.lang}): {card.text}"
                    )
            out.append("")

        if angle.commentary_joint is not None:
            out.extend(
                [
                    "### Current joint explanation",
                    "",
                    _multi(angle.commentary_joint.text),
                    "",
                ]
            )

    body = "\n".join(out).rstrip() + "\n"
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    print(f"written {target} ({len(body):,} chars, {len(page.angles)} angles)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
