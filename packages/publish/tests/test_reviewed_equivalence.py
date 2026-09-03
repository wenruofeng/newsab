"""The one path where a publication may ship bytes the user did not literally sign.

``backfill-locales`` re-prepares an already-approved publication against the topic's
current editorial run so it ships a language the site has since learned.  Months later
and one renderer version on, the exact signed bytes no longer come back: the run says who
it is (a new run id, timestamp, producer, model) and the chrome around the article has
moved.  ``newsab_publish.reviewed_equivalence`` proves the approval still holds anyway —
identical content in every reviewed language, plus rendered bytes differing only inside a
closed whitelist — and these tests pin both halves of that, in both directions.

The negative case is the point of the whole exercise: a page run whose *body text* moved
by a single character must be refused, however small the edit and however much of the
page is otherwise identical.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

EXAMPLE_DIR = Path(__file__).resolve().parents[3] / "examples" / "synthetic-topic"
sys.path.insert(0, str(EXAMPLE_DIR))
import demo_fixture as fx  # noqa: E402

from newsab_publish import backfill
from newsab_publish.builder import (
    activate_publication,
    default_theme_registry_path,
    prepare_publication,
    render_candidate_bundle,
    resolve_inputs,
    verify_candidate,
)
from newsab_publish.metadata import SiteMetadata
from newsab_publish.reviewed_equivalence import (
    RULES,
    WHITELIST_VERSION,
    ContentBaseline,
    project_page,
    prove_byte_equivalence,
    redact,
)


def _bytes_baseline(html: str) -> ContentBaseline:
    """A baseline that still holds the signed bytes — the first-backfill shape."""
    return ContentBaseline(
        page={},
        page_run_id="rl-baseline",
        closure=(),
        data_assets=(),
        page_html=html.encode(),
    )
from newsab_publish.site_strings import SITE_LOCALES
from newsab_publish.themes import load_theme_registry, resolve_theme
from newsab_schema.artifacts import append_manifest, run_set_hash
from newsab_schema.io import ArtifactError
from newsab_schema.models.manifest import ManifestEntry
from newsab_schema.models.publication import HumanApproval, PublicationReview
from newsab_schema.paths import SitePaths, TopicPaths

BASE_URL = "https://example.org"
BUILD_DATE = date(2026, 9, 3)
#: The shape every real publication has: the writer's ``edt-`` run, then a
#: render-localize run that produced the bytes the user signed, then the expansion run
#: that adds a language.  The fixture's own page run is the *write* run, so the signed
#: render-localize run is staged here.
SIGNED_RUN_ID = "rl-20260901010203040506-abcdef11"
EXPANSION_RUN_ID = "rl-20260903010203040506-abcdef12"

#: A halo language the chrome already speaks and the site already ships, other than the
#: two the fixture page is written in — the language a backfill would be adding.
_SPARE_LOCALES = [
    locale for locale in SITE_LOCALES if locale not in ("en", "zh-CN")
]
EXTRA_LOCALE = _SPARE_LOCALES[0] if _SPARE_LOCALES else None
#: And one more, for the second backfill — the case where the record holding the signed
#: bytes has itself been superseded and the proof has to chain.
SECOND_EXTRA_LOCALE = _SPARE_LOCALES[1] if len(_SPARE_LOCALES) > 1 else None

pytestmark = pytest.mark.skipif(
    EXTRA_LOCALE is None,
    reason="the site ships only the fixture's two languages; nothing to backfill into",
)


# --------------------------------------------------------------------------------------
# a synthetic topic, published in two languages, then given an expansion run
# --------------------------------------------------------------------------------------


def _localize(node, locale: str, *, edit: str | None = None):
    """Copy every English value into ``locale`` — a stand-in for a localization run.

    ``edit`` appends one character to the first English *paragraph* it meets, which is
    how the negative case stages "the body text moved" without touching anything else.
    """
    state = {"edited": edit is None}

    def walk(value):
        if isinstance(value, dict):
            values = value.get("values")
            if set(value) == {"values"} and isinstance(values, dict) and "en" in values:
                english = values["en"]
                if not state["edited"] and len(english) > 40:
                    english = english + edit
                    state["edited"] = True
                out = dict(values)
                out["en"] = english
                out[locale] = english
                return {"values": out}
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(node)


def _render_localize_run(
    paths: TopicPaths,
    *,
    source_run: str,
    run_id: str,
    when: datetime,
    version: str,
    locale: str | None = None,
    edit: str | None = None,
) -> str:
    """One render-localize run over an existing page: same content, its own identity.

    ``locale`` adds a language (an expansion run); ``edit`` moves one character of body
    text, which is the defect the whole mechanism exists to catch.
    """
    page = json.loads(
        (paths.stage_run_dir("editorial", source_run) / "page.json").read_text(
            encoding="utf-8"
        )
    )
    if locale or edit:
        page = _localize(page, locale or "en", edit=edit)
    page["provenance"] = dict(page["provenance"])
    page["provenance"]["run_id"] = run_id
    page["provenance"]["skill_version"] = f"renderlocalize-{version}"
    page["provenance"]["timestamp"] = when.isoformat().replace("+00:00", "Z")
    run_dir = paths.stage_run_dir("editorial", run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "page.json").write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
    append_manifest(
        paths,
        ManifestEntry(
            skill_id="render-localize",
            skill_version=version,
            model_id="fixture-model",
            run_id=run_id,
            topic_id=fx.TOPIC_ID,
            stage="editorial",
            inputs=[source_run, fx.QA_RUN_ID, fx.CORPUS_RUN_ID],
            output_set_hash=run_set_hash(paths, "editorial", run_id),
            timestamp=when,
        ),
        activate_stage="editorial",
    )
    return run_id


def _signed_run(paths: TopicPaths) -> str:
    """The render-localize run whose bytes the reviewer signs at touchpoint two."""
    return _render_localize_run(
        paths,
        source_run=fx.PAGE_RUN_ID,
        run_id=SIGNED_RUN_ID,
        when=datetime(2026, 9, 1, 1, 2, 3, tzinfo=timezone.utc),
        version="0.20.0",
    )


def _expansion_run(
    paths: TopicPaths,
    locale: str,
    *,
    edit: str | None = None,
    source_run: str = SIGNED_RUN_ID,
    run_id: str = EXPANSION_RUN_ID,
    when: datetime = datetime(2026, 9, 3, 1, 2, 3, tzinfo=timezone.utc),
) -> str:
    """The later run that adds a language — a new run, so a new self-description."""
    return _render_localize_run(
        paths,
        source_run=source_run,
        run_id=run_id,
        when=when,
        version="0.21.0",
        locale=locale,
        edit=edit,
    )


@pytest.fixture
def topics_root(tmp_path):
    root = tmp_path / "topics"
    fx.build_topic(root)
    return root


@pytest.fixture
def narrow_metadata(tmp_path) -> tuple[SiteMetadata, Path]:
    """The site as it was when the user approved: the fixture's two languages."""
    path = tmp_path / "site_metadata_narrow.json"
    return fx.build_metadata(path), path


