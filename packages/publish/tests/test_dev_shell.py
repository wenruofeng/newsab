"""The Dev Shell: the decisions it may take, the ones it must refuse, and what it serves."""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import pytest

from newsab_publish import dev_shell
from newsab_publish.builder import bytes_digest, write_chrome_assets
from newsab_publish.dashboard_strings import dashboard_strings
from newsab_publish.themes import load_theme_registry
from newsab_schema import HALO_LOCALE_CODES
from newsab_schema.io import ArtifactError
from newsab_schema.models.publication import HumanApproval, PublicationReview
from newsab_schema.paths import SitePaths


#: The dashboard's default UI language is zh-CN (``DEFAULT_DASHBOARD_LOCALE``); tests that
#: assert on literal rendered copy read it from the same table the renderer does, so
#: they track the table instead of duplicating its bytes.
ZH = dashboard_strings("zh-CN")


DECIDED = datetime(2026, 8, 26, 18, 30, tzinfo=timezone.utc)


@pytest.fixture()
def site(tmp_path):
    return SitePaths.at(tmp_path / "site").ensure()


def _page(root, locale: str, topic_id: str, body: str) -> None:
    target = root / locale / "topics" / topic_id / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def _topic_manifest(topics_root, topic_id: str, *, review_locale: str | None = "zh-CN"):
    """A scope on disk — the only place the dashboard learns a topic's review language.

    Written for real rather than stubbed: ``collect_state`` reads ``review_locale`` off
    the manifest, so a test that wants an approvable release card has to have signed a
    scope the same way the user does.
    """
    from datetime import date

    from newsab_schema.common import Provenance
    from newsab_schema.io import write_yaml
    from newsab_schema.models.corpus import Group, Period, TopicManifest
    from newsab_schema.paths import TopicPaths

    paths = TopicPaths.for_topic(topics_root, topic_id)
    manifest = TopicManifest(
        topic_id=topic_id,
        title={"values": {"en": "Test topic"}},
        groups=[
            Group(
                group_id="cn", prefix="CN",
                label={"values": {"en": "Chinese coverage"}},
                short_label={"values": {"en": "China side"}},
                definition={"values": {"en": "Chinese-language coverage"}},
            ),
            Group(
                group_id="us", prefix="US",
                label={"values": {"en": "US coverage"}},
                short_label={"values": {"en": "US side"}},
                definition={"values": {"en": "US-produced English coverage"}},
            ),
        ],
        period=Period(start=date(2026, 5, 1)),
        include=["test scope item"],
        review_locale=review_locale,
        provenance=Provenance(
            skill_version="S0-0.1.0",
            model_id=None,
            run_id="s0-202609020000-00000001",
            timestamp="2026-09-02T00:00:00Z",
        ),
    )
    write_yaml(paths.topic_manifest, manifest)
    return manifest


def test_touchpoint_two_binds_the_bytes_the_server_actually_served(site, tmp_path):
    root = tmp_path / "review"
    _page(root, "zh-CN", "aabb-river-light-2026", "<html>批准我</html>")
    served = dev_shell.ServedRoot(
        key="preview:review", kind="preview", label="review", path=root, port=9001
    )
    pages = dev_shell.review_pages(served)
    assert len(pages) == 1
    page = pages[0]
    assert page.page_hash == bytes_digest("<html>批准我</html>".encode("utf-8"))
    assert page.url == "http://127.0.0.1:9001/zh-CN/topics/aabb-river-light-2026/"

    path = dev_shell.record_page_approval(
        site,
        topic_id=page.topic_id,
        locale=page.locale,
        page_hash=page.page_hash,
        reviewer_id="founder",
        note="读完了，可以发。",
        note_lang="zh-CN",
        decided_at=DECIDED,
    )
    review = PublicationReview.model_validate_json(path.read_text(encoding="utf-8"))
    assert review.page_hash == page.page_hash
    assert review.locale == "zh-CN"
    assert review.decision == "approved"
    assert review.note.lang == "zh-CN"
    # Byte-isomorphic with a hand-written review record: one canonical line plus newline.
    assert path.read_text(encoding="utf-8") == review.model_dump_json() + "\n"


def test_a_decision_record_is_never_silently_overwritten(site):
    first = dev_shell.record_page_approval(
        site,
        topic_id="aabb-river-light-2026",
        locale="zh-CN",
        page_hash="sha256:" + "ab" * 32,
        reviewer_id="founder",
        note="",
        note_lang="zh-CN",
        decided_at=DECIDED,
    )
    assert first.is_file()
    with pytest.raises(ArtifactError, match="refusing to overwrite"):
        dev_shell.record_page_approval(
            site,
            topic_id="aabb-river-light-2026",
            locale="zh-CN",
            page_hash="sha256:" + "ab" * 32,
            reviewer_id="founder",
            note="改主意了",
            note_lang="zh-CN",
            decided_at=DECIDED,
        )


def test_one_decision_writes_the_review_and_the_lifecycle_authorization(site):
    """Approving the bytes they read *is* the authorization to ship them.

    The second click asked a question the first had already answered, so both records now
    come from one confirmation.  What still guards the bytes is mechanical —
    ``verify-candidate`` re-renders and compares, and no click can wave that past.
    """
    pages = [
        {"locale": "en", "page_hash": "sha256:" + "a" * 64},
        {"locale": "zh-CN", "page_hash": "sha256:" + "b" * 64},
    ]
    result = dev_shell.record_release_approval(
        site,
        topic_id="aabb-river-light-2026",
        pages=pages,
        reviewer_locale="zh-CN",
        reason="合并重批。",
        reviewer_id="founder",
        publication_id="PUB-aabb-river-light-2026-0123456789ab",
        decided_at=DECIDED,
    )
    assert len(result["reviews"]) == 2
    for path, page in zip(sorted(result["reviews"]), sorted(pages, key=lambda p: p["locale"])):
        review = PublicationReview.model_validate_json(
            pathlib.Path(path).read_text(encoding="utf-8")
        )
        assert review.page_hash == page["page_hash"]
    authorization = pathlib.Path(result["authorization"])
    assert authorization.name == "activate-PUB-aabb-river-light-2026-0123456789ab.json"
    approval = HumanApproval.model_validate_json(authorization.read_text(encoding="utf-8"))
    assert approval.reviewer_id == "founder"
    assert approval.note.text == "合并重批。"


def test_release_approval_always_records_a_locale_plan_even_with_no_extra_languages(site):
    """Silence is itself the decision — "ship only what is already here" — so the
    plan is written every time, not only when the user checked a box."""
    pages = [
        {"locale": "en", "page_hash": "sha256:" + "a" * 64},
        {"locale": "zh-CN", "page_hash": "sha256:" + "b" * 64},
    ]
    result = dev_shell.record_release_approval(
        site,
        topic_id="aabb-river-light-2026",
        pages=pages,
        reviewer_locale="zh-CN",
        reason="合并重批。",
        reviewer_id="founder",
        publication_id="PUB-aabb-river-light-2026-0123456789ab",
        decided_at=DECIDED,
    )
    plan_path = pathlib.Path(result["locale_plan"])
    assert plan_path.name == f"locale-plan-aabb-river-light-2026-{('sha256:' + 'b'*64)[7:15]}.json"
    from newsab_schema.models.publication import LocalePlan

    plan = LocalePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    assert plan.included_locales == ["en", "zh-CN"]
    assert plan.target_locales == ["en", "zh-CN"]
    assert result["target_locales"] == ["en", "zh-CN"]


