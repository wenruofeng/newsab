"""Preview collection — derived from run directories, the manifest and the active selector."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from newsab_editorial.previews import collect_topics

TOPIC = "aabb-river-light-2026"
NEW = "edt-20260822165042332476-5f3fab4b"
OLD = "edt-20260821074110902552-72768fbe"
DEAD = "edt-20260822163232416356-28a4d94f"


def build_tree(tmp_path: Path) -> Path:
    topics = tmp_path / "topics"
    topic = topics / TOPIC
    (topic / "manifest").mkdir(parents=True)
    (topic / "topic_manifest.yaml").write_text(
        'topic_id: aabb-river-light-2026\nreview_locale: zh-CN\ntitle:\n  values:\n'
        '    en: "US student visas"\n    zh-CN: "美国对中国留学生签证收紧"\n',
        encoding="utf-8",
    )
    lines = [
        {"run_id": OLD, "stage": "editorial", "status": "completed",
         "model_id": "claude-opus-5", "timestamp": "2026-08-21T07:41:25Z"},
        {"run_id": DEAD, "stage": "editorial", "status": "stopped",
         "model_id": "claude-sonnet-5", "timestamp": "2026-08-22T23:43:03Z"},
        {"run_id": NEW, "stage": "editorial", "status": "completed",
         "model_id": "claude-sonnet-5", "timestamp": "2026-08-22T23:53:54Z"},
    ]
    (topic / "manifest" / "manifest.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )
    # The selector deliberately points at the older run: "active" is routing, not recency.
    (topic / "manifest" / "active.json").write_text(
        json.dumps({"editorial": OLD}), encoding="utf-8"
    )
    for run_id, langs in ((NEW, ("zh-CN", "en")), (OLD, ("zh-CN", "en")), (DEAD, ("en",))):
        run_dir = topic / "editorial" / "versions" / run_id
        run_dir.mkdir(parents=True)
        for lang in langs:
            (run_dir / f"preview.{lang}.html").write_text(f"<html>{run_id} {lang}", encoding="utf-8")
    (topic / "editorial" / "versions" / NEW / "page.json").write_text(
        json.dumps({"title": {"values": {"zh-CN": "签证新规", "en": "Visa rule"}},
                    "angles": [1, 2, 3, 4, 5]}),
        encoding="utf-8",
    )
    legacy = topic / "qa"
    legacy.mkdir()
    legacy_file = legacy / "preview.html"
    legacy_file.write_text("<html>legacy", encoding="utf-8")
    # Pin the mtime: with no manifest line this file dates itself, and a fixture written
    # "just now" would otherwise sort ahead of every dated run.
    stamp = datetime(2026, 8, 19, tzinfo=timezone.utc).timestamp()
    os.utime(legacy_file, (stamp, stamp))
    return topics


def test_runs_are_newest_first_and_active_follows_the_selector(tmp_path):
    topics_root = build_tree(tmp_path)
    (collected,) = collect_topics(topics_root)

    assert collected.title == "美国对中国留学生签证收紧"
    assert [run.run_id for run in collected.runs][:3] == [NEW, DEAD, OLD]
    assert [run.active for run in collected.runs] == [False, False, True, False]
    assert collected.runs[0].angle_count == 5
    assert collected.runs[0].page_title == "签证新规"
    assert collected.runs[1].status == "stopped"


def test_the_index_speaks_the_language_this_topic_is_reviewed_in(tmp_path):
    """Which language the index shows is the manifest's ``review_locale``.

    The same tree read for a reviewer who signs in English shows the English title —
    nothing about this listing may assume one operator's language.  Absent the field,
    the English pivot is the fallback, never a guess at who is reading.
    """
    topics_root = build_tree(tmp_path)
    manifest = topics_root / TOPIC / "topic_manifest.yaml"

    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("review_locale: zh-CN", "review_locale: en"),
        encoding="utf-8",
    )
    (collected,) = collect_topics(topics_root)
    assert collected.title == "US student visas"
    assert collected.runs[0].page_title == "Visa rule"

    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("review_locale: en\n", ""),
        encoding="utf-8",
    )
    (collected,) = collect_topics(topics_root)
    assert collected.title == "US student visas"


def test_legacy_unversioned_preview_still_gets_a_row(tmp_path):
    topics_root = build_tree(tmp_path)
    (collected,) = collect_topics(topics_root)

    legacy = collected.runs[-1]
    assert legacy.run_id is None and legacy.dir_label == "qa"
    # No manifest line to date it, so the file's own mtime stands in — and says so.
    assert legacy.when_is_exact is False


def test_collection_survives_a_manifest_line_that_no_longer_parses(tmp_path):
    topics_root = build_tree(tmp_path)
    manifest = topics_root / TOPIC / "manifest" / "manifest.jsonl"
    manifest.write_text("{not json at all\n" + manifest.read_text(encoding="utf-8"), encoding="utf-8")

    (collected,) = collect_topics(topics_root)
    assert collected.runs[0].run_id == NEW


def test_topic_without_a_preview_is_absent(tmp_path):
    topics_root = build_tree(tmp_path)
    empty = topics_root / "aabb-garden-wind-2026"
    empty.mkdir()
    (empty / "topic_manifest.yaml").write_text("topic_id: aabb-garden-wind-2026\n", encoding="utf-8")

    assert [t.topic_id for t in collect_topics(topics_root)] == [TOPIC]
