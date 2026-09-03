from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from newsab_publish.metadata import SiteMetadata, load_site_metadata
from newsab_publish.site_strings import SITE_LOCALES, site_strings


def test_synthetic_taxonomy_carries_approved_backfill_and_new_mapping(metadata):
    assert [category.category_id for category in metadata.categories] == [
        "civic-life",
        "environment",
    ]
    assert [metadata.category_label(category.category_id, "zh-CN") for category in metadata.categories] == [
        "公共生活",
        "环境",
    ]
    backfilled = {
        "aabb-river-light-2026": ["civic-life", "environment"],
        "aabb-harbor-bell-2026": ["civic-life"],
        "aabb-garden-wind-2026": ["civic-life", "environment"],
        "aabb-old-map-2005": ["civic-life"],
    }
    assert {
        topic_id: metadata.topic_categories[topic_id] for topic_id in backfilled
    } == backfilled

    approval = metadata.taxonomy_backfill_approval
    assert approval is not None
    assert approval.reviewer_id == "synthetic-reviewer"
    assert approval.decision == "approved"
    assert set(approval.topic_ids) == set(backfilled)
    assert approval.note.lang == "en"

    # What actually matters: no mapping ships without the user deciding it, whether
    # through the legacy backfill or its own record.
    per_topic = {a.topic_id: a for a in metadata.topic_category_approvals}
    assert set(metadata.topic_categories) == set(backfilled) | set(per_topic)
    for topic_id, entry in per_topic.items():
        assert entry.reviewer_id == "synthetic-reviewer"
        assert entry.decision == "approved"
        assert entry.note.lang == "en"
        assert list(entry.category_ids) == metadata.topic_categories[topic_id]


def test_a_topic_mapping_without_a_user_approval_is_refused(metadata):
    """The mapping is a published fact; an agent may not add one on its own judgement."""
    payload = metadata.model_dump(mode="json")
    payload["topic_categories"]["xxyy-unapproved-2026"] = ["civic-life"]
    with pytest.raises(ValidationError, match="no user approval"):
        SiteMetadata.model_validate(payload)


def test_a_topic_approval_that_disagrees_with_its_mapping_is_refused(metadata):
    payload = metadata.model_dump(mode="json")
    approvals = payload["topic_category_approvals"]
    assert approvals, "fixture is expected to carry at least one per-topic approval"
    topic_id = approvals[0]["topic_id"]
    payload["topic_categories"][topic_id] = ["environment"]
    with pytest.raises(ValidationError, match="does not match the approved categories"):
        SiteMetadata.model_validate(payload)


def test_loader_takes_explicit_path_and_rejects_unknown_category(tmp_path):
    payload = {
        "metadata_version": "site-metadata-1.0.0",
        "taxonomy_version": "taxonomy-1.0.0",
        "locales": ["en", "zh-CN"],
        "categories": [
            {"category_id": "local-demo", "labels": {"en": "Demo", "zh-CN": "示例"}}
        ],
        "topic_categories": {},
    }
    payload["topic_categories"]["aabb-river-light-2026"] = ["made-up"]
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="unknown category"):
        load_site_metadata(path)


def test_category_labels_must_be_symmetric_across_site_locales(metadata):
    payload = metadata.model_dump(mode="json")
    del payload["categories"][0]["labels"]["en"]
    with pytest.raises(ValidationError, match="labels must match site locales"):
        SiteMetadata.model_validate(payload)


def test_site_dictionary_has_exactly_the_same_keys_in_every_site_locale():
    assert {"en", "zh-CN"} <= set(SITE_LOCALES)
    for locale in SITE_LOCALES:
        assert set(site_strings(locale)) == set(site_strings("en")), locale
    # The halo's other seven are pre-loaded, so a locale still outside ``SITE_LOCALES``
    # (``ar`` until batch 2) resolves too; a code with no catalog at all fails closed.
    assert set(site_strings("ar")) == set(site_strings("en"))
    with pytest.raises(ValueError, match="unsupported site locale"):
        site_strings("de")


def test_site_locales_must_contain_the_english_pivot(metadata):
    # Every shipped language is a localization of the pivot, so a set without it names
    # a site that cannot render the page it was written in.
    payload = metadata.model_dump(mode="json")
    payload["locales"] = ["zh-CN"]
    for category in payload["categories"]:
        category["labels"].pop("en", None)
    with pytest.raises(ValidationError) as excinfo:
        SiteMetadata.model_validate(payload)
    assert "pivot" in str(excinfo.value)
