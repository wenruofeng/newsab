#!/usr/bin/env python3
"""Append one validated entry to a topic's collection log, at the moment it happens.

The log is the only artifact that answers "what would you have found if you had searched
differently?", so entries are written as they run, never reconstructed from memory. This
tool validates the line through the real schema (``extra="forbid"``) before appending —
a misspelled field fails here instead of at check time.

    python skills/collect/scripts/log_query.py <topics_root> <topic_id> query \
        --group cn --query "留学生 签证 新规" --term-variant policy_name_zh \
        --engine-or-site baidu_news --results-seen 8 --results-staged 2
    python skills/collect/scripts/log_query.py <topics_root> <topic_id> fetch_failure \
        --group cn --url https://… --layer browser --reason "405 on every path (ip block)"
    python skills/collect/scripts/log_query.py <topics_root> <topic_id> excluded \
        --group us --url https://… --reason "aggregator copy, publisher not resolvable"
    python skills/collect/scripts/log_query.py <topics_root> <topic_id> note \
        --group cn --note "thin side: ruled out wrong-round vocabulary, channel gap remains"
    python skills/collect/scripts/log_query.py <topics_root> <topic_id> source_added \
        --group cn --source-id smm_cn --found-via "baidu: 镍矿 出口"

A correction is a new line naming the superseded one via --corrects, never an edit.
``fetch_failure`` needs ``--layer browser``: an HTTP refusal is a transport artifact and
has to survive the Playwright retry before it is a failure (fetch-extract.md §1.3).
Exit codes: 0 appended · 1 invalid entry · 2 inputs missing.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import _bootstrap  # noqa: F401

from newsab_corpus.collection_log import CollectionLogEntry
from newsab_schema.paths import TopicPaths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topics_root")
    ap.add_argument("topic_id")
    ap.add_argument("kind", choices=["query", "fetch_failure", "excluded", "note", "source_added"])
    ap.add_argument("--group", required=True, dest="group_id")
    for flag in ["query", "lang", "engine-or-site", "term-variant", "url", "source-id",
                 "reason", "found-via", "snapshot-id", "corrects", "note",
                 "period-from", "period-to", "layer"]:
        ap.add_argument(f"--{flag}")
    ap.add_argument("--results-seen", type=int)
    ap.add_argument("--results-staged", type=int)
    args = ap.parse_args(argv)

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    if not paths.topic_manifest.exists():
        print(f"no topic manifest: {paths.topic_manifest}", file=sys.stderr)
        return 2

    payload = {k: v for k, v in vars(args).items()
               if k not in ("topics_root", "topic_id") and v is not None}
    payload["at"] = datetime.now(timezone.utc)
    try:
        entry = CollectionLogEntry.model_validate(payload)
    except Exception as exc:
        print(f"invalid entry: {exc}", file=sys.stderr)
        return 1

    paths.corpus_dir.mkdir(parents=True, exist_ok=True)
    with paths.collection_log.open("a", encoding="utf-8") as fh:
        fh.write(entry.model_dump_json(exclude_none=True) + "\n")
    print(f"appended {entry.kind} entry to {paths.collection_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
