#!/usr/bin/env python3
"""Print reporting clusters the way the annotate stage reads them.

The Q×A annotation unit is one reporting cluster (all publication instances of one piece
of independent reporting), so this prints a whole cluster at a time: every member
article, every sentence, each with its anchor already attached.  Anchors are copied from
this output, never reconstructed by hand — hand-built anchors are how traceability
drifts (non-negotiable 2).

    python scripts/show_cluster.py topics <topic_id> --list [--group cn]
    python scripts/show_cluster.py topics <topic_id> RC-CN-02cf559b [RC-US-060eade0 ...]
    python scripts/show_cluster.py topics <topic_id> --group cn --index 3

Exit codes: 0 ok · 2 inputs missing.
"""

from __future__ import annotations

import argparse
import sys

import _bootstrap  # noqa: F401

from newsab_schema.io import ArtifactError
from newsab_schema.paths import TopicPaths
from newsab_schema.store import load_corpus_run, load_run_articles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("topics_root")
    parser.add_argument("topic_id")
    parser.add_argument("cluster_ids", nargs="*")
    parser.add_argument("--group", help="lower-case group_id, e.g. us / cn / id")
    parser.add_argument("--list", action="store_true", help="one line per cluster, no text")
    parser.add_argument(
        "--index",
        type=int,
        default=None,
        help="print the Nth cluster (1-based) of --group's sorted cluster list",
    )
    args = parser.parse_args(argv)

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    try:
        run = load_corpus_run(paths)
        articles = load_run_articles(paths)
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    by_id = {a.article_id: a for a in articles}
    clusters: dict[str, list[str]] = {}
    for member in run.articles:
        clusters.setdefault(member.reporting_cluster_id, []).append(member.article_id)

    selected = sorted(clusters)
    if args.group:
        prefix = f"RC-{args.group.upper()}-"
        selected = [c for c in selected if c.startswith(prefix)]
    if args.cluster_ids:
        missing = [c for c in args.cluster_ids if c not in clusters]
        if missing:
            print(f"not clusters of the active corpus run: {missing}", file=sys.stderr)
            return 2
        selected = list(args.cluster_ids)
    if args.index is not None:
        if not 1 <= args.index <= len(selected):
            print(f"--index {args.index} out of range 1..{len(selected)}", file=sys.stderr)
            return 2
        selected = [selected[args.index - 1]]

    for cluster_id in selected:
        members = sorted(clusters[cluster_id], key=lambda aid: by_id[aid].publish_date)
        head = ", ".join(
            f"{aid} ({by_id[aid].source_id}, {by_id[aid].publish_date}, "
            f"{by_id[aid].origin.type.value})"
            for aid in members
        )
        print(f"=== {cluster_id}  members={len(members)}: {head}")
        if args.list:
            continue
        for aid in members:
            article = by_id[aid]
            print(f"--- {aid}  lang={article.lang}  url={article.url}")
            for paragraph in article.structured_text:
                for sentence in paragraph.sentences:
                    sid = f"{aid}:P{paragraph.index:02d}:S{sentence.index:02d}"
                    print(f"{sid}\t{sentence.text}")
        print()
    if args.list:
        print(f"-- {len(selected)} cluster(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