def _metadata_with(metadata: SiteMetadata, locales, path: Path):
    payload = metadata.model_dump(mode="json")
    payload["locales"] = list(locales)
    for category in payload["categories"]:
        for locale in locales:
            category["labels"].setdefault(locale, category["labels"]["en"])
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return SiteMetadata.model_validate(payload), path


@pytest.fixture
def wide_metadata(tmp_path, narrow_metadata) -> tuple[SiteMetadata, Path]:
    """The site after it learned one more language — what a backfill runs against."""
    metadata, _ = narrow_metadata
    return _metadata_with(
        metadata, ["en", "zh-CN", EXTRA_LOCALE], tmp_path / "site_metadata_wide.json"
    )


@pytest.fixture
def wider_metadata(tmp_path, narrow_metadata) -> tuple[SiteMetadata, Path]:
    """And a language after that — the second backfill, which has to chain."""
    metadata, _ = narrow_metadata
    if SECOND_EXTRA_LOCALE is None:
        pytest.skip("the site ships only one language beyond the fixture's two")
    return _metadata_with(
        metadata,
        ["en", "zh-CN", EXTRA_LOCALE, SECOND_EXTRA_LOCALE],
        tmp_path / "site_metadata_wider.json",
    )


@pytest.fixture
def published(topics_root, tmp_path, narrow_metadata):
    """One approved, live publication in the fixture's two languages."""
    metadata, metadata_path = narrow_metadata
    site_root = tmp_path / "site"
    signed_run = _signed_run(TopicPaths.for_topic(topics_root, fx.TOPIC_ID))
    resolved = resolve_inputs(topics_root, fx.TOPIC_ID, signed_run)
    theme = resolve_theme(None, load_theme_registry(default_theme_registry_path()))
    scratch = tmp_path / "scratch-review"
    scratch.mkdir()
    bundles, _, _ = render_candidate_bundle(
        resolved, metadata.locales, scratch, m2=True, theme=theme
    )
    review = PublicationReview(
        approval_id="APR-aabb-river-light-0123abcd",
        reviewer_id="test-founder",
        decided_at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
        locale=fx.REVIEW_LOCALE,
        page_hash=next(b.page_hash for b in bundles if b.locale == fx.REVIEW_LOCALE),
        reviewed_locales=list(metadata.locales),
    )
    record = prepare_publication(
        topics_root,
        site_root,
        fx.TOPIC_ID,
        page_run_id=signed_run,
        review=review,
        metadata=metadata,
        metadata_path=metadata_path,
    )
    activate_publication(
        topics_root,
        site_root,
        record.publication_id,
        approval=HumanApproval(
            approval_id="APR-aabb-river-light-1123abcd",
            reviewer_id="test-founder",
            decided_at=datetime(2026, 9, 1, 12, 5, tzinfo=timezone.utc),
        ),
        metadata=metadata,
        production_dir=site_root / "public",
        base_url=BASE_URL,
        build_date=BUILD_DATE,
    )
    return site_root, record


