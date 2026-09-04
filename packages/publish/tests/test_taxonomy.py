"""``adopt-taxonomy``: folding one approved ``TopicCategoryApproval`` into site metadata.

Pins the mechanical transcription this command replaces: the mapping and the approvals-list entry must
land together, the same adopt is idempotent on replay, and a *different* approval for an
already-mapped topic is refused rather than silently overwritten.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from newsab_publish.metadata import TopicCategoryApproval
from newsab_publish.taxonomy import adopt_taxonomy
from newsab_schema.common import LangText
from newsab_schema.io import ArtifactError
from newsab_schema.paths import SitePaths


DECIDED = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
NEW_TOPIC = "aabb-new-topic-2026"


def _approval(
    topic_id: str = NEW_TOPIC,
    category_ids: list[str] | None = None,
    *,
    decided_at: datetime = DECIDED,
) -> TopicCategoryApproval:
    return TopicCategoryApproval(
        approval_id=f"taxonomy-topic-{topic_id}-2026-09-03",
        topic_id=topic_id,
        reviewer_id="founder",
        decision="approved",
        decided_at=decided_at,
        category_ids=category_ids or ["civic-life", "environment"],
        note=LangText(text="测试审批。", lang="zh-CN"),
    )


def _write_metadata(tmp_path: Path, metadata) -> Path:
    path = tmp_path / "site_metadata.json"
    path.write_text(metadata.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def _write_approval(site_root: Path, approval: TopicCategoryApproval, hash8: str = "abcdef01") -> Path:
    approvals_dir = SitePaths.at(site_root).ensure().private_dir / "approvals"
    approvals_dir.mkdir(parents=True, exist_ok=True)
    target = approvals_dir / f"topic-categories-{approval.topic_id}-{hash8}.json"
    target.write_text(approval.model_dump_json() + "\n", encoding="utf-8")
    return target


def test_adopts_a_new_topic_and_writes_both_the_mapping_and_the_approval(
    tmp_path, metadata
):
    metadata_path = _write_metadata(tmp_path, metadata)
    site_root = tmp_path / "site"
    approval = _approval()
    approval_path = _write_approval(site_root, approval)

    result = adopt_taxonomy(site_root, NEW_TOPIC, metadata_path=metadata_path)

    assert result.status == "adopted"
    assert result.category_ids == ("civic-life", "environment")
    assert result.approval_path == approval_path

    on_disk = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert on_disk["topic_categories"][NEW_TOPIC] == ["civic-life", "environment"]
    approvals = [a for a in on_disk["topic_category_approvals"] if a["topic_id"] == NEW_TOPIC]
    assert len(approvals) == 1
    assert approvals[0]["approval_id"] == approval.approval_id
    # Every pre-existing mapping and approval survives untouched.
    for topic_id, cats in metadata.topic_categories.items():
        assert on_disk["topic_categories"][topic_id] == cats


def test_adopting_the_same_approval_twice_is_a_no_op(tmp_path, metadata):
    metadata_path = _write_metadata(tmp_path, metadata)
    site_root = tmp_path / "site"
    _write_approval(site_root, _approval())

    first = adopt_taxonomy(site_root, NEW_TOPIC, metadata_path=metadata_path)
    after_first = metadata_path.read_text(encoding="utf-8")
    second = adopt_taxonomy(site_root, NEW_TOPIC, metadata_path=metadata_path)

    assert first.status == "adopted"
    assert second.status == "already-adopted"
    # The file was not rewritten a second time.
    assert metadata_path.read_text(encoding="utf-8") == after_first


def test_a_different_approval_for_an_already_mapped_topic_is_refused(tmp_path, metadata):
    metadata_path = _write_metadata(tmp_path, metadata)
    site_root = tmp_path / "site"
    _write_approval(site_root, _approval())
    adopt_taxonomy(site_root, NEW_TOPIC, metadata_path=metadata_path)

    # A second, differently-worded decision for the same topic (as if re-reviewed under
    # a different page hash) must not silently replace the first.
    conflicting = _approval(category_ids=["civic-life"])
    conflicting_path = SitePaths.at(site_root).private_dir / "approvals" / (
        f"topic-categories-{NEW_TOPIC}-11223344.json"
    )
    conflicting_path.write_text(conflicting.model_dump_json() + "\n", encoding="utf-8")

    with pytest.raises(ArtifactError, match="already carries a different"):
        adopt_taxonomy(
            site_root, NEW_TOPIC, approval_path=conflicting_path, metadata_path=metadata_path
        )


def test_no_matching_approval_file_is_refused_with_the_search_path(tmp_path, metadata):
    metadata_path = _write_metadata(tmp_path, metadata)
    site_root = tmp_path / "site"
    with pytest.raises(ArtifactError, match="no topic-categories approval found"):
        adopt_taxonomy(site_root, NEW_TOPIC, metadata_path=metadata_path)


def test_more_than_one_matching_approval_requires_an_explicit_choice(tmp_path, metadata):
    metadata_path = _write_metadata(tmp_path, metadata)
    site_root = tmp_path / "site"
    _write_approval(site_root, _approval(), hash8="aaaaaaaa")
    _write_approval(site_root, _approval(), hash8="bbbbbbbb")

    with pytest.raises(ArtifactError, match="approvals found for"):
        adopt_taxonomy(site_root, NEW_TOPIC, metadata_path=metadata_path)


def test_explicit_approval_path_is_used_over_directory_search(tmp_path, metadata):
    metadata_path = _write_metadata(tmp_path, metadata)
    site_root = tmp_path / "site"
    # Two files on disk; the explicit --approval must win without even listing the dir.
    _write_approval(site_root, _approval(), hash8="aaaaaaaa")
    wanted = _write_approval(site_root, _approval(), hash8="bbbbbbbb")

    result = adopt_taxonomy(
        site_root, NEW_TOPIC, approval_path=wanted, metadata_path=metadata_path
    )
    assert result.status == "adopted"
    assert result.approval_path == wanted


def test_a_topic_already_covered_by_the_legacy_backfill_is_refused(tmp_path, metadata):
    # The fixture's `metadata` already names TOPICS[:4] in taxonomy_backfill_approval.
    backfilled_topic = metadata.taxonomy_backfill_approval.topic_ids[0]
    metadata_path = _write_metadata(tmp_path, metadata)
    site_root = tmp_path / "site"
    _write_approval(site_root, _approval(topic_id=backfilled_topic))

    with pytest.raises(ArtifactError, match="taxonomy backfill approval"):
        adopt_taxonomy(site_root, backfilled_topic, metadata_path=metadata_path)


def test_an_approval_file_naming_a_different_topic_than_asked_is_refused(tmp_path, metadata):
    metadata_path = _write_metadata(tmp_path, metadata)
    site_root = tmp_path / "site"
    mismatched_path = _write_approval(site_root, _approval(topic_id="aabb-other-topic-2026"))

    with pytest.raises(ArtifactError, match="approves"):
        adopt_taxonomy(
            site_root, NEW_TOPIC, approval_path=mismatched_path, metadata_path=metadata_path
        )
