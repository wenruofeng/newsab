#!/usr/bin/env python3
"""Search the active corpus with side-native term variants and keep the probe audit log.

A search is one conceptual probe, expressed in every side's own vocabulary.  The script
refuses a one-sided query because translating one side's term literally is the easiest
way to manufacture a false agenda gap.

    python scripts/corpus_probe.py search topics <topic_id> \
      --term cn=本土词形 --term id='istilah lokal' --log probe_log.jsonl
    python scripts/corpus_probe.py read topics <topic_id> RC-CN-... \
      --log probe_log.jsonl

The log enforces at most 10 searches and at most 5 distinct full-cluster reads per active
corpus run. Exit codes: 0 ok · 2 invalid input/budget/artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap  # noqa: F401

from newsab_schema.io import ArtifactError, read_yaml
from newsab_schema.models.corpus import TopicManifest
from newsab_schema.paths import TopicPaths
from newsab_schema.store import load_corpus_run, load_run_articles

MAX_SEARCHES = 10
MAX_FULL_CLUSTER_READS = 5


def _read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
    return records


def _append_log(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _parse_terms(raw_terms: list[str], required_groups: list[str]) -> dict[str, str]:
    terms = {}
    for raw in raw_terms:
        if "=" not in raw:
            raise ValueError(f"--term must be GROUP=TEXT, got {raw!r}")
        group_id, term = raw.split("=", 1)
        group_id, term = group_id.strip(), term.strip()
        if group_id in terms:
            raise ValueError(f"duplicate --term for group {group_id!r}")
        if not term:
            raise ValueError(f"empty term for group {group_id!r}")
        terms[group_id] = term
    missing = sorted(set(required_groups) - set(terms))
    extra = sorted(set(terms) - set(required_groups))
    if missing or extra:
        raise ValueError(
            "every probe needs exactly one native term per side; "
            f"missing={missing}, unknown={extra}, expected={required_groups}"
        )
    return terms


def _clusters(articles):
    out = {}
    for article in articles:
        out.setdefault(article.reporting_cluster_id, []).append(article)
    return out


def _print_cluster(cluster_id: str, members) -> None:
    print(f"=== {cluster_id}")
    for article in sorted(members, key=lambda item: item.article_id):
        print(
            f"--- {article.article_id} | {article.source_id} | {article.publish_date} | "
            f"{article.origin.type.value} | {article.url}"
        )
        for paragraph in article.structured_text:
            for sentence in paragraph.sentences:
                anchor = f"{article.article_id}:P{paragraph.index:02d}:S{sentence.index:02d}"
                print(f"{anchor}\t{sentence.text}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    search = sub.add_parser("search", help="run and log one side-native corpus probe")
    read = sub.add_parser("read", help="print and log one or more full clusters")
    for command in (search, read):
        command.add_argument("topics_root")
        command.add_argument("topic_id")
        command.add_argument("--log", required=True, type=Path)
    search.add_argument("--term", action="append", required=True, dest="terms")
    read.add_argument("cluster_ids", nargs="+")
    args = parser.parse_args(argv)

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    try:
        manifest = read_yaml(paths.topic_manifest, TopicManifest)
        run = load_corpus_run(paths)
        articles = load_run_articles(paths)
        records = _read_log(args.log)
    except (ArtifactError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    active_records = [r for r in records if r.get("corpus_run_id") == run.run_id]
    clusters = _clusters(articles)
    now = datetime.now(timezone.utc).isoformat()

    if args.command == "search":
        prior = sum(r.get("kind") == "probe" for r in active_records)
        if prior >= MAX_SEARCHES:
            print(
                f"probe budget exhausted: {prior}/{MAX_SEARCHES} searches for {run.run_id}",
                file=sys.stderr,
            )
            return 2
        try:
            terms = _parse_terms(args.terms, [g.group_id for g in manifest.groups])
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        hits = {group_id: {} for group_id in terms}
        for article in articles:
            group_id = article.reporting_cluster_id.split("-")[1].lower()
            term = terms.get(group_id)
            if term is None:
                continue
            needle = term.casefold()
            for paragraph in article.structured_text:
                for sentence in paragraph.sentences:
                    if needle not in sentence.text.casefold():
                        continue
                    anchor = f"{article.article_id}:P{paragraph.index:02d}:S{sentence.index:02d}"
                    hits[group_id].setdefault(article.reporting_cluster_id, []).append(
                        (anchor, sentence.text)
                    )

        print(f"probe {prior + 1}/{MAX_SEARCHES} | corpus_run {run.run_id}")
        for group_id in terms:
            group_hits = hits[group_id]
            print(
                f"# {group_id}: term={terms[group_id]!r} | "
                f"matched_clusters={len(group_hits)}"
            )
            for cluster_id in sorted(group_hits):
                print(f"## {cluster_id}")
                for anchor, sentence in group_hits[cluster_id]:
                    print(f"{anchor}\t{sentence}")
        _append_log(
            args.log,
            {
                "kind": "probe",
                "topic_id": args.topic_id,
                "corpus_run_id": run.run_id,
                "terms": terms,
                "matched_clusters": {
                    group_id: sorted(group_hits) for group_id, group_hits in hits.items()
                },
                "timestamp": now,
            },
        )
        return 0

    missing = [cluster_id for cluster_id in args.cluster_ids if cluster_id not in clusters]
    if missing:
        print(f"not clusters of active corpus run: {missing}", file=sys.stderr)
        return 2
    already = {
        cluster_id
        for record in active_records
        if record.get("kind") == "full_cluster"
        for cluster_id in record.get("cluster_ids", [])
    }
    requested = set(args.cluster_ids)
    if len(already | requested) > MAX_FULL_CLUSTER_READS:
        print(
            f"full-read budget would be {len(already | requested)}/"
            f"{MAX_FULL_CLUSTER_READS} clusters for {run.run_id}",
            file=sys.stderr,
        )
        return 2
    for cluster_id in args.cluster_ids:
        _print_cluster(cluster_id, clusters[cluster_id])
    _append_log(
        args.log,
        {
            "kind": "full_cluster",
            "topic_id": args.topic_id,
            "corpus_run_id": run.run_id,
            "cluster_ids": args.cluster_ids,
            "timestamp": now,
        },
    )
    print(
        f"full-cluster reads: {len(already | requested)}/{MAX_FULL_CLUSTER_READS}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