def test_release_approval_records_the_users_checked_extra_languages(site):
    pages = [
        {"locale": "en", "page_hash": "sha256:" + "a" * 64},
        {"locale": "zh-CN", "page_hash": "sha256:" + "b" * 64},
    ]
    result = dev_shell.record_release_approval(
        site,
        topic_id="aabb-river-light-2026",
        pages=pages,
        reviewer_locale="zh-CN",
        reason="批一下顺带扩两语。",
        reviewer_id="founder",
        publication_id="PUB-aabb-river-light-2026-0123456789ab",
        add_locales=["ru", "fr"],
        decided_at=DECIDED,
    )
    from newsab_schema.models.publication import LocalePlan

    plan = LocalePlan.model_validate_json(
        pathlib.Path(result["locale_plan"]).read_text(encoding="utf-8")
    )
    assert plan.included_locales == ["en", "zh-CN"]
    assert plan.target_locales == ["en", "fr", "ru", "zh-CN"]
    assert result["target_locales"] == ["en", "fr", "ru", "zh-CN"]
    assert plan.reason.text == "批一下顺带扩两语。"


def test_release_approval_refuses_an_add_locale_outside_the_halos_nine(site):
    pages = [{"locale": "zh-CN", "page_hash": "sha256:" + "b" * 64}]
    with pytest.raises(ArtifactError, match="outside the halo's nine"):
        dev_shell.record_release_approval(
            site,
            topic_id="aabb-river-light-2026",
            pages=pages,
            reviewer_locale="zh-CN",
            reason="试试非法语言",
            reviewer_id="founder",
            publication_id="PUB-aabb-river-light-2026-0123456789ab",
            add_locales=["de"],
            decided_at=DECIDED,
        )


def test_release_approval_is_idempotent_on_the_locale_plan_when_retried(site):
    """A retried approval click (e.g. a flaky connection) must not raise on the second
    write — the same review/authorization idempotency already relied on for the other
    two records extends to the locale plan."""
    pages = [{"locale": "zh-CN", "page_hash": "sha256:" + "b" * 64}]
    kwargs = dict(
        site_paths=site,
        topic_id="aabb-river-light-2026",
        pages=pages,
        reviewer_locale="zh-CN",
        reason="重试也不该炸。",
        reviewer_id="founder",
        publication_id="PUB-aabb-river-light-2026-0123456789ab",
        add_locales=["ru"],
        decided_at=DECIDED,
    )
    first = dev_shell.record_release_approval(**kwargs)
    second = dev_shell.record_release_approval(**kwargs)
    assert first["locale_plan"] == second["locale_plan"]


def test_a_release_decision_without_a_reason_is_refused(site):
    """The reason outlives the click: it goes into the permanent event log."""
    with pytest.raises(ArtifactError):
        dev_shell.record_release_approval(
            site,
            topic_id="aabb-river-light-2026",
            pages=[{"locale": "zh-CN", "page_hash": "sha256:" + "c" * 64}],
            reviewer_locale="zh-CN",
            reason="   ",
            reviewer_id="founder",
            publication_id="PUB-aabb-river-light-2026-0123456789ab",
            decided_at=DECIDED,
        )


def test_an_authorization_signed_before_prepare_is_promoted_by_its_page_hash(site):
    """Touchpoint two happens on preview bytes; ``prepare`` is what mints the id.

    So a decision taken before ``prepare`` is filed as an intent keyed by the hash the
    user signed, and promoted only when a candidate pins that exact hash as reviewed.
    """
    page_hash = "sha256:" + "d" * 64
    result = dev_shell.record_release_approval(
        site,
        topic_id="aabb-river-light-2026",
        pages=[{"locale": "zh-CN", "page_hash": page_hash}],
        reviewer_locale="zh-CN",
        reason="读完了，可以发。",
        reviewer_id="founder",
        decided_at=DECIDED,
    )
    intent = pathlib.Path(result["authorization"])
    assert intent.name.startswith("activate-intent-aabb-river-light-2026-")
    assert result["publication_id"] == ""

    promoted = dev_shell.promote_intent(
        site,
        topic_id="aabb-river-light-2026",
        publication_id="PUB-aabb-river-light-2026-0123456789ab",
        page_hash=page_hash,
    )
    assert promoted.name == "activate-PUB-aabb-river-light-2026-0123456789ab.json"
    assert promoted.read_text(encoding="utf-8") == intent.read_text(encoding="utf-8")

    # A candidate pinning bytes the user never signed gets nothing.
    assert (
        dev_shell.promote_intent(
            site,
            topic_id="aabb-river-light-2026",
            publication_id="PUB-aabb-river-light-2026-ffffffffffff",
            page_hash="sha256:" + "e" * 64,
        )
        is None
    )


def test_a_promoted_intent_is_spent_and_never_authorizes_a_second_operation(site):
    """The user signed one lifecycle move, not every future prepare.

    The same approved bytes can be prepared again (a locale backfill does exactly that),
    and before this fix the second ``prepare`` re-promoted the same signature — hanging an
    authorization on the new publication that was actually spent on the previous one.
    """
    page_hash = "sha256:" + "f" * 64
    dev_shell.record_release_approval(
        site,
        topic_id="aabb-river-light-2026",
        pages=[{"locale": "zh-CN", "page_hash": page_hash}],
        reviewer_locale="zh-CN",
        reason="读完了，可以发。",
        reviewer_id="founder",
        decided_at=DECIDED,
    )
    first = dev_shell.promote_intent(
        site,
        topic_id="aabb-river-light-2026",
        publication_id="PUB-aabb-river-light-2026-111111111111",
        page_hash=page_hash,
    )
    assert first is not None

    # The consumption is a sidecar record; the signed intent itself is never edited.
    spent = dev_shell.consumed_intent(
        site, topic_id="aabb-river-light-2026", page_hash=page_hash
    )
    assert spent["publication_id"] == "PUB-aabb-river-light-2026-111111111111"
    assert dev_shell.intent_path(site, "aabb-river-light-2026", page_hash).is_file()

    # A second candidate pinning the same bytes gets nothing and must bring its own
    # authorization.
    assert (
        dev_shell.promote_intent(
            site,
            topic_id="aabb-river-light-2026",
            publication_id="PUB-aabb-river-light-2026-222222222222",
            page_hash=page_hash,
        )
        is None
    )

    # The dashboard likewise stops offering the spent intent as an authorization.
    assert (
        dev_shell.pending_intent_path(
            site, topic_id="aabb-river-light-2026", page_hash=page_hash
        )
        is None
    )

    # Re-running the *same* candidate's prepare after a crash between marker and copy
    # completes the interrupted promotion instead of refusing it.
    first.unlink()
    again = dev_shell.promote_intent(
        site,
        topic_id="aabb-river-light-2026",
        publication_id="PUB-aabb-river-light-2026-111111111111",
        page_hash=page_hash,
    )
    assert again == first and again.is_file()