def _backfill(topics_root, site_root, wide_metadata):
    metadata, metadata_path = wide_metadata
    return backfill.backfill_locales(
        topics_root,
        site_root,
        metadata=metadata,
        metadata_path=metadata_path,
        production_dir=site_root / "public",
        base_url=BASE_URL,
        build_date=BUILD_DATE,
        reason=f"the site learned {EXTRA_LOCALE}",
    )


# --------------------------------------------------------------------------------------
# the positive case: same content, new run, one more language
# --------------------------------------------------------------------------------------


def test_backfill_accepts_an_expansion_run_and_records_the_proof(
    topics_root, published, wide_metadata
):
    site_root, original = published
    _expansion_run(TopicPaths.for_topic(topics_root, fx.TOPIC_ID), EXTRA_LOCALE)

    outcomes = _backfill(topics_root, site_root, wide_metadata)
    assert [o.status for o in outcomes] == ["superseded"], [o.detail for o in outcomes]

    from newsab_schema.store import load_publications

    new_id = outcomes[0].new_publication_id
    record = load_publications(SitePaths.at(site_root))[new_id]
    assert sorted(b.locale for b in record.locales) == sorted(
        ["en", "zh-CN", EXTRA_LOCALE]
    )
    proof = record.reviewed_equivalence
    assert proof is not None
    # The receipt is about *this* approval and *these* bytes, and says plainly that the
    # bytes are not the signed ones — that is what makes it a proof rather than a claim.
    assert proof.signed_page_hash == original.review.page_hash
    assert proof.signed_page_run_id == SIGNED_RUN_ID
    assert proof.candidate_page_hash != proof.signed_page_hash
    assert proof.whitelist_version == WHITELIST_VERSION
    # Only the run's own identity moved: the fixture's chrome and locale markers are the
    # same on both sides because the reviewed set is re-rendered as it was signed.
    assert set(proof.whitelisted_differences) <= {
        "provenance-lineage",
        "provenance-language-count",
        "content-direction",
        "stat-tooltip-wording",
    }
    assert "provenance-lineage" in proof.whitelisted_differences


