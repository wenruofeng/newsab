"""Resolve the collect stage's reading notes onto the pinned corpus run's articles.

``corpus/topics_raised.jsonl`` is keyed by *staging file*, because that is what the
collect agent had in hand when it wrote the notes.  Everything downstream is keyed by
article id, so the join runs through the staging file's own ``group_id`` + ``url``, which
is exactly what minted the article id in the first place (``make_article_id``).

A topic whose corpus predates the artifact simply has no records; every consumer treats
that as "nothing to show" rather than as an error.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from stat import S_ISREG

import yaml

from newsab_schema.ids import make_article_id
from newsab_schema.io import load_yaml_text
from newsab_schema.paths import TopicPaths


def load_topics_by_article(paths: TopicPaths) -> dict[str, list[dict]]:
    """``article_id -> [{"pivot_en": …, "source_phrase": …}, …]``, or ``{}``."""
    source = paths.topics_raised
    if not source.is_file():
        return {}
    staging = paths.staging_dir
    out: dict[str, list[dict]] = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        article_id = _article_id(staging, record.get("staging_file") or "")
        if article_id is None:
            continue
        entries = [
            {
                "pivot_en": (item.get("pivot_en") or "").strip(),
                "source_phrase": (item.get("source_phrase") or "").strip(),
            }
            for item in record.get("topics_raised") or []
            if isinstance(item, dict)
        ]
        # Same article staged twice (a re-collect) keeps the later record: the file is
        # append-only and the last writer is the one that read the current bytes.
        if entries:
            out[article_id] = entries
    return out


def _article_id(staging: Path, staging_file: str) -> str | None:
    if not staging_file:
        return None
    path = staging / staging_file
    try:
        stat = path.stat()
    except OSError:
        return None
    if not S_ISREG(stat.st_mode):
        return None
    # A staged file is parsed whole just to read two head fields, and ``verify-site``
    # walks every publication of every topic — 7,191 parses of a few dozen distinct files
    # on this repo.  Key on the identity a re-collect would change so a rewritten
    # staging file is still re-read.
    return _article_id_cached(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=4096)
def _article_id_cached(path_str: str, mtime_ns: int, size: int) -> str | None:
    path = Path(path_str)
    try:
        head = load_yaml_text(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(head, dict):
        return None
    group_id, url = head.get("group_id"), head.get("url")
    if not group_id or not url:
        return None
    try:
        return make_article_id(str(group_id).upper(), str(url))
    except Exception:  # noqa: BLE001 - a malformed staging file is not a render failure
        return None