def test_locale_plan_consumption_mirrors_the_activation_intent_pattern(site):
    """A locale-plan is read by a later expansion run and then marked spent, the
    same single-use shape as the activation intent it sits beside — never re-read as
    though the user can revise the plan out of band."""
    page_hash = "sha256:" + "5" * 64
    result = dev_shell.record_release_approval(
        site,
        topic_id="aabb-river-light-2026",
        pages=[
            {"locale": "en", "page_hash": "sha256:" + "6" * 64},
            {"locale": "zh-CN", "page_hash": page_hash},
        ],
        reviewer_locale="zh-CN",
        reason="批准并顺带扩语。",
        reviewer_id="founder",
        add_locales=["ko"],
        decided_at=DECIDED,
    )
    assert result["target_locales"] == ["en", "ko", "zh-CN"]

    plan = dev_shell.pending_locale_plan(
        site, topic_id="aabb-river-light-2026", reviewed_hash=page_hash
    )
    assert plan is not None
    assert plan.target_locales == ["en", "ko", "zh-CN"]

    marker = dev_shell.consume_locale_plan(
        site,
        topic_id="aabb-river-light-2026",
        reviewed_hash=page_hash,
        consumer="PUB-aabb-river-light-2026-555555555555",
    )
    assert marker is not None and marker.is_file()

    # Once consumed, it no longer offers itself as still-pending — a second expansion
    # run must bring its own fresh plan rather than replay this one.
    assert (
        dev_shell.pending_locale_plan(
            site, topic_id="aabb-river-light-2026", reviewed_hash=page_hash
        )
        is None
    )
    # But the record itself is never edited or removed — an audit can still read it.
    assert dev_shell.locale_plan_path(
        site, "aabb-river-light-2026", page_hash
    ).is_file()

    # Idempotent: consuming an already-consumed plan is a no-op, not an error.
    again = dev_shell.consume_locale_plan(
        site,
        topic_id="aabb-river-light-2026",
        reviewed_hash=page_hash,
        consumer="PUB-aabb-river-light-2026-555555555555",
    )
    assert again == marker


def test_reapproving_bytes_whose_intent_was_spent_is_refused(site):
    """The intent slot is single-use; a later decision must bind the new publication id."""
    page_hash = "sha256:" + "9" * 64
    dev_shell.record_release_approval(
        site,
        topic_id="aabb-river-light-2026",
        pages=[{"locale": "zh-CN", "page_hash": page_hash}],
        reviewer_locale="zh-CN",
        reason="读完了，可以发。",
        reviewer_id="founder",
        decided_at=DECIDED,
    )
    dev_shell.promote_intent(
        site,
        topic_id="aabb-river-light-2026",
        publication_id="PUB-aabb-river-light-2026-333333333333",
        page_hash=page_hash,
    )
    with pytest.raises(ArtifactError, match="already consumed"):
        dev_shell.record_release_approval(
            site,
            topic_id="aabb-river-light-2026",
            pages=[{"locale": "zh-CN", "page_hash": page_hash}],
            reviewer_locale="zh-CN",
            reason="再批一次。",
            reviewer_id="founder",
            decided_at=DECIDED,
        )
    # With the publication id in hand the same decision is recordable directly.
    result = dev_shell.record_release_approval(
        site,
        topic_id="aabb-river-light-2026",
        pages=[{"locale": "zh-CN", "page_hash": page_hash}],
        reviewer_locale="zh-CN",
        reason="再批一次。",
        reviewer_id="founder",
        publication_id="PUB-aabb-river-light-2026-444444444444",
        decided_at=DECIDED,
    )
    assert pathlib.Path(result["authorization"]).name == (
        "activate-PUB-aabb-river-light-2026-444444444444.json"
    )