def test_a_second_backfill_chains_onto_the_standing_proof(
    topics_root, published, wide_metadata, wider_metadata
):
    """The normal case from the second language onward.

    By then the publication holding the user's exact bytes has been superseded, so the
    proof is measured against the standing record — which is itself already proven
    equivalent to those bytes.  The digest carries through unchanged, which is exactly
    what makes the chain a proof rather than a hand-off.
    """
    site_root, original = published
    _expansion_run(TopicPaths.for_topic(topics_root, fx.TOPIC_ID), EXTRA_LOCALE)

    from newsab_schema.store import load_publications

    first = _backfill(topics_root, site_root, wide_metadata)
    assert [o.status for o in first] == ["superseded"], [o.detail for o in first]
    # The site learns a second language, so stage 6 localizes into it: another run again.
    _expansion_run(
        TopicPaths.for_topic(topics_root, fx.TOPIC_ID),
        SECOND_EXTRA_LOCALE,
        source_run=EXPANSION_RUN_ID,
        run_id="rl-20260904010203040506-abcdef13",
        when=datetime(2026, 9, 4, 1, 2, 3, tzinfo=timezone.utc),
    )
    second = _backfill(topics_root, site_root, wider_metadata)
    assert [o.status for o in second] == ["superseded"], [o.detail for o in second]

    publications = load_publications(SitePaths.at(site_root))
    before = publications[first[0].new_publication_id].reviewed_equivalence
    after = publications[second[0].new_publication_id].reviewed_equivalence
    assert sorted(
        b.locale for b in publications[second[0].new_publication_id].locales
    ) == sorted(["en", "zh-CN", EXTRA_LOCALE, SECOND_EXTRA_LOCALE])
    # Same approval, same redacted digest, all the way down the chain.
    assert after.signed_page_hash == original.review.page_hash
    assert after.redacted_digest == before.redacted_digest
    assert after.content_digest == before.content_digest
    verify_candidate(topics_root, site_root, second[0].new_publication_id)


def test_verify_candidate_replays_the_proof_without_the_superseded_bundle(
    topics_root, published, wide_metadata
):
    site_root, _ = published
    _expansion_run(TopicPaths.for_topic(topics_root, fx.TOPIC_ID), EXTRA_LOCALE)
    outcomes = _backfill(topics_root, site_root, wide_metadata)
    new_id = outcomes[0].new_publication_id

    # verify-candidate re-renders the reviewed set and re-derives the redacted digest;
    # it never reads the superseded publication, which is what makes the proof durable.
    verify_candidate(topics_root, site_root, new_id)
    verify_candidate(topics_root, site_root, new_id)


# --------------------------------------------------------------------------------------
# the negative case: one character of body text
# --------------------------------------------------------------------------------------


def test_backfill_refuses_a_page_run_whose_body_text_moved_by_one_character(
    topics_root, published, wide_metadata
):
    site_root, _ = published
    _expansion_run(TopicPaths.for_topic(topics_root, fx.TOPIC_ID), EXTRA_LOCALE, edit="x")

    outcomes = _backfill(topics_root, site_root, wide_metadata)
    assert [o.status for o in outcomes] == ["failed"]
    assert "changes approved content" in outcomes[0].detail
    assert "ordinary review path" in outcomes[0].detail
    # Nothing was published: the live publication is untouched.
    from newsab_schema.store import (
        derive_publish_selector,
        load_publication_events,
        load_publications,
    )
    from newsab_schema.models.manifest import file_digest

    site_paths = SitePaths.at(site_root)
    publications = load_publications(site_paths)
    selector = derive_publish_selector(
        publications,
        load_publication_events(site_paths),
        publication_hashes={
            pid: file_digest(site_paths.publication_record(pid)) for pid in publications
        },
    )
    live = publications[selector.publications[fx.TOPIC_ID]]
    assert [b.locale for b in live.locales] == ["en", "zh-CN"]


# --------------------------------------------------------------------------------------
# the whitelist itself: what it erases, and what it must never erase
# --------------------------------------------------------------------------------------


