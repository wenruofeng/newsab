#!/usr/bin/env python3
"""Print everything a collect run needs to know before its first query.

Scope status and approval-hash check, groups with their definitions, period, targets,
current corpus/staging/log state, and the registry slice's channel coverage — so a fresh
agent starts from facts instead of re-deriving them from the tree.

    python skills/collect/scripts/preflight.py <topics_root> <topic_id>

Exit codes: 0 ready · 1 not ready to collect (reason printed) · 2 inputs missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import _bootstrap  # noqa: F401

from newsab_schema.io import read_yaml
from newsab_schema.models.corpus import TopicManifest
from newsab_schema.paths import TopicPaths, source_registry_path
from newsab_schema.store import load_registry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topics_root")
    ap.add_argument("topic_id")
    args = ap.parse_args(argv)

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    if not paths.topic_manifest.exists():
        print(f"no topic manifest: {paths.topic_manifest}", file=sys.stderr)
        return 2
    manifest = read_yaml(paths.topic_manifest, TopicManifest)

    ready = True
    print(f"topic     {manifest.topic_id} — {manifest.title.get('en') or ''}")
    print(f"status    {manifest.status.value}")
    if manifest.scope_approval is None:
        print("approval  MISSING — collection may not start before touchpoint #1")
        ready = False
    else:
        current = manifest.scope_hash()
        ok = current == manifest.scope_approval.scope_hash
        print(f"approval  {manifest.scope_approval.approved_by} @ "
              f"{manifest.scope_approval.approved_at:%Y-%m-%d} — "
              f"hash {'matches' if ok else 'STALE (scope edited since approval)'}")
        ready = ready and ok
    print(f"period    {manifest.period.start} .. {manifest.period.end or 'open'} (hard filter)")
    if manifest.cluster_threshold is not None:
        print(f"cluster_threshold {manifest.cluster_threshold} (topic override)")
    for g in manifest.groups:
        target = manifest.target_clusters_per_group.get(g.group_id)
        silence = "  [expected_silence]" if g.group_id in manifest.expected_silence else ""
        print(f"group {g.group_id} ({g.prefix})  target={target}{silence}")
        print(f"  definition: {g.definition.get('en') or next(iter(g.definition.values.values()))}")

    log_path = paths.collection_log
    if log_path.exists():
        kinds = Counter(json.loads(line)["kind"]
                        for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip())
        print(f"log       {sum(kinds.values())} entries: "
              + ", ".join(f"{k}={n}" for k, n in sorted(kinds.items())))
    else:
        print("log       none yet")
    staging = sorted(paths.corpus_dir.glob("staging/*.yaml"))
    print(f"staging   {len(staging)} file(s)")
    store = paths.corpus_dir / "articles"
    print(f"store     {len(list(store.glob('*.json'))) if store.exists() else 0} article(s)")
    runs = sorted((paths.corpus_dir / "versions").glob("*/")) if (paths.corpus_dir / "versions").exists() else []
    print(f"runs      {len(runs)} corpus run(s)")

    registry = load_registry(source_registry_path(args.topics_root))
    with_channel = [s for s in registry.sources if s.channel and s.channel.search_channel]
    print(f"registry  {len(registry.sources)} outlet(s), {len(with_channel)} with a search channel — "
          f"query your slice: python -m newsab_corpus registry find --country <CC> --lang <lang>")

    print("ready" if ready else "NOT READY")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
