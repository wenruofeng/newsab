"""``registry set-channel``: accumulated channel knowledge must survive the next worker.

A pub-repo worker once overwrote an outlet's body-selector and subdomain-trap notes with
its own single measurement (caught and restored in the same round, 2026-09-01).  The
huanqiu entry holds seven measured facts in one string; replacement semantics made every
``--fetch-notes`` a potential wipe, so appending is now the default and replacement is a
separate deliberate flag.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from newsab_corpus.registry_cli import build_registry_parser


ENTRY = {
    "beat_scope": "general",
    "category": "serious",
    "channel": {
        "checked_at": "2026-08-19",
        "fetch_notes": "Body sits in <textarea class=\"article-content\">; s.huanqiu.com is 403.",
        "origin_field": None,
        "rate_limit": None,
        "search_channel": None,
        "status": "discovery_blocked",
    },
    "country": "CN",
    "id": "globaltimes_cn",
    "lang": "zh-CN",
    "name": {"values": {"en": "Global Times (Chinese)", "zh-CN": "环球网"}},
    "notes": {"values": {"en": "Fixture entry.", "zh-CN": "测试用条目。"}},
    "url": "https://www.huanqiu.com/",
}


def _registry(tmp_path: Path) -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "registry_version": "0.3.0",
                "updated_at": "2026-08-19T00:00:00+00:00",
                "sources": [ENTRY],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


def _run(path: Path, *extra: str) -> None:
    parser = argparse.ArgumentParser()
    build_registry_parser(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(
        ["registry", "set-channel", "globaltimes_cn", "--registry", str(path), *extra]
    )
    assert args.func(args) == 0


def _notes(path: Path) -> str:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc["sources"][0]["channel"]["fetch_notes"]


def test_fetch_notes_append_and_keep_what_the_last_worker_measured(tmp_path):
    path = _registry(tmp_path)
    _run(
        path,
        "--fetch-notes",
        "DDG site: index is stale here; add dated phrasing.",
        "--checked-at",
        "2026-09-01",
    )
    notes = _notes(path)
    assert "article-content" in notes and "403" in notes  # the old facts survive
    assert "[2026-09-01] DDG site: index is stale here" in notes


def test_replace_fetch_notes_is_a_separate_deliberate_flag(tmp_path):
    path = _registry(tmp_path)
    _run(
        path,
        "--fetch-notes",
        "Re-measured from scratch.",
        "--replace-fetch-notes",
        "--checked-at",
        "2026-09-01",
    )
    assert _notes(path) == "Re-measured from scratch."


def test_omitting_fetch_notes_still_preserves_them(tmp_path):
    path = _registry(tmp_path)
    _run(path, "--status", "ok", "--checked-at", "2026-09-01")
    notes = _notes(path)
    assert "article-content" in notes and "[2026-09-01]" not in notes