def test_the_whitelist_erases_only_what_it_names():
    signed = (
        '<html lang="en" data-site-locale="en">'
        '<link rel="alternate" hreflang="en" href="/en/topics/t/">'
        '<code class="prov-run">rl-1</code><span class="prov-meta">'
        '<time datetime="2026-01-01T00:00:00Z">2026-01-01 00:00:00</time>'
        "<span>render-localize · 0.20.0</span>"
        '<span class="prov-model">model-a</span></span>'
        '<span class="badge count" data-tip="of the 23 reports collected, 20 answered." '
        'tabindex="0">10/20</span>'
        "<p>The reader-visible sentence.</p></html>"
    )
    candidate = (
        '<html lang="en" dir="ltr" data-site-locale="en">'
        '<link rel="alternate" hreflang="en" href="/en/topics/t/">'
        '<link rel="alternate" hreflang="fr" href="/fr/topics/t/">'
        '<code class="prov-run">rl-2</code><span class="prov-meta">'
        '<time datetime="2026-09-03T00:00:00Z">2026-09-03 00:00:00</time>'
        "<span>render-localize · 0.21.0</span>"
        '<span class="prov-model">model-b</span></span>'
        '<span class="badge count" data-tip="among the 23 readable reports counted, 20 '
        'answered." tabindex="0">10/20</span>'
        "<p>The reader-visible sentence.</p></html>"
    )
    digest, moved = prove_byte_equivalence(_bytes_baseline(signed), candidate.encode())
    assert digest.startswith("sha256:")
    assert set(moved) == {
        "locale-alternates",
        "content-direction",
        "provenance-lineage",
        "stat-tooltip-wording",
    }
    # The sentence survives redaction; the whitelist is not allowed to reach it.
    assert "The reader-visible sentence." in redact(signed)[0]


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(("The reader-visible sentence.", "The reader-visible sentence!"), id="prose"),
        pytest.param(('tabindex="0">10/20<', 'tabindex="0">10/21<'), id="badge-text"),
        pytest.param(("the 23 reports collected", "the 24 reports collected"), id="tooltip-number"),
        pytest.param(('<h1>Title</h1>', "<h1>Titlé</h1>"), id="title"),
    ],
)
def test_content_changes_are_never_absorbed_by_the_whitelist(mutation):
    signed = (
        "<h1>Title</h1>"
        '<span class="badge count" data-tip="of the 23 reports collected, 20 answered." '
        'tabindex="0">10/20</span>'
        "<p>The reader-visible sentence.</p>"
    )
    before, after = mutation
    candidate = signed.replace(before, after)
    assert candidate != signed
    with pytest.raises(ArtifactError, match="outside the .* whitelist"):
        prove_byte_equivalence(_bytes_baseline(signed), candidate.encode())


def test_every_rule_says_what_it_is_and_why():
    assert len({rule.key for rule in RULES}) == len(RULES)
    for rule in RULES:
        assert rule.why.strip(), rule.key


def test_projection_ignores_other_languages_but_not_the_reviewed_ones():
    page = {
        "title": {"values": {"en": "A", "zh-CN": "甲"}},
        "note": {"values": {"fr": "seulement en français"}},
        "provenance": {"run_id": "rl-1"},
        "question_id": None,
    }
    projected = project_page(page, ["en", "zh-CN"])
    assert projected == {"title": {"values": {"en": "A", "zh-CN": "甲"}}}
    changed = project_page(
        {**page, "title": {"values": {"en": "B", "zh-CN": "甲"}}}, ["en", "zh-CN"]
    )
    assert changed != projected


def test_a_brand_new_multilang_dict_field_projects_the_same_as_the_key_being_absent():
    """``page.lexicon.group_labels`` (and its two siblings) is a
    field no baseline signed before it existed carries at all — a run that only fills
    it in for locales the page has not been reviewed in must project the same as a
    baseline that lacks the key outright, or every such lexicon-fill run would be
    permanently unable to ride a backfill even though nothing reviewed moved.
    """
    baseline = {
        "title": {"values": {"en": "A", "zh-CN": "甲"}},
        "lexicon": {"categories": {}},
    }
    candidate = {
        "title": {"values": {"en": "A", "zh-CN": "甲"}},
        "lexicon": {
            "categories": {},
            "group_labels": {
                "cn": {"values": {"fr": "côté chinois"}},
                "us": {"values": {"fr": "côté américain"}},
            },
        },
    }
    assert project_page(baseline, ["en", "zh-CN"]) == project_page(candidate, ["en", "zh-CN"])
    # ...but a real reviewed-language change is still caught: give "us" a reviewed value.
    candidate["lexicon"]["group_labels"]["us"]["values"]["en"] = "US side"
    assert project_page(baseline, ["en", "zh-CN"]) != project_page(candidate, ["en", "zh-CN"])
