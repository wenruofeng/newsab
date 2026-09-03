"""Stage-8 publication contracts and the site-level lifecycle state machine."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from newsab_schema import (
    CatalogAngle,
    CatalogRecord,
    CatalogSide,
    HumanApproval,
    LangText,
    LocaleBundle,
    LocalePlan,
    Provenance,
    PublicationEvent,
    PublicationEventLog,
    PublicationRecord,
    PublicationReview,
    ShareAsset,
    SitePaths,
    SponsorAttribution,
    TopicRunPin,
    WorkerAttribution,
)
from newsab_schema.io import ArtifactError
from newsab_schema.models.manifest import content_digest, file_digest
from newsab_schema.store import (
    append_publication_event,
    derive_publish_selector,
    load_publication_events,
    write_publication,
)


NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
TOPIC = "aabb-river-light-2026"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
RUNS = {
    "scope": "s0-202608250900-a0000001",
    "corpus": "s2s-202608250901-a0000002",
    "questions": "qset-202608250902-a0000003",
    "answers": "ans-202608250903-a0000004",
    "normalization": "norm-202608250904-a0000005",
    "analysis": "qa-202608250905-a0000006",
    "page": "rl-202608250906-a0000007",
}


def approval(suffix: str = "aaaa0001") -> HumanApproval:
    return HumanApproval(
        approval_id=f"APR-{TOPIC}-{suffix}",
        reviewer_id="founder",
        decided_at=NOW,
    )


def publication(
    publication_id: str = f"PUB-{TOPIC}-aaaaaaaaaaaa",
    *,
    page_hash: str = HASH_A,
) -> PublicationRecord:
    return PublicationRecord(
        publication_id=publication_id,
        topic_id=TOPIC,
        page_run_id=RUNS["page"],
        run_closure=[
            TopicRunPin(
                topic_id=TOPIC,
                stage=stage,
                run_id=run_id,
                artifact_fingerprint=HASH_A,
            )
            for stage, run_id in RUNS.items()
        ],
        review=PublicationReview(
            approval_id=f"APR-{TOPIC}-aaaab001",
            reviewer_id="founder",
            decided_at=NOW,
            locale="zh-cn",
            page_hash=page_hash,
        ),
        default_locale="zh-cn",
        locales=[
            LocaleBundle(locale="en", page_url=f"/en/topics/{TOPIC}/", page_hash=HASH_B),
            LocaleBundle(locale="zh-cn", page_url=f"/zh-CN/topics/{TOPIC}/", page_hash=page_hash),
        ],
        sponsor=SponsorAttribution(display_name="News A/B"),
        workers=[
            WorkerAttribution(
                model_id="test-model", stages=["render-localize"], run_ids=[RUNS["page"]]
            )
        ],
        site_metadata_version="site-metadata-1.0.0",
        site_metadata_fingerprint=HASH_A,
        render_input_hashes={"topics_by_article.json": HASH_A},
        public_bundle_fingerprint=HASH_B,
        prepared_at=NOW,
        provenance=Provenance(
            skill_version="publish-0.1.0",
            model_id=None,
            run_id="pub-202608250907-a0000008",
            timestamp=NOW,
        ),
    )


def event(
    event_id: str,
    event_type: str,
    target: PublicationRecord,
    *,
    previous: PublicationEvent | None = None,
    replacement: PublicationRecord | None = None,
) -> PublicationEvent:
    return PublicationEvent(
        event_id=event_id,
        event_type=event_type,
        publication_id=target.publication_id,
        publication_hash=content_digest(target.model_dump(mode="json")),
        replacement_publication_id=(replacement.publication_id if replacement else None),
        replacement_publication_hash=(
            content_digest(replacement.model_dump(mode="json")) if replacement else None
        ),
        reason=(
            None
            if event_type == "publish"
            else LangText(text=f"Approved {event_type}", lang="en")
        ),
        approval=approval(event_id[-8:].lower()),
        occurred_at=NOW,
        previous_event_hash=(
            content_digest(previous.model_dump(mode="json")) if previous else None
        ),
        provenance=Provenance(
            skill_version="publish-0.1.0",
            model_id=None,
            run_id=f"evt-202608251200-{event_id[-8:].lower()}",
            timestamp=NOW,
        ),
    )


def locale_plan(
    *,
    included: list[str] | None = None,
    target: list[str] | None = None,
) -> LocalePlan:
    return LocalePlan(
        approval_id=f"APR-{TOPIC}-aaaac001",
        topic_id=TOPIC,
        reviewer_id="founder",
        decided_at=NOW,
        reviewed_hash=HASH_A,
        included_locales=included or ["en", "zh-CN"],
        target_locales=target or ["en", "zh-CN", "ru", "fr"],
        reason=LangText(text="加选两语先扩", lang="zh-CN"),
    )


def test_locale_plan_records_target_superset_of_included():
    plan = locale_plan()
    assert plan.included_locales == ["en", "zh-CN"]
    assert plan.target_locales == ["en", "zh-CN", "ru", "fr"]


def test_locale_plan_refuses_a_target_narrower_than_included():
    with pytest.raises(ValidationError, match="target_locales must include"):
        locale_plan(included=["en", "zh-CN", "ru"], target=["en", "zh-CN"])


def test_locale_plan_refuses_duplicate_locales():
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        locale_plan(target=["en", "zh-CN", "en"])


def test_reviewed_publication_is_immutable_candidate_without_lifecycle_status():
    record = publication()
    assert record.default_locale == "zh-CN"
    assert "status" not in type(record).model_fields
    assert "published_at" not in type(record).model_fields
    assert {pin.stage for pin in record.run_closure} == set(RUNS)


def test_share_assets_are_angle_specific_and_locale_symmetric():
    record = publication()
    assets = [
        ShareAsset(
            locale=locale,
            question_id=f"QST-{TOPIC}-001",
            url=f"/{locale}/topics/{TOPIC}/share/angle-QST-{TOPIC}-001.svg",
            sha256=HASH_A,
            landing_url=f"/{locale}/topics/{TOPIC}/share/angle-QST-{TOPIC}-001.html",
            landing_sha256=HASH_B,
        )
        for locale in ("en", "zh-CN")
    ]
    payload = record.model_dump(mode="json")
    payload["share_assets"] = [asset.model_dump(mode="json") for asset in assets]
    validated = PublicationRecord.model_validate(payload)
    assert validated.share_assets == assets

    payload = record.model_dump(mode="json")
    payload["share_assets"] = [assets[0].model_dump(mode="json")]
    with pytest.raises(ValidationError, match="cover every publication locale"):
        PublicationRecord.model_validate(payload)


def test_share_assets_may_pin_the_landing_alone():
    """A record minted since publish-0.8.0 ships no SVG card; the historical ones do."""
    record = publication()
    landings = [
        ShareAsset(
            locale=locale,
            question_id=f"QST-{TOPIC}-001",
            landing_url=f"/{locale}/topics/{TOPIC}/share/angle-QST-{TOPIC}-001.html",
            landing_sha256=HASH_B,
        )
        for locale in ("en", "zh-CN")
    ]
    assert all(asset.url is None and asset.mime_type is None for asset in landings)
    payload = record.model_dump(mode="json")
    payload["share_assets"] = [asset.model_dump(mode="json") for asset in landings]
    validated = PublicationRecord.model_validate(payload)
    assert validated.share_assets == landings

    # The image fields are one fact: half a card is a corrupt record, not a new shape.
    with pytest.raises(ValidationError, match="appear together"):
        ShareAsset(
            locale="en",
            question_id=f"QST-{TOPIC}-001",
            landing_url=f"/en/topics/{TOPIC}/share/angle-QST-{TOPIC}-001.html",
            landing_sha256=HASH_B,
            url=f"/en/topics/{TOPIC}/share/angle-QST-{TOPIC}-001.svg",
        )


def test_topic_run_pin_allows_only_the_known_legacy_scope_shape():
    legacy = TopicRunPin(
        topic_id=TOPIC,
        stage="scope",
        run_id="scope-20260823055138",
        artifact_fingerprint=HASH_A,
    )
    assert legacy.run_id == "scope-20260823055138"

    with pytest.raises(ValidationError, match="legacy scope pin"):
        TopicRunPin(
            topic_id=TOPIC,
            stage="corpus",
            run_id="scope-20260823055138",
            artifact_fingerprint=HASH_A,
        )

    worker = WorkerAttribution(
        model_id="legacy-model",
        stages=["scope"],
        run_ids=["scope-20260823055138"],
    )
    assert worker.stages == ["scope"]
    with pytest.raises(ValidationError, match="requires scope attribution"):
        WorkerAttribution(
            model_id="legacy-model",
            stages=["collect"],
            run_ids=["scope-20260823055138"],
        )


def test_publication_requires_complete_closure_and_exact_reviewed_bytes():
    payload = publication().model_dump(mode="json")
    payload["run_closure"] = payload["run_closure"][:-1]
    with pytest.raises(ValidationError, match="missing required stages"):
        PublicationRecord.model_validate(payload)

    payload = publication().model_dump(mode="json")
    payload["locales"][1]["page_hash"] = HASH_B
    with pytest.raises(ValidationError, match="differ from the human-reviewed bytes"):
        PublicationRecord.model_validate(payload)

    payload = publication().model_dump(mode="json")
    payload.update(submission_id="SUB-001", submission_archive_hash=HASH_A)
    with pytest.raises(ValidationError, match="audit_run_id"):
        PublicationRecord.model_validate(payload)

    payload = publication().model_dump(mode="json")
    payload["render_input_hashes"] = {"../private.json": HASH_A}
    with pytest.raises(ValidationError, match="render_input_hashes"):
        PublicationRecord.model_validate(payload)


def test_event_stream_derives_publish_supersede_withdraw_and_restore():
    first = publication()
    second = publication(f"PUB-{TOPIC}-bbbbbbbbbbbb", page_hash=HASH_B)
    published = event("EVT-20260825120000-00000001", "publish", first)
    superseded = event(
        "EVT-20260825120100-00000002",
        "supersede",
        first,
        previous=published,
        replacement=second,
    )
    withdrawn = event(
        "EVT-20260825120200-00000003", "withdraw", second, previous=superseded
    )
    restored = event(
        "EVT-20260825120300-00000004", "restore", second, previous=withdrawn
    )

    selector = derive_publish_selector(
        {first.publication_id: first, second.publication_id: second},
        [published, superseded, withdrawn, restored],
    )
    assert selector.publications == {TOPIC: second.publication_id}
    assert selector.event_count == 4


def test_event_hash_chain_and_state_machine_refuse_gaps():
    record = publication()
    published = event("EVT-20260825120000-00000001", "publish", record)
    restore = event("EVT-20260825120100-00000002", "restore", record, previous=published)
    with pytest.raises(ArtifactError, match="restore requires"):
        derive_publish_selector({record.publication_id: record}, [published, restore])

    broken = restore.model_copy(update={"previous_event_hash": HASH_A})
    with pytest.raises(ValidationError, match="previous_event_hash"):
        PublicationEventLog(events=[published, broken])


def catalog(record: PublicationRecord) -> CatalogRecord:
    return CatalogRecord(
        publication_id=record.publication_id,
        publication_hash=content_digest(record.model_dump(mode="json")),
        public_bundle_fingerprint=record.public_bundle_fingerprint,
        topic_id=TOPIC,
        locale="zh-cn",
        slug=TOPIC,
        page_url=f"/zh-CN/topics/{TOPIC}/",
        title=LangText(text="签证报道比较", lang="zh-cn"),
        brief=LangText(text="两组媒体如何回答同一问题。", lang="zh-cn"),
        sides=[
            CatalogSide(
                group_id="cn",
                short_label=LangText(text="中方", lang="zh-cn"),
                definition=LangText(text="样本中的中文报道", lang="zh-cn"),
            ),
            CatalogSide(
                group_id="us",
                short_label=LangText(text="美方", lang="zh-cn"),
                definition=LangText(text="样本中的英文报道", lang="zh-cn"),
            ),
        ],
        scope_start=date(2026, 5, 1),
        scope_end=date(2026, 8, 1),
        published_at=NOW,
        category_ids=["policy"],
        source_languages=["zh-CN", "en"],
        reader_locales=["en", "zh-CN"],
        report_count=24,
        angles=[
            CatalogAngle(
                question_id=f"QST-{TOPIC}-{serial:03d}",
                question=LangText(text=f"报道问题 {serial} 是什么？", lang="zh-cn"),
                finding_kind="divergence",
                answers={
                    "cn": LangText(text="政策冲击", lang="zh-cn"),
                    "us": LangText(text="执行不确定", lang="zh-cn"),
                },
                fragment_url=(
                    f"/zh-CN/topics/{TOPIC}/#angle-QST-{TOPIC}-{serial:03d}"
                ),
            )
            for serial in range(1, 4)
        ],
        sponsor=record.sponsor,
        workers=record.workers,
        catalog_version="catalog-0.1.0",
    )


def test_catalog_is_one_locale_and_has_exactly_the_publication_sides():
    row = catalog(publication())
    assert row.locale == "zh-CN"

    payload = row.model_dump(mode="json")
    payload["angles"][0]["answers"].pop("us")
    with pytest.raises(ValidationError, match="answer sides"):
        CatalogRecord.model_validate(payload)


def test_catalog_counts_must_be_recomputable_cluster_fractions():
    payload = catalog(publication()).model_dump(mode="json")
    payload["angles"][0]["counts"] = {"cn": "2/28", "us": "5/9"}
    validated = CatalogRecord.model_validate(payload)
    assert validated.angles[0].counts == {"cn": "2/28", "us": "5/9"}

    for impossible in ("9/3", "5/0"):
        payload["angles"][0]["counts"] = {"cn": impossible, "us": "5/9"}
        with pytest.raises(ValidationError, match="recomputable"):
            CatalogRecord.model_validate(payload)


def test_publication_topic_binding_is_exact_not_a_prefix():
    from newsab_schema.models.publication import PublishSelector

    selector = PublishSelector(
        publications={TOPIC: f"PUB-{TOPIC}-aaaaaaaaaaaa"},
        event_count=1,
        event_log_hash=HASH_A,
    )
    assert selector.publications[TOPIC].endswith("aaaaaaaaaaaa")

    # "PUB-aabb-river-light-2026-…" starts with "PUB-aabb-river-light-", so a prefix test would let
    # the hyphenated sibling topic claim it.
    with pytest.raises(ValidationError, match="belongs to another topic"):
        PublishSelector(
            publications={"aabb-river-light": f"PUB-{TOPIC}-aaaaaaaaaaaa"},
            event_count=1,
            event_log_hash=HASH_A,
        )


def test_legacy_scope_exemption_is_a_closed_id_list_not_a_shape():
    with pytest.raises(ValidationError, match="legacy scope"):
        TopicRunPin(
            topic_id=TOPIC,
            stage="scope",
            run_id="scope-99991231235959",
            artifact_fingerprint=HASH_A,
        )
    with pytest.raises(ValidationError, match="run_ids are invalid"):
        WorkerAttribution(
            model_id="legacy-model",
            stages=["scope"],
            run_ids=["scope-99991231235959"],
        )


def test_render_input_keys_must_be_normalized_relative_paths():
    for bad_key in (".", "./topics_by_article.json", "a/./b.json", "/etc/passwd"):
        payload = publication().model_dump(mode="json")
        payload["render_input_hashes"] = {bad_key: HASH_A}
        with pytest.raises(ValidationError, match="render_input_hashes"):
            PublicationRecord.model_validate(payload)


def test_event_chain_refuses_backdated_events():
    record = publication()
    published = event("EVT-20260825120000-00000001", "publish", record)
    payload = event(
        "EVT-20260825120100-00000002", "withdraw", record, previous=published
    ).model_dump(mode="json")
    payload["occurred_at"] = "2020-01-01T00:00:00Z"
    payload["approval"]["decided_at"] = "2020-01-01T00:00:00Z"
    backdated = PublicationEvent.model_validate(payload)
    with pytest.raises(ValidationError, match="precedes the prior event"):
        PublicationEventLog(events=[published, backdated])


def test_site_store_refuses_overwrite_and_appends_event_before_selector(tmp_path):
    paths = SitePaths.at(tmp_path / "site").ensure()
    record = publication()
    publication_path = write_publication(paths, record)
    with pytest.raises(ArtifactError, match="overwrite publication"):
        write_publication(paths, record)

    publish_event = event("EVT-20260825120000-00000001", "publish", record)
    publish_event = publish_event.model_copy(
        update={"publication_hash": file_digest(publication_path)}
    )
    append_publication_event(paths, publish_event)
    assert load_publication_events(paths) == [publish_event]
    assert paths.production_selector.is_file()

    withdraw_event = event(
        "EVT-20260825120100-00000002",
        "withdraw",
        record,
        previous=publish_event,
    ).model_copy(update={"publication_hash": file_digest(publication_path)})
    append_publication_event(paths, withdraw_event)
    assert load_publication_events(paths) == [publish_event, withdraw_event]
    selector = paths.production_selector.read_text(encoding="utf-8")
    assert '"event_count":2' in selector
    assert '"publications":{}' in selector


def test_write_publication_recovers_from_a_crashed_partial_write(tmp_path):
    paths = SitePaths.at(tmp_path / "site").ensure()
    record = publication()
    # A crash between mkdir and the record write leaves an empty directory; the retry
    # must succeed instead of dying on FileExistsError.
    paths.publication_dir(record.publication_id).mkdir(parents=True)
    target = write_publication(paths, record)
    assert target.is_file()


def test_audit_delete_is_terminal_and_the_topic_can_republish(tmp_path):
    paths = SitePaths.at(tmp_path / "site").ensure()
    first = publication()
    second = publication(f"PUB-{TOPIC}-bbbbbbbbbbbb", page_hash=HASH_B)
    first_hash = file_digest(write_publication(paths, first))
    second_hash = file_digest(write_publication(paths, second))

    published = event("EVT-20260825120000-00000001", "publish", first).model_copy(
        update={"publication_hash": first_hash}
    )
    append_publication_event(paths, published)

    # Audit deletion of the live publication is refused; it must be withdrawn first.
    premature = event(
        "EVT-20260825120100-00000002", "audit_delete", first, previous=published
    ).model_copy(update={"publication_hash": first_hash})
    with pytest.raises(ArtifactError, match="withdraw a live publication"):
        append_publication_event(paths, premature)

    withdrawn = event(
        "EVT-20260825120100-00000002", "withdraw", first, previous=published
    ).model_copy(update={"publication_hash": first_hash})
    append_publication_event(paths, withdrawn)
    deleted = event(
        "EVT-20260825120200-00000003", "audit_delete", first, previous=withdrawn
    ).model_copy(update={"publication_hash": first_hash})
    append_publication_event(paths, deleted)

    republished = event(
        "EVT-20260825120300-00000004", "publish", second, previous=deleted
    ).model_copy(update={"publication_hash": second_hash})
    append_publication_event(paths, republished)
    selector = paths.production_selector.read_text(encoding="utf-8")
    assert second.publication_id in selector
    assert first.publication_id not in selector


def test_load_publications_fails_closed_on_stray_directory_entries(tmp_path):
    paths = SitePaths.at(tmp_path / "site").ensure()
    record = publication()
    publication_hash = file_digest(write_publication(paths, record))
    (paths.publications_dir / "scratch").mkdir()
    publish_event = event("EVT-20260825120000-00000001", "publish", record).model_copy(
        update={"publication_hash": publication_hash}
    )
    with pytest.raises(ArtifactError, match="scratch"):
        append_publication_event(paths, publish_event)


def test_site_paths_use_an_allowlist_for_public_sources(tmp_path):
    paths = SitePaths.at(tmp_path / "site").ensure()
    assert paths.is_public_source(paths.publication_record(f"PUB-{TOPIC}-aaaaaaaaaaaa"))
    assert paths.is_public_source(paths.catalog("zh-CN"))
    assert paths.visibility(paths.publication_events) == "internal"
    assert paths.is_private(paths.submissions_dir / "upload.zip")
    assert paths.is_private(paths.audit_dir / "articles" / "CN_deadbeef.json")
