#!/usr/bin/env python3
"""Validate the collect-stage topics_raised artifact and print its side difference.

    python scripts/check_topics_raised.py topics <topic_id> \
      topics/<topic_id>/corpus/topics_raised.jsonl

Every staged article needs one record with 3–6 extractive source phrases and English-pivot
forms. Source phrases must occur verbatim in that staging file. When an active corpus run
exists, pivot tallies count reporting clusters rather than publication instances, and a
staging file whose article that run withdrew needs no record.

Exit codes: 0 clean · 1 validation errors · 2 unreadable inputs.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

import _bootstrap  # noqa: F401

from newsab_schema.ids import make_article_id
from newsab_schema.io import ArtifactError, read_yaml
from newsab_schema.models.corpus import TopicManifest
from newsab_schema.paths import TopicPaths
from newsab_schema.store import load_corpus_run

RECORD_KEYS = {"staging_file", "topics_raised", "provenance"}
TOPIC_KEYS = {"source_phrase", "pivot_en"}
PROVENANCE_KEYS = {"skill_version", "model_id", "run_id", "timestamp"}


def _load_records(path: Path) -> list[tuple[int, dict]]:
    records = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{lineno}: record must be an object")
        records.append((lineno, payload))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("topics_root")
    parser.add_argument("topic_id")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--articles", nargs="+", metavar="STAGING_FILE",
                        help="check coverage for these staging filenames only — for an "
                             "extension of a corpus that predates topics_raised, name the "
                             "newly staged files; full coverage stays the default")
    args = parser.parse_args(argv)

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    staging_dir = paths.corpus_dir / "staging"
    try:
        manifest = read_yaml(paths.topic_manifest, TopicManifest)
        records = _load_records(args.artifact)
        staging = {
            path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
            for path in sorted(staging_dir.glob("*.yaml"))
            if path.name != "EXAMPLE.yaml.template"
        }
    except (ArtifactError, OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    errors = []
    seen = set()
    valid_topics = defaultdict(list)
    for lineno, record in records:
        where = f"{args.artifact}:{lineno}"
        if set(record) != RECORD_KEYS:
            errors.append(f"{where}: keys must be exactly {sorted(RECORD_KEYS)}")
            continue
        filename = record.get("staging_file")
        if filename in seen:
            errors.append(f"{where}: duplicate staging_file {filename!r}")
            continue
        seen.add(filename)
        source = staging.get(filename)
        if source is None:
            errors.append(f"{where}: no staging article named {filename!r}")
            continue
        provenance = record.get("provenance")
        if not isinstance(provenance, dict) or set(provenance) != PROVENANCE_KEYS:
            errors.append(f"{where}: provenance keys must be exactly {sorted(PROVENANCE_KEYS)}")
        elif any(not provenance.get(key) for key in PROVENANCE_KEYS):
            errors.append(f"{where}: provenance values must all be non-empty")
        topics = record.get("topics_raised")
        if not isinstance(topics, list) or not 3 <= len(topics) <= 6:
            errors.append(f"{where}: topics_raised must contain 3–6 items")
            continue
        searchable = "\n".join(
            str(source.get(field) or "") for field in ("title", "subtitle", "body")
        )
        for index, topic in enumerate(topics, 1):
            item = f"{where}:topics_raised[{index}]"
            if not isinstance(topic, dict) or set(topic) != TOPIC_KEYS:
                errors.append(f"{item}: keys must be exactly {sorted(TOPIC_KEYS)}")
                continue
            phrase = topic.get("source_phrase")
            pivot = topic.get("pivot_en")
            if not isinstance(phrase, str) or not phrase.strip():
                errors.append(f"{item}: source_phrase must be non-empty text")
            elif phrase not in searchable:
                errors.append(f"{item}: source_phrase is not verbatim in {filename}")
            if not isinstance(pivot, str) or not pivot.strip():
                errors.append(f"{item}: pivot_en must be non-empty text")
            if isinstance(phrase, str) and phrase in searchable and isinstance(pivot, str) and pivot:
                valid_topics[filename].append(pivot.strip())

    groups = [group.group_id for group in manifest.groups]
    group_prefix = {group.group_id: group.prefix.upper() for group in manifest.groups}
    cluster_by_article = {}
    withdrawn_ids: set[str] = set()
    try:
        run = load_corpus_run(paths)
        cluster_by_article = {member.article_id: member.reporting_cluster_id for member in run.articles}
        withdrawn_ids = {entry.article_id for entry in run.withdrawn}
    except (ArtifactError, ValueError):
        run = None

    # A staging file whose article the active run withdrew is out of the sample: it feeds no
    # denominator and no tally, so requiring an agenda record for it would contradict the
    # membership check below, which rejects any non-member article.
    article_id_of = {}
    withdrawn_files = set()
    for filename, source in staging.items():
        prefix = group_prefix.get(source.get("group_id"))
        if prefix is None:
            continue
        article_id_of[filename] = make_article_id(prefix, source["url"])
        if article_id_of[filename] in withdrawn_ids:
            withdrawn_files.add(filename)

    required = (set(staging) if args.articles is None else set(args.articles) & set(staging))
    required -= withdrawn_files
    if args.articles is not None:
        unknown = sorted(set(args.articles) - set(staging))
        if unknown:
            errors.append(f"--articles names files not in staging: {', '.join(unknown)}")
    missing = sorted(required - seen)
    if missing:
        errors.append(f"missing records for staging articles: {', '.join(missing)}")
    if errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 1

    tallies = {group_id: defaultdict(set) for group_id in groups}
    unresolved = []
    for filename, pivots in valid_topics.items():
        source = staging[filename]
        group_id = source.get("group_id")
        if group_id not in tallies:
            print(f"ERROR {filename}: unknown group_id {group_id!r}", file=sys.stderr)
            return 1
        unit = filename
        if run is not None:
            article_id = article_id_of[filename]
            if article_id in withdrawn_ids:
                continue
            unit = cluster_by_article.get(article_id)
            if unit is None:
                unresolved.append(f"{filename} -> {article_id}")
                continue
        for pivot in pivots:
            tallies[group_id][pivot].add(unit)

    if unresolved:
        print(
            "ERROR staged articles are not members of the active corpus run: "
            + ", ".join(unresolved),
            file=sys.stderr,
        )
        return 1
    print(f"OK {len(records)} article record(s); tally unit: {'cluster' if run else 'article'}")

    # Per-side denominators, so the table can be read as rates.  Raw counts invert whenever
    # the two sides differ in size — 1-vs-5 on a 12-vs-42 corpus is 8% vs 12%, no gap at all
    # — and every consumer of this table is looking for exactly that kind of asymmetry.
    # Derived from the run's own membership via the article-id prefix, never from staging:
    # the denominator is every cluster the side actually has, including any whose staging
    # file is absent.
    group_of_prefix = {prefix: group_id for group_id, prefix in group_prefix.items()}
    if run is not None:
        by_side: dict[str, set[str]] = {group_id: set() for group_id in groups}
        for member in run.articles:
            side = group_of_prefix.get(member.article_id.split("_")[0].upper())
            if side is not None:
                by_side[side].add(member.reporting_cluster_id)
        denominators = {group_id: len(by_side[group_id]) for group_id in groups}
    else:
        denominators = {
            group_id: sum(
                1 for filename, source in staging.items()
                if source.get("group_id") == group_id and filename not in withdrawn_files
            )
            for group_id in groups
        }

    all_pivots = sorted({pivot for side in tallies.values() for pivot in side})
    print("denominator\t" + "\t".join(str(denominators[g]) for g in groups))
    print("pivot_en\t" + "\t".join(groups) + "\t" + "\t".join(f"{g}%" for g in groups))
    for pivot in all_pivots:
        counts = [len(tallies[g][pivot]) for g in groups]
        rates = [
            f"{(n / denominators[g] * 100):.0f}%" if denominators[g] else "n/a"
            for n, g in zip(counts, groups)
        ]
        print(pivot + "\t" + "\t".join(str(n) for n in counts) + "\t" + "\t".join(rates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
