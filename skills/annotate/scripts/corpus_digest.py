#!/usr/bin/env python3
"""Print a bounded, deterministic digest of the active corpus, grouped by side.

For each reporting cluster this shows one representative member's title and the first
three sentences of its first two body paragraphs, plus source/date/origin metadata.  It
is the mandatory first read before proposing a topic's reader-tier questions.

    python scripts/corpus_digest.py topics <topic_id> [--group cn]

Exit codes: 0 ok · 2 invalid input or unrestorable corpus.
"""

from __future__ import annotations

import argparse
import sys

import _bootstrap  # noqa: F401

from newsab_schema.io import ArtifactError
from newsab_schema.paths import TopicPaths
from newsab_schema.store import load_corpus_run, load_run_articles


def _representative(members):
    """Prefer an original, then the earliest stable article in the cluster."""
    return sorted(
        members,
        key=lambda article: (
            article.origin.type.value != "original",
            article.publish_date,
            article.article_id,
        ),
    )[0]


def render_digest(run, articles, *, group: str | None = None) -> str:
    by_cluster = {}
    for article in articles:
        by_cluster.setdefault(article.reporting_cluster_id, []).append(article)

    selected = sorted(by_cluster)
    if group:
        selected = [cid for cid in selected if cid.startswith(f"RC-{group.upper()}-")]
    groups = sorted({cid.split("-")[1].lower() for cid in selected})
    lines = [f"corpus_run: {run.run_id}", f"clusters: {len(selected)}", ""]
    for group_id in groups:
        lines.extend((f"# {group_id}", ""))
        for cluster_id in [c for c in selected if c.split("-")[1].lower() == group_id]:
            members = by_cluster[cluster_id]
            article = _representative(members)
            member_meta = "; ".join(
                f"{a.article_id}/{a.source_id}/{a.publish_date}/{a.origin.type.value}"
                for a in sorted(members, key=lambda item: item.article_id)
            )
            lines.append(f"## {cluster_id} ({len(members)} article(s))")
            lines.append(
                f"source: {article.source_id} | date: {article.publish_date} | "
                f"origin.type: {article.origin.type.value}"
            )
            lines.append(f"title: {article.title}")
            for paragraph in article.structured_text[1:3]:
                text = " ".join(sentence.text for sentence in paragraph.sentences[:3])
                lines.append(f"P{paragraph.index:02d}: {text}")
            lines.append(f"members: {member_meta}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("topics_root")
    parser.add_argument("topic_id")
    parser.add_argument("--group", help="lower-case group_id, e.g. cn / us / id")
    args = parser.parse_args(argv)

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    try:
        run = load_corpus_run(paths)
        articles = load_run_articles(paths)
    except (ArtifactError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    available = {a.reporting_cluster_id.split("-")[1].lower() for a in articles}
    if args.group and args.group not in available:
        print(
            f"unknown group {args.group!r}; active corpus groups: {sorted(available)}",
            file=sys.stderr,
        )
        return 2
    print(render_digest(run, articles, group=args.group), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
