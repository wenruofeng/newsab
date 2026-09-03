"""The locale backfill: which publications it touches, what it reuses, what it refuses.

The underlying primitives (``prepare_publication``, ``activate_publication``) carry their
own guarantees; what is new — and what these tests pin — is the orchestration: skip the
already-current, reuse a prepared candidate, mint one authorization per supersede (never
an intent), carry the review with its original locale set, and let one topic's
refusal leave the rest of the batch running.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from newsab_publish import backfill
from newsab_schema.io import ArtifactError
from newsab_schema.models.publication import HumanApproval, PublicationReview
from newsab_schema.paths import SitePaths


DECIDED = datetime(2026, 8, 26, 18, 30, tzinfo=timezone.utc)


@pytest.fixture()
def site(tmp_path):
    return SitePaths.at(tmp_path / "site").ensure()


def _review(locale: str = "zh-CN", reviewed_locales=None) -> PublicationReview:
    return PublicationReview(
        approval_id="APR-aabb-river-light-2026-0123abcd",
        reviewer_id="founder",
        decided_at=DECIDED,
        locale=locale,
        page_hash="sha256:" + "d" * 64,
        reviewed_locales=reviewed_locales,
    )


def _record(pub_id: str, locales: tuple[str, ...], review: PublicationReview):
    topic_id = pub_id.removeprefix("PUB-").rsplit("-", 1)[0]
    return SimpleNamespace(
        publication_id=pub_id,
        topic_id=topic_id,
        page_run_id=f"rl-202608280900-{topic_id[:8]}",
        locales=[SimpleNamespace(locale=locale) for locale in locales],
        review=review,
        theme_token="slate",
        default_locale="zh-CN",
    )


@pytest.fixture()
def machinery(monkeypatch, site, metadata, tmp_path):
    """Stub the heavy primitives; keep the real locale resolution and review handling."""
    state = SimpleNamespace(
        records={},  # publication_id -> record
        selector={},  # topic_id -> live publication_id
        prepared=[],
        activated=[],
        prepare_error={},  # topic_id -> message
    )

    monkeypatch.setattr(backfill, "load_publications", lambda paths: dict(state.records))
    monkeypatch.setattr(backfill, "load_publication_events", lambda paths: [])
    monkeypatch.setattr(
        backfill,
        "derive_publish_selector",
        lambda pubs, events, publication_hashes=None: SimpleNamespace(
            publications=dict(state.selector)
        ),
    )
    monkeypatch.setattr(backfill, "file_digest", lambda path: "sha256:" + "e" * 64)

    class _Paths:
        def __init__(self, topics_root, topic_id):
            self.topic_id = topic_id

        @classmethod
        def for_topic(cls, topics_root, topic_id):
            return cls(topics_root, topic_id)

        def active_run_id(self, stage):
            assert stage == "editorial"
            return f"rl-202608280900-{self.topic_id[:8]}"

    monkeypatch.setattr(backfill, "TopicPaths", _Paths)
    monkeypatch.setattr(
        backfill,
        "resolve_inputs",
        lambda topics_root, topic_id, page_run_id: SimpleNamespace(
            topic_id=topic_id, page_run_id=page_run_id
        ),
    )
    monkeypatch.setattr(
        backfill,
        "_publication_id",
        lambda resolved, review, fp, locales, theme: (
            f"PUB-{resolved.topic_id}-{'b' * 12}"
        ),
    )

    def _prepare(topics_root, site_root, topic_id, **kwargs):
        if topic_id in state.prepare_error:
            raise ArtifactError(state.prepare_error[topic_id])
        state.prepared.append((topic_id, kwargs))

    monkeypatch.setattr(backfill, "prepare_publication", _prepare)
    # The signed baseline reads the live publication's stored bundle off disk; these
    # tests pin the orchestration, and the equivalence proof it feeds has its own
    # coverage in ``test_reviewed_equivalence.py``.
    monkeypatch.setattr(
        backfill,
        "signed_baseline",
        lambda topics_root, site_paths, record: SimpleNamespace(
            page_run_id=record.page_run_id
        ),
    )

    def _activate(topics_root, site_root, publication_id, **kwargs):
        state.activated.append((publication_id, kwargs))
        return SimpleNamespace(event_id=f"EVT-{publication_id[-4:]}")

    monkeypatch.setattr(backfill, "activate_publication", _activate)

    def run(**overrides):
        arguments = dict(
            metadata=metadata,
            metadata_path=backfill.Path(
                __import__("newsab_publish.metadata", fromlist=["default_metadata_path"])
                .default_metadata_path()
            ),
            production_dir=tmp_path / "public",
            base_url="https://example.org",
            reason="站点语言集扩到 en+zh-CN，批量补齐。",
        )
        arguments.update(overrides)
        return backfill.backfill_locales("topics", site.root, **arguments)

    state.run = run
    state.site = site
    return state


def test_a_publication_already_on_the_site_set_is_skipped(machinery):
    review = _review()
    machinery.records["PUB-aabb-river-light-2026-aaaaaaaaaaaa"] = _record(
        "PUB-aabb-river-light-2026-aaaaaaaaaaaa", ("en", "zh-CN"), review
    )
    machinery.selector["aabb-river-light-2026"] = "PUB-aabb-river-light-2026-aaaaaaaaaaaa"

    outcomes = machinery.run()
    assert [o.status for o in outcomes] == ["skipped"]
    assert machinery.prepared == [] and machinery.activated == []


def test_a_same_locale_set_publication_whose_page_run_moved_is_still_superseded(machinery):
    """A content-only rerun on non-reviewed languages (a lexicon-fill
    fixing an untranslated side badge, say) leaves the locale set exactly as it was —
    the locale-set check alone would skip this forever, so it must not be the only gate.
    """
    review = _review()
    record = _record(
        "PUB-aabb-river-light-2026-aaaaaaaaaaaa", ("en", "zh-CN"), review
    )
    record.page_run_id = "rl-202608280900-stale00"  # differs from the stub's "active" run
    machinery.records["PUB-aabb-river-light-2026-aaaaaaaaaaaa"] = record
    machinery.selector["aabb-river-light-2026"] = "PUB-aabb-river-light-2026-aaaaaaaaaaaa"

    outcomes = machinery.run()
    assert [o.status for o in outcomes] == ["superseded"]
    (topic, kwargs), = machinery.prepared
    assert topic == "aabb-river-light-2026"
    assert kwargs["page_run_id"] == "rl-202608280900-aabb-riv"
    assert tuple(kwargs["locales"]) == ("en", "zh-CN")


def test_a_narrower_publication_is_prepared_and_superseded_with_its_own_approval(machinery):
    """The narrower shape: live with no English page, brought to the site set.

    The review carries with the locale set it was actually bound into, and the
    authorization is a fresh record written against the new publication id — the batch
    never touches an intent.
    """
    review = _review(reviewed_locales=None)
    machinery.records["PUB-aabb-river-light-2026-aaaaaaaaaaaa"] = _record(
        "PUB-aabb-river-light-2026-aaaaaaaaaaaa", ("zh-CN",), review
    )
    machinery.selector["aabb-river-light-2026"] = "PUB-aabb-river-light-2026-aaaaaaaaaaaa"

    outcomes = machinery.run()
    assert [o.status for o in outcomes] == ["superseded"]
    assert outcomes[0].new_publication_id == "PUB-aabb-river-light-2026-" + "b" * 12

    (topic, kwargs), = machinery.prepared
    assert topic == "aabb-river-light-2026"
    assert tuple(kwargs["locales"]) == ("en", "zh-CN")
    # Records that predate reviewed_locales get the set their publication shipped.
    assert kwargs["review"].reviewed_locales == ["zh-CN"]
    assert kwargs["theme_token"] == "slate"

    (pub_id, activate_kwargs), = machinery.activated
    approval = activate_kwargs["approval"]
    assert isinstance(approval, HumanApproval)
    assert approval.note.text.startswith("站点语言集")
    written = machinery.site.private_dir / "approvals" / f"activate-{pub_id}.json"
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["approval_id"] == approval.approval_id


def test_an_already_prepared_candidate_is_reused_not_reprepared(machinery):
    review = _review(reviewed_locales=["zh-CN"])
    machinery.records["PUB-aabb-river-light-2026-aaaaaaaaaaaa"] = _record(
        "PUB-aabb-river-light-2026-aaaaaaaaaaaa", ("zh-CN",), review
    )
    machinery.selector["aabb-river-light-2026"] = "PUB-aabb-river-light-2026-aaaaaaaaaaaa"
    candidate = machinery.site.publication_record("PUB-aabb-river-light-2026-" + "b" * 12)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("{}", encoding="utf-8")

    outcomes = machinery.run()
    assert [o.status for o in outcomes] == ["superseded"]
    assert "reusing" in outcomes[0].detail
    assert machinery.prepared == []
    assert len(machinery.activated) == 1


def test_one_topics_refusal_leaves_the_rest_of_the_batch_running(machinery):
    for topic in ("aabb-harbor-bell-2026", "aabb-river-light-2026"):
        pub = f"PUB-{topic}-aaaaaaaaaaaa"
        machinery.records[pub] = _record(pub, ("zh-CN",), _review())
        machinery.selector[topic] = pub
    machinery.prepare_error["aabb-harbor-bell-2026"] = (
        "page-check: claim text missing language 'en'"
    )

    outcomes = machinery.run()
    by_topic = {o.topic_id: o for o in outcomes}
    assert by_topic["aabb-harbor-bell-2026"].status == "failed"
    assert "missing language" in by_topic["aabb-harbor-bell-2026"].detail
    assert by_topic["aabb-river-light-2026"].status == "superseded"


def test_a_backfill_without_a_reason_is_refused(machinery):
    with pytest.raises(ArtifactError, match="needs a reason"):
        machinery.run(reason="   ")
