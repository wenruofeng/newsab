from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from newsab_schema import (
    CatalogAngle,
    CatalogRecord,
    CatalogSide,
    LangText,
    SponsorAttribution,
    WorkerAttribution,
)

from newsab_publish.metadata import SiteMetadata


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
RUN_ID = "rl-202608250906-a0000007"

TOPICS = [
    "aabb-river-light-2026",
    "aabb-harbor-bell-2026",
    "aabb-garden-wind-2026",
    "aabb-old-map-2005",
    "aabb-sky-kite-1415",
]


@pytest.fixture
def metadata():
    return SiteMetadata.model_validate(
        {
            "metadata_version": "site-metadata-1.1.0",
            "taxonomy_version": "taxonomy-1.0.0",
            "locales": ["en", "zh-CN"],
            "categories": [
                {
                    "category_id": "civic-life",
                    "labels": {"en": "Civic life", "zh-CN": "公共生活"},
                },
                {
                    "category_id": "environment",
                    "labels": {"en": "Environment", "zh-CN": "环境"},
                },
            ],
            "topic_categories": {
                topic_id: (["civic-life", "environment"] if index % 2 == 0 else ["civic-life"])
                for index, topic_id in enumerate(TOPICS)
            },
            "taxonomy_backfill_approval": {
                "approval_id": "taxonomy-backfill-2026-08-29",
                "reviewer_id": "synthetic-reviewer",
                "decision": "approved",
                "decided_at": "2026-08-29T12:00:00Z",
                "topic_ids": TOPICS[:4],
                "note": {"text": "Synthetic fixture taxonomy approval.", "lang": "en"},
            },
            "topic_category_approvals": [
                {
                    "approval_id": "taxonomy-topic-aabb-sky-kite-1415-2026-08-29",
                    "topic_id": TOPICS[4],
                    "reviewer_id": "synthetic-reviewer",
                    "decision": "approved",
                    "decided_at": "2026-08-29T12:05:00Z",
                    "category_ids": ["civic-life", "environment"],
                    "note": {"text": "Synthetic per-topic approval.", "lang": "en"},
                }
            ],
        }
    )


@pytest.fixture
def catalog_factory(metadata):
    def make(
        serial: int,
        *,
        locale: str = "zh-CN",
        topic_id: str | None = None,
        published_at: datetime | None = None,
        title: str | None = None,
    ) -> CatalogRecord:
        topic = topic_id or TOPICS[serial % len(TOPICS)]
        is_zh = locale == "zh-CN"
        group_labels = (("aa", "甲组", "虚构甲组样本"), ("bb", "乙组", "虚构乙组样本"))
        if not is_zh:
            group_labels = (("aa", "Aster sample", "Fictional Aster coverage"), ("bb", "Beryl sample", "Fictional Beryl coverage"))
        pub_id = f"PUB-{topic}-{serial:012x}"
        page_url = f"/{locale}/topics/{topic}/"
        return CatalogRecord(
            publication_id=pub_id,
            publication_hash=HASH_A,
            public_bundle_fingerprint=HASH_B,
            topic_id=topic,
            locale=locale,
            slug=topic,
            page_url=page_url,
            title=LangText(
                text=title or ((f"议题 {serial}") if is_zh else f"Topic {serial}"),
                lang=locale,
            ),
            brief=LangText(
                text="两组报道如何回答同一问题。" if is_zh else "How two samples answer the same question.",
                lang=locale,
            ),
            sides=[
                CatalogSide(
                    group_id=group_id,
                    short_label=LangText(text=short, lang=locale),
                    definition=LangText(text=definition, lang=locale),
                )
                for group_id, short, definition in group_labels
            ],
            scope_start=date(2026, 5, 1),
            scope_end=date(2026, 8, 1),
            published_at=published_at or datetime(2026, 8, serial + 1, tzinfo=timezone.utc),
            category_ids=metadata.topic_categories[topic],
            source_languages=["zh-CN", "en"],
            reader_locales=["en", "zh-CN"],
            report_count=24,
            angles=[
                CatalogAngle(
                    question_id=f"QST-{topic}-{angle_serial:03d}",
                    question=LangText(
                        text=(f"问题 {angle_serial}？" if is_zh else f"Question {angle_serial}?"),
                        lang=locale,
                    ),
                    finding_kind="divergence",
                    answers={
                        "aa": LangText(text="答案甲" if is_zh else "Answer A", lang=locale),
                        "bb": LangText(text="答案乙" if is_zh else "Answer B", lang=locale),
                    },
                    fragment_url=f"{page_url}#angle-QST-{topic}-{angle_serial:03d}",
                )
                for angle_serial in range(1, 4)
            ],
            sponsor=SponsorAttribution(display_name="Synthetic toolkit demo"),
            workers=[WorkerAttribution(model_id="test-model", stages=["render-localize"], run_ids=[RUN_ID])],
            catalog_version="catalog-0.4.0",
        )

    return make