def test_a_note_is_recorded_as_a_note_and_never_as_an_approval(site):
    path = dev_shell.record_note(
        site, subject="PUB-aabb-river-light-2026-0123456789ab", text="角度 3 的措辞要改", reviewer_id="founder"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["decision"] == "note"
    assert "approval_id" not in payload
    with pytest.raises(ArtifactError, match="needs text"):
        dev_shell.record_note(site, subject="x", text="   ", reviewer_id="founder")


def test_theme_proposal_targets_the_registry_not_css(site):
    registry = load_theme_registry()
    payload = {
        "schema_version": registry.schema_version,
        "default_token": registry.default_token,
        "themes": [theme.model_dump(mode="json") for theme in registry.themes],
    }
    path = dev_shell.record_theme_proposal(site, payload=payload, author="founder")
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["target"].endswith("theme_tokens.v1.json")
    assert document["gate"] == ["contrast", "web-gate", "site-operator-commit"]
    with pytest.raises(ArtifactError, match="at least one theme"):
        dev_shell.record_theme_proposal(site, payload={"themes": []}, author="founder")


def test_only_undecided_candidates_get_a_port(site, monkeypatch):
    class _Record:
        pass

    class _Event:
        def __init__(self, publication_id, replacement=None):
            self.publication_id = publication_id
            self.replacement_publication_id = replacement

    monkeypatch.setattr(
        dev_shell,
        "load_publications",
        lambda paths: {"PUB-a-000000000001": _Record(), "PUB-b-000000000002": _Record()},
    )
    monkeypatch.setattr(
        dev_shell, "load_publication_events", lambda paths: [_Event("PUB-a-000000000001")]
    )
    assert dev_shell.pending_publications(site) == ["PUB-b-000000000002"]


def test_a_candidate_a_preview_already_serves_does_not_claim_a_second_port(site, tmp_path):
    """One root per topic per tree, or a hundred waiting candidates exhaust the ports.

    The review card links into the preview, and ``verify-candidate`` is what proves the
    bundle reproduces those bytes — so a second server for the same page buys nothing.
    """
    root = tmp_path / "review"
    body = "<html>读我</html>"
    _page(root, "zh-CN", "aabb-river-light-2026", body)

    class _Bundle:
        locale = "zh-CN"
        page_hash = bytes_digest(body.encode("utf-8"))

    dev_shell.write_review_manifest(
        root,
        topic_id="aabb-river-light-2026",
        page_run_id="rl-20260825153200000001-a1100001",
        theme_token="ember",
        locales=["zh-CN"],
        bundles=[_Bundle()],
    )
    assert dev_shell._hashes_in_previews([root]) == {_Bundle.page_hash}

    # A preview that serves other bytes leaves the candidate its own port.
    other = tmp_path / "other"
    _page(other, "zh-CN", "aabb-garden-wind-2026", "<html>别的</html>")
    assert _Bundle.page_hash not in dev_shell._hashes_in_previews([other])


def test_roots_are_discovered_in_a_stable_order(site, tmp_path):
    production = tmp_path / "public"
    production.mkdir()
    preview = tmp_path / "review"
    preview.mkdir()
    roots = dev_shell.discover_roots(site, production, [preview], 8787, candidate_ids=[])
    assert [root.kind for root in roots] == ["production", "preview"]
    again = dev_shell.discover_roots(site, production, [preview], 8787, candidate_ids=[])
    assert [root.key for root in again] == [root.key for root in roots]


def test_a_port_held_by_something_else_moves_one_root_not_the_whole_shell(tmp_path):
    import socket

    held = socket.socket()
    held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    busy = held.getsockname()[1]
    try:
        server, following = dev_shell._bind_upward(tmp_path, busy)
        try:
            assert server.server_port > busy
            assert following == server.server_port + 1
        finally:
            server.shutdown()
            server.server_close()
    finally:
        held.close()


def test_the_dashboard_never_injects_itself_into_a_reviewed_page(site, tmp_path):
    root = tmp_path / "review"
    body = "<html><body>只有内容</body></html>"
    _page(root, "zh-CN", "aabb-river-light-2026", body)
    _topic_manifest(tmp_path / "topics", "aabb-river-light-2026")
    write_chrome_assets(root)
    served = dev_shell.discover_roots(site, tmp_path / "missing", [root], 8900, candidate_ids=[])
    state = dev_shell.collect_state(
        repo_root=tmp_path,
        topics_root=tmp_path / "topics",
        site_paths=site,
        production_dir=tmp_path / "missing",
        roots=served,
    )
    page = dev_shell.render_dashboard(state)
    # The approve control is in the dashboard, and the reviewed file is untouched.
    assert "data-approve-release" in page
    assert (root / "zh-CN" / "topics" / "aabb-river-light-2026" / "index.html").read_text(
        encoding="utf-8"
    ) == body


def test_a_review_row_states_the_consequence_before_and_after_the_click(site, tmp_path):
    """The defect this replaced: a bare prompt and a toast that vanished after 6 seconds.

    A reviewer could not tell whether anything had happened, or what it would lead to.
    """
    root = tmp_path / "review"
    body = "<html>读我</html>"
    _page(root, "zh-CN", "aabb-river-light-2026", body)
    _topic_manifest(tmp_path / "topics", "aabb-river-light-2026")

    class _Bundle:
        locale = "zh-CN"
        page_hash = bytes_digest(body.encode("utf-8"))

    dev_shell.write_review_manifest(
        root,
        topic_id="aabb-river-light-2026",
        page_run_id="rl-20260825153200000001-a1100001",
        theme_token="ember",
        locales=["en", "zh-CN"],
        bundles=[_Bundle()],
    )
    roots = dev_shell.discover_roots(site, tmp_path / "missing", [root], 8900, candidate_ids=[])

    def dashboard():
        state = dev_shell.collect_state(
            repo_root=tmp_path,
            topics_root=tmp_path / "topics",
            site_paths=site,
            production_dir=tmp_path / "missing",
            roots=roots,
        )
        return dev_shell.render_dashboard(state)

    before = dashboard()
    # Before the click: both records it writes, and the machine check it does not bypass.
    assert "PublicationReview" in before and "HumanApproval" in before
    assert ZH["confirm_not_immediate"] in before
    assert "verify-candidate" in before
    assert "rl-20260825153200000001-a1100001" in before
    assert '<div class="done">' not in before
    assert "data-approve-release data-topic=" in before

    dev_shell.record_release_approval(
        site,
        topic_id="aabb-river-light-2026",
        pages=[{"locale": "zh-CN", "page_hash": _Bundle.page_hash}],
        reviewer_locale="zh-CN",
        reason="读完了，可以发。",
        reviewer_id="founder",
        decided_at=DECIDED,
    )
    after = dashboard()
    # After it, and on every later load: the decision is still visible on the card.
    assert '<div class="done">' in after
    assert "activate-intent-aabb-river-light-2026-" in after
    assert "data-approve-release data-topic=" not in after


def test_a_preview_whose_bytes_are_already_live_offers_no_decision(site, tmp_path):
    """The review root outlives the release; the card must not outlive the question.

    After ``activate`` the same preview directory is still registered and still serves the
    same bytes.  Offering "approve and ship" there invites a supersede of a publication by
    itself — the one operation ``activate`` refuses outright.
    """
    live_hash = "sha256:" + "a" * 64

    class _Bundle:
        locale = "zh-CN"
        page_hash = live_hash

    class _Record:
        locales = [_Bundle()]

    rows = dev_shell._releases(
        site,
        previews=[
            {
                "key": "preview:review",
                "pages": [
                    {
                        "topic_id": "aabb-river-light-2026",
                        "locale": "zh-CN",
                        "page_hash": live_hash,
                        "url": "http://127.0.0.1:9001/zh-CN/topics/aabb-river-light-2026/",
                        "approved_path": "",
                        "page_run_id": "rl-1",
                        "theme_token": "ember",
                    }
                ],
            }
        ],
        candidates=[],
        live_by_topic={"aabb-river-light-2026": "PUB-aabb-river-light-2026-0123456789ab"},
        publications={"PUB-aabb-river-light-2026-0123456789ab": _Record()},
        titles={"aabb-river-light-2026": "签证收紧"},
        reviewer_locales={"aabb-river-light-2026": "zh-CN"},
    )
    (row,) = rows
    assert row["live"] is True
    card = dev_shell._release_cards(rows)
    assert ZH["tag_live"] in card
    assert "data-approve-release" not in card


def test_release_row_takes_its_review_locale_from_the_preview_record(site):
    """An imported submission renders from its own namespace.

    Nothing about it is under the repo's ``topics/``, so the scan that builds
    ``reviewer_locales`` has no row for it and the card would refuse every approval with
    "this scope names no review language" — about a manifest that names one.  The
    preview's own record carries the fact and wins; a preview written before the field
    existed still falls back to the scan.
    """
    def _pages(review_locale):
        return [
            {
                "topic_id": "aabb-river-light-2026",
                "locale": locale,
                "page_hash": "sha256:" + char * 64,
                "url": f"http://127.0.0.1:9001/{locale}/topics/aabb-river-light-2026/",
                "approved_path": "",
                "page_run_id": "rl-1",
                "theme_token": "ember",
                "review_locale": review_locale,
            }
            for locale, char in (("en", "a"), ("zh-CN", "b"))
        ]

    def _row(pages, reviewer_locales):
        rows = dev_shell._releases(
            site,
            previews=[{"key": "preview:review", "pages": pages}],
            candidates=[],
            live_by_topic={},
            publications={},
            titles={"aabb-river-light-2026": "签证收紧"},
            reviewer_locales=reviewer_locales,
        )
        assert len(rows) == 1
        return rows[0]

    # The topic is absent from the repo scan, exactly as an imported submission is.
    row = _row(_pages("zh-CN"), {})
    assert row["reviewer_locale"] == "zh-CN"
    assert row["reviewer_locale_problem"] == ""
    assert row["reviewed_hash"] == "sha256:" + "b" * 64

    # No record (a preview rendered before the field existed): the scan still answers.
    row = _row(_pages(""), {"aabb-river-light-2026": "en"})
    assert row["reviewer_locale"] == "en"
    assert row["reviewer_locale_problem"] == ""

    # Neither source knows: refuse rather than guess a rendering to bind the approval to.
    assert _row(_pages(""), {})["reviewer_locale_problem"] == "no_review_locale"


def test_release_card_locale_plan_renders_in_every_halo_locale(site):
    """The language checkboxes/tags must not ``KeyError`` in any of the halo's
    nine — a missing key here only shows up once a reviewer switches the dashboard
    language."""
    rows = dev_shell._releases(
        site,
        previews=[
            {
                "key": "preview:review",
                "pages": [
                    {
                        "topic_id": "aabb-river-light-2026",
                        "locale": "en",
                        "page_hash": "sha256:" + "a" * 64,
                        "url": "http://127.0.0.1:9001/en/topics/aabb-river-light-2026/",
                        "approved_path": "",
                        "page_run_id": "rl-1",
                        "theme_token": "ember",
                    },
                    {
                        "topic_id": "aabb-river-light-2026",
                        "locale": "zh-CN",
                        "page_hash": "sha256:" + "b" * 64,
                        "url": "http://127.0.0.1:9001/zh-CN/topics/aabb-river-light-2026/",
                        "approved_path": "",
                        "page_run_id": "rl-1",
                        "theme_token": "ember",
                    },
                ],
            }
        ],
        candidates=[],
        live_by_topic={},
        publications={},
        titles={"aabb-river-light-2026": "签证收紧"},
        reviewer_locales={"aabb-river-light-2026": "zh-CN"},
    )
    for code in HALO_LOCALE_CODES:
        card = dev_shell._release_cards(rows, locale=code)
        strings = dashboard_strings(code)
        assert strings["locale_plan_heading"] in card
        assert strings["locale_included_tag"] in card
        # The candidate's own locales (en, zh-CN) are read-only, never checkboxes.
        assert 'data-locale-choice value="en"' not in card
        assert 'data-locale-choice value="zh-CN"' not in card
        # Every other halo locale offers a checkbox to add it to the plan.
        for extra in HALO_LOCALE_CODES:
            if extra in ("en", "zh-CN"):
                continue
            assert f'data-locale-choice value="{extra}"' in card


def test_the_production_section_is_an_entry_point_not_a_copy_of_the_index(site, tmp_path):
    """The dashboard must not grow with the site.

    Listing every live topic here makes the dashboard grow with the site and duplicates
    something the production site already answers better.  A link and a count do not.
    """
    production = tmp_path / "public"
    for topic_id in ("aabb-river-light-2026", "aabb-garden-wind-2026"):
        _page(production, "zh-CN", topic_id, f"<html>{topic_id}</html>")
        _page(production, "en", topic_id, f"<html>{topic_id}</html>")
    roots = dev_shell.discover_roots(site, production, [], 8900, candidate_ids=[])
    state = dev_shell.collect_state(
        repo_root=tmp_path,
        topics_root=tmp_path / "topics",
        site_paths=site,
        production_dir=production,
        roots=roots,
    )
    assert state["production"]["topic_count"] == 2
    assert state["production"]["page_count"] == 4
    page = dev_shell.render_dashboard(state)
    section = page.split(ZH["section_production"])[1].split("<h2>")[0]
    assert ZH["topic_count_page_count"].format(topics=2, pages=4) in section
    assert ZH["open_production"] in section
    # The per-topic list is what must not be here.
    assert "aabb-river-light-2026" not in section
    assert "aabb-garden-wind-2026" not in section


def test_touchpoint_one_comes_before_touchpoint_two_and_hides_what_is_signed(site, tmp_path):
    """A signed scope needs no second approval, so it is not a row.

    It stays as a count, because "nothing is waiting" and "nothing exists" are different
    answers and the dashboard must not merge them.
    """
    state = {
        "release": {},
        "chrome": {"version": "chrome-1.4.0"},
        "production": {"origin": "", "path": "", "topic_count": 0, "page_count": 0, "pages": []},
        "releases": [],
        "scope": [
            {"topic_id": "aabb-river-light-2026", "state": "signed", "title": "签过的"},
            {"topic_id": "aabb-garden-wind-2026", "state": "unsigned", "title": "还没签的",
             "detail": "缺 scope_approval", "candidates": False},
        ],
        "generated_at": "2026-08-27T18:00:00+00:00",
    }
    page = dev_shell.render_dashboard(state)
    assert page.index(ZH["section_scope"]) < page.index(ZH["section_release"])
    section = page.split(ZH["section_scope"])[1].split("<h2>")[0]
    assert "还没签的" in section
    assert "签过的" not in section
    assert ZH["scope_more_signed"].format(n=1) in section


def test_touchpoint_one_reads_candidate_text_from_multilang_values():
    """Which authored language is shown is asked for, never assumed.

    The scope sheet is read by whoever is holding the sitting, so the caller names the
    languages that reader wants — the dashboard's own, then the topic's review language.
    With nothing named, the English pivot is what is left, not one operator's language.
    """
    both = {"values": {"en": "What changed?", "zh-CN": "发生了什么变化？"}}
    assert dev_shell._candidate_review_label(both, ("zh-CN",)) == "发生了什么变化？"
    assert dev_shell._candidate_review_label(both, ("ja", "zh-CN")) == "发生了什么变化？"
    assert dev_shell._candidate_review_label(both) == "What changed?"
    assert dev_shell._candidate_review_label(
        {"values": {"en": "What changed?"}}, ("zh-CN",)
    ) == "What changed?"


# ---------------------------------------------------------------------------------- ports


def _free_ephemeral_port() -> int:
    """A port nothing holds right now, picked by the OS — never 8787-8800."""
    import socket

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _hold_port():
    """Occupy a real, OS-assigned loopback port for the life of the returned socket."""
    import socket

    held = socket.socket()
    held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    return held


def _run_dev_serve_once(site, tmp_path, *, base_port: int, port_explicit: bool):
    return dev_shell.run_dev_shell(
        repo_root=tmp_path,
        topics_root=tmp_path / "topics",
        site_root=site.root,
        production_dir=tmp_path / "missing-production",
        preview_dirs=[],
        reviewer_id="founder",
        base_port=base_port,
        port_explicit=port_explicit,
        once=True,
    )


def test_default_port_is_used_when_free(site, tmp_path):
    """No --port, and nothing is on the port dev-serve would pick: it binds it as-is."""
    base = _free_ephemeral_port()
    context = _run_dev_serve_once(site, tmp_path, base_port=base, port_explicit=False)
    assert context.base_port == base


def test_default_port_probes_upward_when_the_base_is_busy(site, tmp_path):
    """A second review session must not crash — it takes the next free block."""
    held = _hold_port()
    busy = held.getsockname()[1]
    try:
        context = _run_dev_serve_once(site, tmp_path, base_port=busy, port_explicit=False)
        assert context.base_port != busy
        assert context.base_port > busy
        assert context.base_port <= busy + dev_shell.PORT_SEARCH_SPAN
    finally:
        held.close()


def test_explicit_port_on_an_occupied_port_fails_loudly_and_is_not_moved(site, tmp_path):
    """An explicit --port is the operator's own choice, so a clash is
    theirs to fix — dev-serve must never silently pick a different port instead."""
    held = _hold_port()
    busy = held.getsockname()[1]
    try:
        with pytest.raises(ArtifactError, match="explicit"):
            _run_dev_serve_once(site, tmp_path, base_port=busy, port_explicit=True)
    finally:
        held.close()


def test_the_dashboard_has_no_stage_six_section_and_no_route_to_one(site, tmp_path):
    """The dashboard offers no stage-6 preview listing and no route to one.

    Two things you can open, side by side, one of which cannot be approved, is a question
    the dashboard was asking and then answering in a footnote.  The stage-6 preview is an
    intermediate artifact of the render-localize run; touchpoint two happens on the
    candidate, which is what section three serves.  So the listing and its route are gone
    and the previews stay on disk where ``docs/artifact_versioning.md`` §7 keeps them.
    """
    state = {
        "release": {},
        "chrome": {"version": "chrome-1.4.0"},
        "production": {"origin": "", "path": "", "topic_count": 0, "page_count": 0, "pages": []},
        "releases": [],
        "scope": [],
        "generated_at": "2026-08-27T18:00:00+00:00",
    }
    page = dev_shell.render_dashboard(state)
    assert "编辑期预览" not in page
    assert "/previews/" not in page
    assert not hasattr(dev_shell, "resolve_preview")
    assert not hasattr(dev_shell, "PREVIEW_ROUTE")


def test_the_review_card_carries_the_proposed_categories(tmp_path):
    """Touchpoint two covers the taxonomy too — the user should never be asked after.

    Measured on aabb-market-meal-2024: the category was settled in a separate question after the
    page had already been approved, which is a second decision about something the user
    was never shown while reading.
    """
    from newsab_publish.dev_shell import read_review_manifest, write_review_manifest

    class _Bundle:
        def __init__(self, locale, page_hash):
            self.locale, self.page_hash = locale, page_hash

    root = tmp_path / "review"
    root.mkdir()
    write_review_manifest(
        root,
        topic_id="aabb-river-light-2026",
        page_run_id="rl-20260828000000000000-0000abcd",
        theme_token="ember",
        locales=["zh-CN"],
        bundles=[_Bundle("zh-CN", "sha256:" + "a" * 64)],
        categories=["world-affairs", "society-policy"],
    )
    entry = read_review_manifest(root)["aabb-river-light-2026"]
    assert entry["categories"] == ["world-affairs", "society-policy"]


def test_one_confirmation_also_settles_the_taxonomy(tmp_path):
    from newsab_publish.dev_shell import record_release_approval

    site_paths = SitePaths.at(tmp_path / "site").ensure()
    page_hash = "sha256:" + "b" * 64
    result = record_release_approval(
        site_paths,
        topic_id="aabb-river-light-2026",
        pages=[{"locale": "zh-CN", "page_hash": page_hash}],
        reviewer_locale="zh-CN",
        reason="lgtm",
        reviewer_id="founder",
        categories=["world-affairs", "society-policy"],
    )
    written = " ".join(str(x) for x in (result.get("written") or result.values()))
    target = (
        site_paths.private_dir / "approvals"
        / f"topic-categories-aabb-river-light-2026-{page_hash[7:15]}.json"
    )
    assert target.is_file(), written
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["reviewer_id"] == "founder"
    assert payload["decision"] == "approved"
    assert payload["category_ids"] == ["world-affairs", "society-policy"]


def test_approve_release_endpoint_writes_a_real_locale_plan_end_to_end(site, tmp_path):
    """Approving a candidate with extra languages checked writes a
    real, schema-validated ``LocalePlan`` on disk through the whole dev-serve HTTP path
    — no mocking of the record writer."""
    from newsab_schema.models.publication import LocalePlan

    class Context:
        repo_root = tmp_path
        site_paths = site
        reviewer_id = "founder"

        @staticmethod
        def state():
            return {
                "releases": [
                    {
                        "topic_id": "aabb-river-light-2026",
                        "preview_key": "preview:review",
                        "locales": [
                            {"locale": "en", "page_hash": "sha256:" + "a" * 64},
                            {"locale": "zh-CN", "page_hash": "sha256:" + "b" * 64},
                        ],
                        "reviewer_locale": "zh-CN",
                        "publication_id": "",
                        "categories": [],
                    }
                ]
            }

    handler = object.__new__(dev_shell.DashboardHandler)
    handler.context = Context()
    result = handler._approve_release(
        {
            "topic_id": "aabb-river-light-2026",
            "preview_key": "preview:review",
            "reason": "扩两语先做起来",
            "add_locales": ["ru", "ja"],
        }
    )
    plan_path = tmp_path / result["locale_plan"]
    assert plan_path.is_file()
    plan = LocalePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    assert plan.topic_id == "aabb-river-light-2026"
    assert plan.included_locales == ["en", "zh-CN"]
    assert plan.target_locales == ["en", "ja", "ru", "zh-CN"]
    assert plan.reason.text == "扩两语先做起来"
    assert plan.reviewer_id == "founder"
    # The sibling review and lifecycle-intent records land too, from the same click.
    assert (tmp_path / result["authorization"]).is_file()
    for review_path in result["reviews"]:
        assert (tmp_path / review_path).is_file()


def test_approve_release_endpoint_passes_the_categories_shown_on_the_card(
    site, tmp_path, monkeypatch
):
    """The HTTP boundary must not drop the proposal before the record writer sees it."""
    captured = {}

    def fake_record(site_paths, **kwargs):
        captured.update(kwargs)
        return {
            "authorization": str(tmp_path / "authorization.json"),
            "reviews": [str(tmp_path / "review.json")],
            "publication_id": "",
            "page_hash": "sha256:" + "a" * 64,
            "locale_plan": str(tmp_path / "locale-plan.json"),
            "target_locales": ["en", "zh-CN"],
        }

    monkeypatch.setattr(dev_shell, "record_release_approval", fake_record)

    class Context:
        repo_root = tmp_path
        site_paths = site
        reviewer_id = "founder"

        @staticmethod
        def state():
            return {
                "releases": [
                    {
                        "topic_id": "aabb-river-light-2026",
                        "preview_key": "preview:review",
                        "locales": [
                            {
                                "locale": "zh-CN",
                                "page_hash": "sha256:" + "a" * 64,
                            }
                        ],
                        "reviewer_locale": "zh-CN",
                        "publication_id": "",
                        "categories": ["world-affairs", "society-policy"],
                    }
                ]
            }

    handler = object.__new__(dev_shell.DashboardHandler)
    handler.context = Context()
    handler._approve_release(
        {
            "topic_id": "aabb-river-light-2026",
            "preview_key": "preview:review",
            "reason": "lgtm",
            "add_locales": ["ru", "fr"],
        }
    )
    assert captured["categories"] == ["world-affairs", "society-policy"]
    assert captured["add_locales"] == ["ru", "fr"]


def test_private_panels_exist_only_when_a_script_generated_them(site):
    """The dashboard knows no specific panel — a checkout that generated none
    (a public clone, a fresh machine) has no section, no route target, no hint."""
    assert dev_shell.private_panels(site) == []
    state = {
        "release": {},
        "chrome": {"version": "chrome-1.4.0"},
        "production": {"origin": "", "path": "", "topic_count": 0, "page_count": 0, "pages": []},
        "releases": [],
        "scope": [],
        "panels": [],
        "generated_at": "2026-09-01T18:00:00+00:00",
    }
    assert ZH["section_panels"] not in dev_shell.render_dashboard(state)

    panels_dir = site.private_dir / dev_shell.PANELS_DIR
    panels_dir.mkdir(parents=True)
    (panels_dir / "suggestion-review.html").write_text("<html>面板</html>", encoding="utf-8")
    (panels_dir / "notes.txt").write_text("not a panel", encoding="utf-8")
    (panels_dir / ".hidden.html").write_text("not listed", encoding="utf-8")
    panels = dev_shell.private_panels(site)
    assert [panel["name"] for panel in panels] == ["suggestion-review.html"]
    page = dev_shell.render_dashboard(state | {"panels": panels})
    assert ZH["section_panels"] in page
    assert "/panels/suggestion-review.html" in page


def test_the_panel_route_serves_panels_and_nothing_else(site, tmp_path):
    """The route pattern is the whole guard: flat name, .html, inside panels/ only."""
    import urllib.error
    import urllib.request

    from newsab_publish.static_server import make_handler, serve_forever_in_thread

    panels_dir = site.private_dir / dev_shell.PANELS_DIR
    panels_dir.mkdir(parents=True)
    (panels_dir / "suggestion-review.html").write_text("<html>面板字节</html>", encoding="utf-8")
    (site.private_dir / "secret.json").write_text("{}", encoding="utf-8")
    context = dev_shell.DevShellContext(
        repo_root=tmp_path,
        topics_root=tmp_path / "topics",
        site_paths=site,
        production_dir=tmp_path / "missing-production",
        preview_dirs=[],
        reviewer_id="founder",
        base_port=0,
    )
    handler = make_handler({}, dev_shell.DashboardHandler)
    handler.context = context
    server = serve_forever_in_thread(
        tmp_path, _free_ephemeral_port(), handler_factory=lambda: handler
    )
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(f"{base}/panels/suggestion-review.html") as response:
            assert "面板字节" in response.read().decode("utf-8")
        for refused in (
            "/panels/secret.json",
            "/panels/%2e%2e/secret.json",
            "/panels/sub/dir.html",
            "/panels/",
        ):
            with pytest.raises(urllib.error.HTTPError):
                urllib.request.urlopen(base + refused)
    finally:
        server.shutdown()
        server.server_close()


def test_a_panel_decision_is_recorded_append_only_and_validated(site):
    """The dashboard remembers what the human chose; it executes nothing."""
    panels_dir = site.private_dir / dev_shell.PANELS_DIR
    panels_dir.mkdir(parents=True)
    (panels_dir / "suggestion-review.html").write_text("<html>面板</html>", encoding="utf-8")

    first = dev_shell.record_panel_decision(
        site,
        panel="suggestion-review.html",
        item_id="sg_" + "a" * 32,
        decision="shortlisted",
        reason="editorial_fit",
    )
    undo = dev_shell.record_panel_decision(
        site, panel="suggestion-review.html", item_id="sg_" + "a" * 32, decision="pending"
    )
    target = pathlib.Path(first["path"])
    assert target == pathlib.Path(undo["path"])
    assert target.name == "suggestion-review.decisions.jsonl"
    lines = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert [line["decision"] for line in lines] == ["shortlisted", "pending"]

    for bad in (
        {"panel": "../secret.html", "item_id": "x", "decision": "spam"},
        {"panel": "missing.html", "item_id": "x", "decision": "spam"},
        {"panel": "suggestion-review.html", "item_id": "../x", "decision": "spam"},
        {"panel": "suggestion-review.html", "item_id": "x", "decision": "Spam!"},
        {"panel": "suggestion-review.html", "item_id": "x", "decision": "spam",
         "reason": "Not A Code"},
    ):
        with pytest.raises(ArtifactError):
            dev_shell.record_panel_decision(site, **bad)


def test_the_panel_decision_route_reaches_the_recorder(site, tmp_path):
    import urllib.request

    from newsab_publish.static_server import make_handler, serve_forever_in_thread

    panels_dir = site.private_dir / dev_shell.PANELS_DIR
    panels_dir.mkdir(parents=True)
    (panels_dir / "suggestion-review.html").write_text("<html>面板</html>", encoding="utf-8")
    context = dev_shell.DevShellContext(
        repo_root=tmp_path,
        topics_root=tmp_path / "topics",
        site_paths=site,
        production_dir=tmp_path / "missing-production",
        preview_dirs=[],
        reviewer_id="founder",
        base_port=0,
    )
    handler = make_handler({}, dev_shell.DashboardHandler)
    handler.context = context
    server = serve_forever_in_thread(
        tmp_path, _free_ephemeral_port(), handler_factory=lambda: handler
    )
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/panel-decision",
            data=json.dumps(
                {
                    "panel": "suggestion-review.html",
                    "item_id": "sg_" + "b" * 32,
                    "decision": "declined",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["record"]["decision"] == "declined"
        recorded = (panels_dir / "suggestion-review.decisions.jsonl").read_text("utf-8")
        assert ("sg_" + "b" * 32) in recorded
    finally:
        server.shutdown()
        server.server_close()


def test_recorded_panel_decisions_can_be_read_back_for_hydration(site):
    """The panel is static bytes; a reload asks this reader for the recorded state."""
    panels_dir = site.private_dir / dev_shell.PANELS_DIR
    panels_dir.mkdir(parents=True)
    (panels_dir / "suggestion-review.html").write_text("<html>面板</html>", encoding="utf-8")
    assert dev_shell.latest_panel_decisions(site, "suggestion-review.html") == {}
    dev_shell.record_panel_decision(
        site, panel="suggestion-review.html", item_id="sg_" + "c" * 32,
        decision="converted",
    )
    dev_shell.record_panel_decision(
        site, panel="suggestion-review.html", item_id="sg_" + "c" * 32,
        decision="pending",
    )
    latest = dev_shell.latest_panel_decisions(site, "suggestion-review.html")
    assert latest["sg_" + "c" * 32]["decision"] == "pending"  # last decision wins
    with pytest.raises(ArtifactError, match="no such panel"):
        dev_shell.latest_panel_decisions(site, "missing.html")
    with pytest.raises(ArtifactError, match="invalid panel name"):
        dev_shell.latest_panel_decisions(site, "../x.html")


# ---------------------------------------------------------------------------------- i18n


def _minimal_dashboard_state() -> dict:
    return {
        "release": {},
        "chrome": {"version": "chrome-1.4.0"},
        "production": {"origin": "", "path": "", "topic_count": 0, "page_count": 0, "pages": []},
        "releases": [],
        "scope": [],
        "panels": [],
        "generated_at": "2026-09-02T18:00:00+00:00",
    }


def test_dashboard_strings_cover_exactly_the_halo_nine_symmetrically():
    """The dashboard's own table (independent of the reader-facing site_strings.py)
    commits to the same nine languages the home page's halo does — not more, not fewer."""
    from newsab_publish.dashboard_strings import _STRINGS

    assert set(_STRINGS) == set(HALO_LOCALE_CODES)
    expected_keys = set(ZH)
    for locale in HALO_LOCALE_CODES:
        assert set(dashboard_strings(locale)) == expected_keys, locale


def test_the_dashboard_renders_every_halo_locale_with_the_right_lang_and_dir():
    for code in HALO_LOCALE_CODES:
        page = dev_shell.render_dashboard(_minimal_dashboard_state(), locale=code)
        strings = dashboard_strings(code)
        assert strings["section_production"] in page
        assert f'dir="{"rtl" if code == "ar" else "ltr"}"' in page


def test_an_unrecognized_or_missing_locale_falls_back_to_the_default():
    assert dev_shell.resolve_ui_locale(None) == "zh-CN"
    assert dev_shell.resolve_ui_locale("") == "zh-CN"
    assert dev_shell.resolve_ui_locale("xx-YY") == "zh-CN"
    assert dev_shell.resolve_ui_locale("not a locale at all") == "zh-CN"
    # A recognized code is honored, in its normalized casing.
    assert dev_shell.resolve_ui_locale("fr") == "fr"
    assert dev_shell.resolve_ui_locale("zh-cn") == "zh-CN"


def test_the_theme_and_language_buttons_render_with_every_halo_endonym():
    """The top-right controls: a theme toggle and a language menu listing all
    nine halo locales by their own endonym, with the current one marked."""
    page = dev_shell.render_dashboard(_minimal_dashboard_state(), locale="ko")
    assert 'id="themebtn"' in page
    assert 'id="langbtn"' in page
    assert 'id="langmenu"' in page
    for entry_locale in HALO_LOCALE_CODES:
        assert f'data-locale="{entry_locale}"' in page
    # The endonym text itself appears (Korean's own name for itself), not an English name.
    assert "한국어" in page
    assert 'class="on"' in page  # the current locale's menu item is marked


def test_theme_and_language_preferences_persist_through_one_localstorage_key():
    """Both buttons read/write the same ``localStorage`` key, mirroring the
    reader page's own ``newsab.prefs`` pattern in ``render/script.py``."""
    page = dev_shell.render_dashboard(_minimal_dashboard_state())
    assert "newsab.dashboardPrefs" in page
    assert "writePrefs({theme:next})" in page
    assert "writePrefs({locale:picked})" in page
    # The early inline script (before the stylesheet paints) applies a stored theme and
    # redirects to a stored locale before first render, so neither ever flashes wrong.
    assert page.index("newsab.dashboardPrefs") < page.index("<style>")


def test_scope_form_html_localizes_its_chrome_but_not_the_scope_content(tmp_path):
    """The form's headings/buttons follow the dashboard locale; the manifest's own
    content (group labels, include/exclude items) is untouched — it is not dashboard
    chrome, it is the topic's own scope, authored in whatever languages it was."""
    topic_id = "aabb-river-light-2026"
    _topic_manifest(tmp_path, topic_id)

    fr = dashboard_strings("fr")
    html_fr = dev_shell.scope_form_html(tmp_path, topic_id, locale="fr")
    assert fr["form_groups"] in html_fr
    assert fr["form_include"] in html_fr
    assert fr["form_submit"] in html_fr
    assert fr["form_ongoing"] in html_fr  # period.end is unset
    assert "test scope item" in html_fr  # scope content stays as authored, not translated

    html_default = dev_shell.scope_form_html(tmp_path, topic_id)
    assert ZH["form_groups"] in html_default
    assert "test scope item" in html_default


def test_scope_form_endpoint_threads_the_locale_query_parameter(site, tmp_path):
    """``/api/scope-form``: the same locale the page itself is showing."""
    topic_id = "aabb-river-light-2026"
    topics_root = tmp_path / "topics"
    _topic_manifest(topics_root, topic_id)

    context = dev_shell.DevShellContext(
        repo_root=tmp_path,
        topics_root=topics_root,
        site_paths=site,
        production_dir=tmp_path / "missing-production",
        preview_dirs=[],
        reviewer_id="founder",
        base_port=0,
    )
    handler = object.__new__(dev_shell.DashboardHandler)
    handler.context = context
    handler.path = f"/api/scope-form?topic_id={topic_id}&locale=ja"
    captured = {}
    handler._json = lambda payload, status=200: captured.update(payload)
    handler._scope_form()
    assert "error" not in captured
    assert dashboard_strings("ja")["form_groups"] in captured["html"]


# -------------------------------------------------------------- whose language reviews


def _reviewable(tmp_path, site, *, review_locale, page_locales):
    """One preview root plus the scope behind it, ready for a release card."""
    root = tmp_path / "review"
    topic_id = "aabb-river-light-2026"
    bundles = []
    for locale in page_locales:
        body = f"<html>{locale}</html>"
        _page(root, locale, topic_id, body)
        bundles.append(
            type("_B", (), {"locale": locale, "page_hash": bytes_digest(body.encode("utf-8"))})
        )
    _topic_manifest(tmp_path / "topics", topic_id, review_locale=review_locale)
    dev_shell.write_review_manifest(
        root,
        topic_id=topic_id,
        page_run_id="rl-20260825153200000001-a1100001",
        theme_token="ember",
        locales=list(page_locales),
        bundles=bundles,
    )
    roots = dev_shell.discover_roots(site, tmp_path / "missing", [root], 8900, candidate_ids=[])
    state = dev_shell.collect_state(
        repo_root=tmp_path,
        topics_root=tmp_path / "topics",
        site_paths=site,
        production_dir=tmp_path / "missing",
        roots=roots,
    )
    return state, {b.locale: b.page_hash for b in bundles}


def test_the_approval_is_keyed_to_whatever_language_the_reviewer_reads(site, tmp_path):
    """An operator who reviews in Japanese signs the Japanese rendering.

    Nothing here may fall back to the language this repo's own operator happens to read: the
    row, the hash the authorization binds, and the language the reviewer's own words are
    recorded as all come from the topic's ``review_locale``.
    """
    state, hashes = _reviewable(tmp_path, site, review_locale="ja", page_locales=["en", "ja"])
    (row,) = state["releases"]
    assert row["reviewer_locale"] == "ja"
    assert row["reviewer_locale_problem"] == ""
    assert row["reviewed_hash"] == hashes["ja"]
    assert "data-approve-release" in dev_shell._release_cards(state["releases"])

    result = dev_shell.record_release_approval(
        site,
        topic_id=row["topic_id"],
        pages=row["locales"],
        reviewer_locale=row["reviewer_locale"],
        reason="読みました。公開して構いません。",
        reviewer_id="founder",
        decided_at=DECIDED,
    )
    assert result["page_hash"] == hashes["ja"]
    approval = HumanApproval.model_validate_json(
        pathlib.Path(result["authorization"]).read_text(encoding="utf-8")
    )
    assert approval.note.lang == "ja"
    reviews = [
        PublicationReview.model_validate_json(
            pathlib.Path(item).read_text(encoding="utf-8")
        )
        for item in result["reviews"]
    ]
    assert {review.locale for review in reviews} == {"en", "ja"}
    assert {review.note.lang for review in reviews} == {"ja"}
    plan = json.loads(pathlib.Path(result["locale_plan"]).read_text(encoding="utf-8"))
    assert plan["reason"]["lang"] == "ja"


def test_a_scope_that_never_named_a_review_language_takes_no_approval(site, tmp_path):
    """A default here would key an approval to a rendering nobody read."""
    state, _ = _reviewable(tmp_path, site, review_locale=None, page_locales=["en", "zh-CN"])
    (row,) = state["releases"]
    assert row["reviewer_locale_problem"] == "no_review_locale"
    assert row["reviewed_hash"] == ""
    card = dev_shell._release_cards(state["releases"])
    assert "data-approve-release" not in card
    assert ZH["release_no_review_locale"] in card

    with pytest.raises(ArtifactError, match="review_locale is unset"):
        dev_shell.record_release_approval(
            site,
            topic_id=row["topic_id"],
            pages=row["locales"],
            reviewer_locale=row["reviewer_locale"],
            reason="总得能发吧。",
            reviewer_id="founder",
            decided_at=DECIDED,
        )


def test_a_candidate_missing_the_reviewers_own_language_says_so(site, tmp_path):
    """The other half of the same rule: the language is named, the rendering is absent."""
    state, _ = _reviewable(tmp_path, site, review_locale="ko", page_locales=["en", "zh-CN"])
    (row,) = state["releases"]
    assert row["reviewer_locale_problem"] == "review_locale_absent"
    card = dev_shell._release_cards(state["releases"])
    assert "data-approve-release" not in card
    assert ZH["release_review_locale_absent"].format(locale="ko") in card
