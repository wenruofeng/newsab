"""ReaderPage model, pre-render checks, renderer."""

from __future__ import annotations

import dataclasses
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for pkg in ("schema", "editorial"):
    sys.path.insert(0, str(ROOT / pkg))

from newsab_schema.common import Provenance
from newsab_schema.models.corpus import (
    Article,
    Contributor,
    Group,
    Origin,
    Paragraph,
    Period,
    Sentence,
    SourceRegistry,
    TopicManifest,
)
from newsab_schema.models.manifest import ManifestEntry
from newsab_schema.models.findings import FindingDelta, GroupAnswerStats, QAFinding
from newsab_schema.models.page import ReaderPage
from newsab_schema.paths import TopicPaths

from newsab_editorial.page_checks import check_page
from newsab_editorial.page_render import render_page
from newsab_editorial.render.strings import STRINGS

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)
TOPIC = "aabb-river-light-2026"
from newsab_editorial.provenance import build_page_components


def prov(skill="write-0.1.0", model="test-model"):
    return Provenance(
        skill_version=skill,
        model_id=model,
        run_id="wrt-202608200000-00000001",
        timestamp=NOW,
    )


def article(article_id: str, lang: str, sentences: list[str], title: str) -> Article:
    return Article(
        article_id=article_id,
        topic_id=TOPIC,
        source_id="src",
        url=f"https://example.com/{article_id}",
        title=title,
        publish_date=date(2026, 7, 17),
        lang=lang,
        structured_text=[
            Paragraph(index=0, sentences=[Sentence(index=1, text=title)]),
            Paragraph(
                index=1,
                sentences=[
                    Sentence(index=i, text=t) for i, t in enumerate(sentences, 1)
                ],
            ),
        ],
        fetch_timestamp=NOW,
        access_level="full",
        origin=Origin(type="original"),
        reporting_cluster_id=f"RC-{article_id.split('_')[0]}-{article_id.split('_')[1]}",
        splitter_version="split-0.2.0",
        provenance=prov("S2stage-0.1.1", None),
    )


ARTICLES = [
    article(
        "CN_00000001",
        "zh-CN",
        ["新规将居留期限改为四年。", "家长表示担忧。"],
        "签证新规",
    ),
    article(
        "US_00000001",
        "en",
        ["The rule caps visas at four years.", "Colleges object."],
        "Visa rule",
    ),
]


def manifest() -> TopicManifest:
    return TopicManifest(
        topic_id=TOPIC,
        title={"values": {"en": "Visa", "zh-CN": "签证"}},
        groups=[
            Group(
                group_id="cn",
                prefix="CN",
                label={"values": {"en": "Chinese coverage", "zh-CN": "中文报道"}},
                short_label={"values": {"en": "China side", "zh-CN": "中方"}},
                definition={"values": {"en": "Chinese-language coverage"}},
            ),
            Group(
                group_id="us",
                prefix="US",
                label={"values": {"en": "US coverage", "zh-CN": "美国报道"}},
                short_label={"values": {"en": "US side", "zh-CN": "美方"}},
                definition={"values": {"en": "US-produced English coverage"}},
            ),
        ],
        period=Period(start=date(2026, 5, 1)),
        include=["visa policy"],
        contributors=[Contributor(name="rwen")],
        provenance=prov("S0-0.1.0", None),
    )


def finding(strength="supported", kind="divergence") -> QAFinding:
    return QAFinding(
        finding_id="FND-aabb-river-light-001",
        topic_id=TOPIC,
        question_id="QST-aabb-river-light-002",
        kind=kind,
        strength=strength,
        rank=1,
        interest=0.8,
        groups=[
            GroupAnswerStats(
                group_id="cn",
                clusters_total=12,
                clusters_addressed=9,
                category_counts={"us_government": 7, "unclear": 2},
                top_category="us_government",
                sample_evidence=["CN_00000001:P01:S01"],
            ),
            GroupAnswerStats(
                group_id="us",
                clusters_total=42,
                clusters_addressed=30,
                category_counts={"trump_administration": 24, "universities": 6},
                top_category="trump_administration",
                sample_evidence=["US_00000001:P01:S01"],
            ),
        ],
        delta=FindingDelta(
            quantity="top_category_share_diff",
            group_a="cn",
            group_b="us",
            value=0.3,
            lo=0.1,
            hi=0.5,
            level=0.9,
        ),
        stability=0.97,
        summary={"text": "The sides blame different actors.", "lang": "en"},
        thresholds_version="qa-0.1.0",
        provenance=prov("analyze-0.1.0", None),
    )


def page() -> ReaderPage:
    return ReaderPage.model_validate(
        {
            "topic_id": TOPIC,
            "title": {"values": {"en": "Who is to blame?", "zh-CN": "谁之过？"}},
            "intro": [
                {
                    "text": {
                        "values": {
                            "en": "A new US rule caps student visas.",
                            "zh-CN": "美国新规限制学生签证期限。",
                        }
                    },
                    "claim_type": "corpus_reading",
                    "evidence": ["CN_00000001:P01:S01", "US_00000001:P01:S01"],
                }
            ],
            "hook": {
                "text": {
                    "values": {
                        "en": "Each side's coverage blames the other side's government most often.",
                        "zh-CN": "两边报道最常归咎的都是对方政府。",
                    }
                },
                "claim_type": "corpus_aggregate",
                "computed_from": "FND-aabb-river-light-001",
                "evidence": ["CN_00000001:P01:S02"],
            },
            "angles": [
                {
                    "rank": 1,
                    "question_id": "QST-aabb-river-light-002",
                    "finding_id": "FND-aabb-river-light-001",
                    "kind": "divergence",
                    "question_display": {
                        "values": {
                            "en": "Who is held responsible?",
                            "zh-CN": "谁被归咎？",
                        }
                    },
                    "editorial_interest": {
                        "text": "The two coverages blame each other's government.",
                        "lang": "en",
                    },
                    "sides": [
                        {
                            "group_id": "cn",
                            "answer": {
                                "text": {
                                    "values": {
                                        "en": "The sampled Chinese coverage points at the US government.",
                                        "zh-CN": "抽样中文报道指向美国政府。",
                                    }
                                },
                                "claim_type": "corpus_aggregate",
                                "computed_from": "FND-aabb-river-light-001",
                            },
                            "answer_label": {
                                "values": {
                                    "en": "The US government",
                                    "zh-CN": "美国政府",
                                }
                            },
                            "answer_category": "us_government",
                            "quotes": [
                                {
                                    "sentence_id": "CN_00000001:P01:S02",
                                    "translation": {
                                        "values": {
                                            "en": "Parents voice concern.",
                                            "zh-CN": "家长表示担忧。",
                                        }
                                    },
                                }
                            ],
                            "badge": {
                                "group_id": "cn",
                                "numerator": 7,
                                "denominator": 9,
                                "computed_from": "FND-aabb-river-light-001:top_category",
                            },
                        },
                        {
                            "group_id": "us",
                            "answer": {
                                "text": {
                                    "values": {
                                        "en": "The sampled US coverage points at the Trump administration.",
                                        "zh-CN": "抽样美国报道指向特朗普政府。",
                                    }
                                },
                                "claim_type": "corpus_aggregate",
                                "computed_from": "FND-aabb-river-light-001",
                            },
                            "answer_label": {
                                "values": {
                                    "en": "The Trump administration",
                                    "zh-CN": "特朗普政府",
                                }
                            },
                            "answer_category": "trump_administration",
                            "quotes": [
                                {
                                    "sentence_id": "US_00000001:P01:S02",
                                    "translation": {
                                        "values": {"zh-CN": "高校提出异议。"}
                                    },
                                }
                            ],
                            "badge": {
                                "group_id": "us",
                                "numerator": 30,
                                "denominator": 42,
                                "computed_from": "FND-aabb-river-light-001",
                            },
                        },
                    ],
                }
            ],
            "how_we_counted": {
                "corpus_run_id": "s2s-20260820022103350548-fb9dba19",
                "questions_run_id": "qst-20260820023231999837-df0b77e1",
                "answers_run_id": "ans-20260820030000000000-00000001",
                "qa_run_id": "qa-20260820040000000000-00000001",
                "notes": [
                    {
                        "values": {
                            "en": "Counts are over independent reporting clusters.",
                            "zh-CN": "计数单位为独立报道簇。",
                        }
                    }
                ],
            },
            "provenance": prov().model_dump(mode="json"),
        }
    )


def test_clean_page_passes_and_renders_both_languages():
    report = check_page(page(), ARTICLES, [finding()], required_langs=("en", "zh-CN"))
    assert report.ok, report.render()
    for lang, expected in (("en", "China side"), ("zh-CN", "中方")):
        html = render_page(page(), ARTICLES, manifest(), lang=lang)
        assert expected in html
        assert (
            "家长表示担忧。" in html
        )  # verbatim quote from the corpus, both languages
        assert "qa-20260820040000000000-00000001" in html  # run ids only in the footer


def test_rtl_direction_wired_per_locale_and_ab_sides_stay_unmirrored():
    """dir="rtl" only for Arabic; the A/B-semantic layout stays forced ltr."""
    ar_html = render_page(page(), ARTICLES, manifest(), lang="ar")
    assert '<html lang="ar" dir="rtl"' in ar_html
    en_html = render_page(page(), ARTICLES, manifest(), lang="en")
    assert '<html lang="en" dir="ltr"' in en_html
    zh_html = render_page(page(), ARTICLES, manifest(), lang="zh-CN")
    assert '<html lang="zh-CN" dir="ltr"' in zh_html
    # The layer that keeps the duo/comm/axis3/cc-grid/timeline physically unmirrored
    # under RTL lives in the shared chrome CSS every preview inlines.
    for selector in (
        '[dir="rtl"] .duo,',
        '[dir="rtl"] .comm:not(.joint),',
        '[dir="rtl"] .axis3,',
        '[dir="rtl"] .cc-grid,',
        '[dir="rtl"] .tl-wrap{direction:ltr}',
    ):
        assert selector in ar_html


def test_machine_default_category_labels_draw_a_warning():
    """A label equal to page-init's `key -> Capitalized words` seed may never have been
    rewritten — or may already be the right reader word (measured: a run turned `Mixed`
    into `Genuinely mixed` purely to silence this warning, which made the label worse).
    The message must say to answer it in the run report, not to add words on sight."""
    data = page().model_dump(mode="json")
    data["lexicon"]["categories"]["narendra_modi_government"] = {
        "values": {"en": "Narendra modi government", "zh-CN": "纳伦德拉·莫迪政府"}
    }
    report = check_page(
        ReaderPage.model_validate(data), ARTICLES, [finding()], required_langs=("en",)
    )
    assert report.ok, report.render()
    assert any("machine-generated default" in w for w in report.warnings), report.render()
    assert any(
        "do not add words just to silence this warning" in w for w in report.warnings
    ), report.render()

    rewritten = page().model_dump(mode="json")
    rewritten["lexicon"]["categories"]["narendra_modi_government"] = {
        "values": {"en": "The Modi government", "zh-CN": "莫迪政府"}
    }
    clean = check_page(
        ReaderPage.model_validate(rewritten), ARTICLES, [finding()], required_langs=("en",)
    )
    assert not any("machine-generated default" in w for w in clean.warnings)


def test_a_lingering_hook_draws_a_warning():
    data = page().model_dump(mode="json")
    data["hook"] = {
        "text": {"values": {"en": "A pull quote nobody asked for."}},
        "claim_type": "corpus_aggregate",
        "computed_from": "FND-aabb-river-light-001",
        "evidence": [],
    }
    report = check_page(
        ReaderPage.model_validate(data), ARTICLES, [finding()], required_langs=("en",)
    )
    assert any("hook" in w for w in report.warnings), report.render()
    dropped = page().model_dump(mode="json")
    dropped["hook"] = None
    assert not any("hook" in w for w in check_page(
        ReaderPage.model_validate(dropped), ARTICLES, [finding()], required_langs=("en",)
    ).warnings)


def test_a_localized_scope_bullet_that_drops_the_signed_numbers_is_flagged():
    """The bullet is what touchpoint one signed: translate it, never summarize it."""
    signed = "Reporting from 2025-04-23 through 2026-07-05 on the visa policy"
    m = manifest().model_copy(update={"include": [signed]})
    data = page().model_dump(mode="json")
    data["lexicon"]["scope"] = {
        signed: {"values": {"en": signed, "zh-CN": "关于签证政策的报道。"}}
    }
    report = check_page(
        ReaderPage.model_validate(data), ARTICLES, [finding()],
        required_langs=("en",), manifest=m,
    )
    lost = [w for w in report.warnings if "drops number(s)" in w]
    assert lost and "[zh-CN]" in lost[0], report.render()

    # Natural notation ("04" -> 4月) still passes: containment is leading-zero tolerant.
    data["lexicon"]["scope"][signed]["values"]["zh-CN"] = (
        "2025年4月23日至2026年7月5日期间关于签证政策的报道。"
    )
    clean = check_page(
        ReaderPage.model_validate(data), ARTICLES, [finding()],
        required_langs=("en",), manifest=m,
    )
    assert not [w for w in clean.warnings if "drops number(s)" in w], clean.render()


def test_a_required_language_missing_from_every_group_table_is_a_warning():
    """Regression: the per-entry group-lexicon check iterates the table's
    own keys, so an empty ``lexicon.group_labels`` (the common case — a run that never
    touches these tables) is asked nothing, even when the manifest itself never carried
    the language either. A nine-locale run shipped a Russian page with the English short
    label "China side" on it this way. This check asks group x language directly,
    independent of whether the lexicon table has any entries at all."""
    m = manifest()  # groups carry en/zh-CN label+short_label, en-only definition
    report = check_page(
        page(), ARTICLES, [finding()], required_langs=("en", "ru"), manifest=m
    )
    for attr in ("group_labels", "group_short_labels", "group_definitions"):
        for group_id in ("cn", "us"):
            assert any(
                f"group {group_id!r} has no {attr} wording for language 'ru'" in w
                for w in report.warnings
            ), report.render()
    # 'en' is fully covered by the manifest itself, on both sides, for all three fields.
    assert not any(
        "wording for language 'en'" in w for w in report.warnings
    ), report.render()

    # Filling in the lexicon override for one side clears exactly that side's warnings.
    data = page().model_dump(mode="json")
    data["lexicon"]["group_labels"] = {"cn": {"values": {"ru": "Освещение на китайском"}}}
    data["lexicon"]["group_short_labels"] = {"cn": {"values": {"ru": "китайская сторона"}}}
    data["lexicon"]["group_definitions"] = {"cn": {"values": {"ru": "Репортажи по-китайски"}}}
    filled = check_page(
        ReaderPage.model_validate(data), ARTICLES, [finding()],
        required_langs=("en", "ru"), manifest=m,
    )
    assert not any(
        "group 'cn' has no" in w and "'ru'" in w for w in filled.warnings
    ), filled.render()
    for attr in ("group_labels", "group_short_labels", "group_definitions"):
        assert any(
            f"group 'us' has no {attr} wording for language 'ru'" in w
            for w in filled.warnings
        ), filled.render()


def test_render_is_byte_deterministic_for_the_same_artifacts():
    first = render_page(page(), ARTICLES, manifest(), cloud_stats(), lang="en")
    second = render_page(page(), ARTICLES, manifest(), cloud_stats(), lang="en")
    reordered = render_page(
        page(), list(reversed(ARTICLES)), manifest(), dict(reversed(cloud_stats().items())),
        lang="en",
    )

    assert first.encode() == second.encode()
    assert first.encode() == reordered.encode()


def test_production_navigation_is_opt_in_and_accessible():
    preview = render_page(page(), ARTICLES, manifest(), lang="zh-CN")
    production = render_page(
        page(), ARTICLES, manifest(), lang="zh-CN", home_url="../../index.html?from=topic&x=1"
    )

    assert 'class="home-link"' not in preview
    assert (
        '<a class="home-link" href="../../index.html?from=topic&amp;x=1">'
        '<span aria-hidden="true">←</span> 返回首页</a>'
    ) in production
    assert 'id="page-top"' in production
    assert (
        'class="top-fab" id="backtotop" href="#page-top" '
        'aria-label="回到顶部"'
    ) in production
    assert "width:2.75rem;height:2.75rem" in production  # 44px at the root font size
    assert "env(safe-area-inset-bottom)" in production
    assert "prefers-reduced-motion:reduce" in production
    assert "prefers-reduced-motion: reduce" in production
    assert "body.modal-open .top-fab" in production
    assert "backToTop.tabIndex = shown ? 0 : -1" in production
    assert "backToTop.setAttribute('aria-hidden', shown ? 'false' : 'true')" in production


def test_m2_layer_is_opt_in_and_ships_the_touch_fixes():
    from newsab_editorial.render.m2 import PageSiteContext

    doc = page()
    page_url = f"/zh-CN/topics/{doc.topic_id}/"
    question_ids = [angle.question_id for angle in doc.angles]
    context = PageSiteContext(
        site_locale="zh-CN",
        content_locale="zh-CN",
        canonical_url=page_url,
        alternate_urls={"zh-CN": page_url, "en": f"/en/topics/{doc.topic_id}/"},
        share_urls={qid: f"{page_url}#angle-{qid}" for qid in question_ids},
        share_landing_urls={qid: f"{page_url}share/angle-{qid}.html" for qid in question_ids},
        share_image_url="/assets/share-card.png",
        language_label="语言",
        share_label="分享角度",
        share_copied="已复制",
        share_failed="复制失败",
        theme_token="editorial-warm",
        stylesheet_url="/assets/site.css",
        script_url="/assets/site.js",
    )
    preview = render_page(page(), ARTICLES, manifest(), lang="zh-CN")
    production = render_page(
        page(), ARTICLES, manifest(), lang="zh-CN", home_url="/zh-CN/", site_context=context
    )

    for marker in ("data-share-angle", 'rel="canonical"', 'data-theme-token="editorial-warm"'):
        assert marker not in preview
        assert marker in production


def test_production_page_is_a_content_document_and_a_preview_is_standalone():
    """Touchpoint two approves what the page states, not the site's typography.

    So a production page carries no stylesheet, font link or script of its own — it links
    the site chrome — while a preview stays one self-contained file a reviewer can open
    from disk.
    """
    from newsab_editorial.render.m2 import PageSiteContext

    doc = page()
    page_url = f"/zh-CN/topics/{doc.topic_id}/"
    question_ids = [angle.question_id for angle in doc.angles]
    context = PageSiteContext(
        site_locale="zh-CN",
        content_locale="zh-CN",
        canonical_url=page_url,
        alternate_urls={"zh-CN": page_url},
        share_urls={qid: f"{page_url}#angle-{qid}" for qid in question_ids},
        share_landing_urls={qid: f"{page_url}share/angle-{qid}.html" for qid in question_ids},
        share_image_url="/assets/share-card.png",
        language_label="语言",
        share_label="分享视角",
        share_copied="已复制",
        share_failed="复制失败",
        theme_token="editorial-warm",
        stylesheet_url="/assets/site.css",
        script_url="/assets/site.js",
    )
    preview = render_page(page(), ARTICLES, manifest(), lang="zh-CN")
    production = render_page(
        page(), ARTICLES, manifest(), lang="zh-CN", home_url="/zh-CN/", site_context=context
    )

    assert '<link rel="stylesheet" href="/assets/site.css">' in production
    assert '<script src="/assets/site.js" defer></script>' in production
    assert "<style>" not in production
    assert "fonts.googleapis.com" not in production
    # The JSON payload blocks are content, and stay in the content document.
    assert 'id="sentence-index"' in production

    assert "<style>" in preview
    assert "fonts.googleapis.com" in preview
    assert "/assets/site.css" not in preview


def test_a_chrome_change_cannot_move_an_approved_content_document(monkeypatch):
    """The whole point of the split: restyling the site must not invalidate an approval.

    Before it, one colour edit changed every page's bytes, so every topic needed a fresh
    touchpoint two.  A preview is still self-contained, so its bytes do move — correctly.
    """
    from newsab_editorial.render import page as page_module
    from newsab_editorial.render.m2 import PageSiteContext

    doc = page()
    page_url = f"/zh-CN/topics/{doc.topic_id}/"
    question_ids = [angle.question_id for angle in doc.angles]
    context = PageSiteContext(
        site_locale="zh-CN",
        content_locale="zh-CN",
        canonical_url=page_url,
        alternate_urls={"zh-CN": page_url},
        share_urls={qid: f"{page_url}#angle-{qid}" for qid in question_ids},
        share_landing_urls={qid: f"{page_url}share/angle-{qid}.html" for qid in question_ids},
        share_image_url="/assets/share-card.png",
        language_label="语言",
        share_label="分享视角",
        share_copied="已复制",
        share_failed="复制失败",
        theme_token="ember",
        stylesheet_url="/assets/site.css",
        script_url="/assets/site.js",
    )

    def render(**kwargs):
        return render_page(page(), ARTICLES, manifest(), lang="zh-CN", **kwargs)

    production_before = render(site_context=context)
    preview_before = render()

    monkeypatch.setattr(
        page_module, "CSS", page_module.CSS.replace("--accent:#8C2F1E", "--accent:#1B5E20")
    )
    monkeypatch.setattr(page_module, "JS", page_module.JS + "\n/* a behaviour change */\n")

    assert render(site_context=context) == production_before
    assert render() != preview_before


def test_withheld_tally_counts_each_denied_anchor_once():
    from newsab_editorial.evidence import SentenceIndex

    index = SentenceIndex(ARTICLES)
    assert index.budget("CN_00000001") == 1
    assert index.allow("CN_00000001:P01:S01") is True
    # The storyline pre-pass and the real render may ask about the same anchor twice.
    assert index.allow("CN_00000001:P01:S02") is False
    assert index.allow("CN_00000001:P01:S02") is False
    assert index.withheld == {"CN_00000001": 1}


def test_unsupported_finding_blocks_the_angle():
    report = check_page(page(), ARTICLES, [finding(strength="unsupported")])
    assert any("unsupported" in e for e in report.errors)


def test_weak_finding_is_labelled_by_the_renderer_not_by_the_writer():
    """A weak finding no longer costs the writer a hedging sentence.

    The page still has to say it — but the renderer says it, as one chip whose tooltip
    carries the thresholds the pinned run used, identically on every page.
    """
    report = check_page(page(), ARTICLES, [finding(strength="weak")])
    assert not any("caveat" in e for e in report.errors), report.render()
    html = render_page(
        page(), ARTICLES, manifest(), lang="zh-CN", findings=[finding(strength="weak")]
    )
    assert "证据偏弱" in html
    assert "统计可复现率" in html  # the threshold explanation rides on the chip


def _with_caveat(*, mark_in: str | None = None, caveat_text: str = "Sampled from one week."):
    """The fixture page with a caveat, optionally pointed at from the cn explanation."""
    data = page().model_dump(mode="json")
    angle = data["angles"][0]
    angle["caveat"] = {"values": {"en": caveat_text, "zh-CN": "仅抽样了一周。"}}
    if mark_in is not None:
        for side in angle["sides"]:
            if side["group_id"] == "cn":
                for lang, suffix in (("en", mark_in), ("zh-CN", mark_in)):
                    side["answer"]["text"]["values"][lang] += suffix
    return ReaderPage.model_validate(data)


def test_a_note_no_marker_points_at_is_a_note_the_reader_never_sees():
    """The renderer drops every note no ``[^n]`` reached, and shows no leftovers anywhere:
    a page can carry a written sampling caveat, validate, render, and simply not contain
    it. Only a human who remembered it was supposed to be there ever finds out."""
    report = check_page(_with_caveat(), ARTICLES, [finding()], required_langs=("en",))
    assert any(
        "no [^n] marker" in w and "angle 1 [en]" in w for w in report.warnings
    ), report.render()

    marked = check_page(
        _with_caveat(mark_in="[^1]"), ARTICLES, [finding()], required_langs=("en",)
    )
    assert not any("[^n] marker" in w for w in marked.warnings), marked.render()


def test_a_translation_that_drops_the_marker_loses_the_note_for_that_reader_alone():
    data = _with_caveat(mark_in="[^1]").model_dump(mode="json")
    for side in data["angles"][0]["sides"]:
        side["answer"]["text"]["values"]["zh-CN"] = side["answer"]["text"]["values"][
            "zh-CN"
        ].replace("[^1]", "")
    report = check_page(
        ReaderPage.model_validate(data),
        ARTICLES,
        [finding()],
        required_langs=("en", "zh-CN"),
    )
    assert any("angle 1 [zh-CN]" in w and "no [^n] marker" in w for w in report.warnings)
    assert not any("angle 1 [en]" in w and "[^n] marker" in w for w in report.warnings)


def test_a_marker_pointing_past_the_notes_is_reported_not_silently_dropped():
    report = check_page(
        _with_caveat(mark_in="[^2]"), ARTICLES, [finding()], required_langs=("en",)
    )
    assert any("marker(s) [2] point past" in w for w in report.warnings), report.render()


def test_badge_that_does_not_recompute_fails():
    bad = page().model_copy(deep=True)
    data = bad.model_dump(mode="json")
    data["angles"][0]["sides"][0]["badge"]["numerator"] = 8
    bad = ReaderPage.model_validate(data)
    report = check_page(bad, ARTICLES, [finding()])
    assert any("recomputes to 7/9" in e for e in report.errors)


def test_placeholder_provenance_from_page_init_is_refused():
    """Regression: page_init.py's draft placeholders passed every check and were
    only refused by review-preview — after finalize, when the run was already immutable
    and the only remedy was a whole new run."""
    from newsab_editorial.page_checks import PLACEHOLDER_MODEL_ID, PLACEHOLDER_RUN_ID

    data = page().model_dump(mode="json")
    data["provenance"]["run_id"] = PLACEHOLDER_RUN_ID
    data["provenance"]["model_id"] = PLACEHOLDER_MODEL_ID
    stale = ReaderPage.model_validate(data)
    report = check_page(stale, ARTICLES, [finding()])
    assert any("provenance.run_id is still the draft placeholder" in e for e in report.errors)
    assert any("provenance.model_id is still the draft placeholder" in e for e in report.errors)

    clean = check_page(page(), ARTICLES, [finding()])
    assert not any("placeholder" in e for e in clean.errors)


def _in_run_dir(tmp_path, run_id: str) -> tuple[Path, TopicPaths]:
    """A page path shaped like ``<topics_root>/<topic>/editorial/versions/<run_id>/page.json``."""
    paths = TopicPaths.for_topic(tmp_path / "topics", TOPIC)
    run_dir = paths.stage_run_dir("editorial", run_id)
    run_dir.mkdir(parents=True)
    return run_dir / "page.json", paths


def test_a_page_copied_from_another_run_keeps_the_donor_stamp_and_is_refused(tmp_path):
    """Regression: a write-run page copied into a render-localize run directory
    to seed localization kept its write-stage stamp through two judge panels, 163
    localized fields and two rendered previews — only ``review-preview`` (the very last
    step, after the run was already finalized and immutable) refused it. The same
    assertion now runs at the first ``page-check``."""
    page_path, paths = _in_run_dir(tmp_path, "rl-202608200000-00000001")
    donor = page().model_dump(mode="json")
    donor["provenance"] = {
        "skill_version": "write-0.17.0",
        "model_id": "test-model",
        "run_id": "edt-202608200000-00000001",
        "timestamp": NOW.isoformat(),
    }
    report = check_page(
        ReaderPage.model_validate(donor),
        ARTICLES,
        [finding()],
        page_path=page_path,
        paths=paths,
    )
    assert any(
        "page.provenance.run_id is 'edt-202608200000-00000001' but this file sits in "
        "run directory 'rl-202608200000-00000001'" in e
        for e in report.errors
    ), report.render()
    assert report.stats["run provenance check"] == (
        "checked against run directory rl-202608200000-00000001"
    )


def test_a_page_with_the_wrong_skill_stamp_for_its_run_directory_is_refused(tmp_path):
    """The run id half can be patched without the skill half following — still a stale
    stamp, still refused."""
    page_path, paths = _in_run_dir(tmp_path, "rl-202608200000-00000001")
    data = page().model_dump(mode="json")
    data["provenance"] = {
        "skill_version": "write-0.17.0",
        "model_id": "test-model",
        "run_id": "rl-202608200000-00000001",
        "timestamp": NOW.isoformat(),
    }
    report = check_page(
        ReaderPage.model_validate(data), ARTICLES, [finding()], page_path=page_path, paths=paths
    )
    assert any(
        "page.provenance.skill_version is 'write-0.17.0' but run "
        "'rl-202608200000-00000001' is a 'rl'-prefixed run" in e
        for e in report.errors
    ), report.render()


def test_a_page_correctly_stamped_for_its_own_run_directory_passes(tmp_path):
    for prefix, stamp in (("edt", "write"), ("rl", "renderlocalize")):
        run_id = f"{prefix}-202608200000-00000001"
        page_path, paths = _in_run_dir(tmp_path, run_id)
        data = page().model_dump(mode="json")
        data["provenance"] = {
            "skill_version": f"{stamp}-0.1.0",
            "model_id": "test-model",
            "run_id": run_id,
            "timestamp": NOW.isoformat(),
        }
        report = check_page(
            ReaderPage.model_validate(data),
            ARTICLES,
            [finding()],
            page_path=page_path,
            paths=paths,
        )
        assert not any("page.provenance." in e for e in report.errors), report.render()
        assert report.stats["run provenance check"] == f"checked against run directory {run_id}"


def test_a_page_outside_any_run_directory_is_not_checked_and_says_so(tmp_path):
    """A scratch draft (write's ``draft_page.json`` before ``mint-run-id``, a fixture)
    is not the run-directory provenance bug and is silently skipped — but the skip is recorded, so a run
    report can see whether the check applied."""
    scratch = tmp_path / "draft_page.json"
    paths = TopicPaths.for_topic(tmp_path / "topics", TOPIC)
    report = check_page(
        page(), ARTICLES, [finding()], page_path=scratch, paths=paths
    )
    assert not any("page.provenance." in e for e in report.errors), report.render()
    assert report.stats["run provenance check"].startswith("skipped")


def test_the_shared_publish_rerender_path_omits_the_run_directory_check():
    """``builder.render_locales`` — the code path ``prepare``/``review-preview``/
    ``verify-site`` all share to reproduce an already-approved page's bytes — calls
    ``check_page`` without ``page_path``/``paths``. That is the whole safety property:
    an already-shipped run's directory is immutable, so a stale stamp there is history,
    not something a reproduced render can fix, and it must never be why a verify of a
    *different*, already-approved run refuses. This pins the contract in the one place a
    signature change could silently break it."""
    import inspect

    from newsab_publish import builder

    source = inspect.getsource(builder.render_locales)
    call = source[source.index("check_page(") :]
    assert "page_path" not in call.split(")", 1)[0]
    assert "paths=" not in call.split(")", 1)[0]
    # And the property it exists for: a page whose provenance would fail the run-directory check
    # if it were told where the file lives still passes when it is not told.
    stale = page().model_dump(mode="json")
    stale["provenance"]["run_id"] = "edt-202608200000-00000001"
    report = check_page(ReaderPage.model_validate(stale), ARTICLES, [finding()])
    assert not any("page.provenance." in e for e in report.errors), report.render()


def test_top_category_badge_refuses_a_tied_mode():
    tied = finding().model_dump(mode="json")
    tied_group = tied["groups"][0]
    tied_group["category_counts"] = {
        "legal_challenge": 3,
        "policy_reversal": 3,
        "unclear": 3,
    }
    tied_group["top_category"] = "legal_challenge"
    tied_group.pop("top_categories", None)  # legacy runs acquire the metadata on load
    tied_group.pop("top_category_tied", None)
    report = check_page(page(), ARTICLES, [QAFinding.model_validate(tied)])
    assert any("top_category is ambiguous" in error for error in report.errors)


def test_tied_mode_must_be_stated_in_the_side_answer():
    tied = finding().model_dump(mode="json")
    tied_group = tied["groups"][0]
    tied_group["category_counts"] = {
        "legal_challenge": 3,
        "policy_reversal": 3,
        "unclear": 3,
    }
    tied_group["top_category"] = "legal_challenge"
    tied_group.pop("top_categories", None)
    tied_group.pop("top_category_tied", None)
    data = page().model_dump(mode="json")
    data["angles"][0]["sides"][0]["badge"] = {
        "group_id": "cn",
        "numerator": 9,
        "denominator": 12,
        "computed_from": "FND-aabb-river-light-001:addressed",
    }
    report = check_page(
        ReaderPage.model_validate(data), ARTICLES, [QAFinding.model_validate(tied)]
    )
    assert any("must state that tie explicitly" in error for error in report.errors)


def test_dangling_anchor_fails():
    data = page().model_dump(mode="json")
    data["angles"][0]["sides"][1]["quotes"][0]["sentence_id"] = "US_00000001:P09:S09"
    report = check_page(ReaderPage.model_validate(data), ARTICLES, [finding()])
    assert any("does not exist" in e for e in report.errors)


def test_aggregate_number_must_recompute():
    data = page().model_dump(mode="json")
    data["hook"]["text"]["values"]["en"] = "In 99 clusters the sides blame each other."
    report = check_page(ReaderPage.model_validate(data), ARTICLES, [finding()])
    assert any("99" in e and "recompute" in e for e in report.errors)


def test_corpus_reading_may_not_quantify():
    data = page().model_dump(mode="json")
    data["intro"][0]["text"]["values"]["en"] = "Most coverage frames the rule as a cap."
    report = check_page(ReaderPage.model_validate(data), ARTICLES, [finding()])
    assert any("quantifies" in e for e in report.errors)


def test_missing_reviewer_language_fails():
    data = page().model_dump(mode="json")
    del data["title"]["values"]["zh-CN"]
    report = check_page(
        ReaderPage.model_validate(data),
        ARTICLES,
        [finding()],
        required_langs=("en", "zh-CN"),
    )
    assert any("title missing language" in e for e in report.errors)


def test_localization_may_convert_numeric_notation_without_a_second_numeric_gate():
    data = page().model_dump(mode="json")
    data["hook"]["text"]["values"]["en"] = "7 of 9 clusters give this answer."
    data["hook"]["text"]["values"]["zh-CN"] = "九个报道簇中有七个，约占78%。"
    report = check_page(
        ReaderPage.model_validate(data),
        ARTICLES,
        [finding()],
        required_langs=("en", "zh-CN"),
    )
    assert report.ok, report.render()


def test_quote_in_the_readers_own_language_needs_no_translation():
    """A zh-CN quote shown to a zh-CN reader renders as itself.

    The renderer suppresses a translation whose language matches the article's, so
    requiring one would only push a sentence into the artifact as its own translation.
    """
    data = page().model_dump(mode="json")
    quote = data["angles"][0]["sides"][0]["quotes"][0]
    assert quote["sentence_id"].startswith("CN_")
    del quote["translation"]["values"]["zh-CN"]
    report = check_page(
        ReaderPage.model_validate(data),
        ARTICLES,
        [finding()],
        required_langs=("en", "zh-CN"),
    )
    assert not any("translation missing" in e for e in report.errors), report.errors


def test_translation_into_a_foreign_readers_language_is_still_required():
    """An English quote with no zh-CN translation is a quote the reviewer cannot read."""
    data = page().model_dump(mode="json")
    quote = data["angles"][0]["sides"][1]["quotes"][0]
    assert quote["sentence_id"].startswith("US_")
    quote["translation"] = None
    report = check_page(
        ReaderPage.model_validate(data),
        ARTICLES,
        [finding()],
        required_langs=("en", "zh-CN"),
    )
    assert any("translation missing" in e for e in report.errors)


def test_quote_english_translation_is_not_required_by_default():
    """The quote-english-translation hard reject is opt-in — off unless a caller explicitly asks for it."""
    data = page().model_dump(mode="json")
    quote = data["angles"][0]["sides"][0]["quotes"][0]
    assert quote["sentence_id"].startswith("CN_")
    del quote["translation"]["values"]["en"]
    report = check_page(ReaderPage.model_validate(data), ARTICLES, [finding()])
    assert report.ok, report.render()


def test_stage_page_check_requires_a_chinese_quote_to_carry_an_english_translation():
    """Regression: an English reader met a bare Chinese quote; seven L2 judges had no pivot to
    compare it against. `require_quote_en_translation=True` is what the stage-level
    `page-check` CLI passes."""
    data = page().model_dump(mode="json")
    quote = data["angles"][0]["sides"][0]["quotes"][0]
    assert quote["sentence_id"].startswith("CN_")
    del quote["translation"]["values"]["en"]
    report = check_page(
        ReaderPage.model_validate(data),
        ARTICLES,
        [finding()],
        require_quote_en_translation=True,
    )
    assert any(
        "translation missing language 'en'" in e for e in report.errors
    ), report.render()


def test_an_english_quote_never_needs_translation_into_itself_even_when_enforced():
    """The US side's quote is already English; the check must not ask for a self-translation."""
    data = page().model_dump(mode="json")
    quote = data["angles"][0]["sides"][1]["quotes"][0]
    assert quote["sentence_id"].startswith("US_")
    quote["translation"] = None
    report = check_page(
        ReaderPage.model_validate(data),
        ARTICLES,
        [finding()],
        require_quote_en_translation=True,
    )
    assert not any(
        "translation missing language 'en'" in e for e in report.errors
    ), report.render()


def test_the_shared_publish_rerender_path_never_enforces_quote_en_translation():
    """An already-published cn-side page with no `en` quote translation must keep
    rendering on the outbound path (`prepare`/`review-preview`/`verify-site`/
    `verify-candidate`) — this is a requirement on future write runs, not a retroactive
    one. Same safety shape as the run-provenance switch: the check reads
    `builder.render_locales`'s own source rather than exercising the whole publish stack,
    so the contract breaks loudly the moment someone passes the kwarg there."""
    import inspect

    from newsab_publish import builder

    source = inspect.getsource(builder.render_locales)
    assert "require_quote_en_translation" not in source


def test_a_number_followed_by_a_comma_is_still_the_same_number():
    """Sentence punctuation must not decide whether a number is verifiable."""
    data = page().model_dump(mode="json")
    intro = data["intro"][0]
    intro["claim_type"] = "source_claim"
    intro["evidence"] = ["CN_00000001:P01:S01"]
    intro["text"]["values"]["en"] = (
        "Under the rule the limit became 四年, officials said."
    )
    intro["text"]["values"]["zh-CN"] = "新规将居留期限改为四年。"
    report = check_page(ReaderPage.model_validate(data), ARTICLES, [finding()])
    assert not any("appears in none" in e for e in report.errors), report.errors


# --------------------------------------------------------------------------------------
# answer cards, per-cluster evidence lists, source detail view, appendix
# --------------------------------------------------------------------------------------

from newsab_schema.models.qa import ClusterAnswer, Question, QuestionSet  # noqa: E402

from newsab_editorial.evidence import AnswerIndex, counted_clusters  # noqa: E402
from newsab_schema.readability import readable_clusters_of_articles  # noqa: E402


def cluster_articles(
    group: str, lang: str, count: int, sentences: int = 4
) -> list[Article]:
    """``count`` single-article clusters on one side, each with its own sentences."""
    return [
        article(
            f"{group}_0000000{i}",
            lang,
            [f"{group} sentence {i}.{j}" for j in range(1, sentences + 1)],
            f"{group} headline {i}",
        )
        for i in range(1, count + 1)
    ]


EV_ARTICLES = cluster_articles("CN", "zh-CN", 3) + cluster_articles("US", "en", 3)


def cluster_answer(
    group: str, i: int, category: str | None, anchors: int = 2
) -> ClusterAnswer:
    addressed = category is not None
    return ClusterAnswer(
        answer_id=f"ANS-aabb-river-light-{i:06d}"
        if group == "CN"
        else f"ANS-aabb-river-light-{100 + i:06d}",
        topic_id=TOPIC,
        question_id="QST-aabb-river-light-002",
        question_set_version="qst-20260820023231999837-df0b77e1",
        reporting_cluster_id=f"RC-{group}-0000000{i}",
        group_id=group.lower(),
        addressed=addressed,
        answer_summary={"text": f"summary {group}{i}", "lang": "en"}
        if addressed
        else None,
        answer_category=category,
        evidence=(
            [f"{group}_0000000{i}:P01:S{j:02d}" for j in range(1, anchors + 1)]
            if addressed
            else []
        ),
        confidence=0.8,
        provenance=prov("annotate-0.1.0", "test-model"),
    )


def ev_answers(cn_categories, us_categories) -> AnswerIndex:
    return AnswerIndex(
        [cluster_answer("CN", i, c) for i, c in enumerate(cn_categories, 1)]
        + [cluster_answer("US", i, c) for i, c in enumerate(us_categories, 1)]
    )


def ev_finding(
    kind="divergence", cn_top="us_government", us_top="trump_administration"
) -> QAFinding:
    data = finding(kind=kind).model_dump(mode="json")
    data["groups"][0].update(
        clusters_total=3,
        clusters_addressed=3,
        category_counts={cn_top: 2, "universities": 1},
        top_category=cn_top,
        top_categories=[cn_top],
        top_category_tied=False,
        sample_evidence=["CN_00000001:P01:S01"],
    )
    data["groups"][1].update(
        clusters_total=3,
        clusters_addressed=3,
        category_counts={us_top: 2, "universities": 1},
        top_category=us_top,
        top_categories=[us_top],
        top_category_tied=False,
        sample_evidence=["US_00000001:P01:S01"],
    )
    return QAFinding.model_validate(data)


def ev_page(**overrides) -> ReaderPage:
    data = page().model_dump(mode="json")
    angle = data["angles"][0]
    for side, group, category in (
        (angle["sides"][0], "CN", "us_government"),
        (angle["sides"][1], "US", "trump_administration"),
    ):
        side["badge"] = {
            "group_id": group.lower(),
            "numerator": 2,
            "denominator": 3,
            "computed_from": "FND-aabb-river-light-001:top_category",
        }
        side["answer_category"] = category
        side["quotes"] = [
            {
                "sentence_id": f"{group}_00000001:P01:S01",
                "translation": {"values": {"en": "x", "zh-CN": "x"}},
            }
        ]
    data["intro"][0]["evidence"] = ["CN_00000001:P01:S01", "US_00000001:P01:S01"]
    data["hook"]["evidence"] = ["CN_00000001:P01:S01"]
    for key, value in overrides.items():
        data["angles"][0][key] = value
    return ReaderPage.model_validate(data)


def question_set() -> QuestionSet:
    return QuestionSet(
        topic_id=TOPIC,
        question_set_version="qst-20260820023231999837-df0b77e1",
        questions=[
            Question(
                question_id="QST-aabb-river-light-002",
                topic_id=TOPIC,
                tier="template",
                template_key="responsibility",
                text={"values": {"en": "Who is blamed?", "zh-CN": "谁被归咎？"}},
                rationale={"text": "standard", "lang": "en"},
                provenance=prov("annotate-0.1.0", "test-model"),
            ),
            Question(
                question_id="QST-aabb-river-light-003",
                topic_id=TOPIC,
                tier="reader",
                text={
                    "values": {"en": "What happens next?", "zh-CN": "接下来会怎样？"}
                },
                rationale={"text": "topic", "lang": "en"},
                provenance=prov("annotate-0.1.0", "test-model"),
            ),
        ],
        provenance=prov("annotate-0.1.0", "test-model"),
    )


def ev_stats() -> dict:
    return {
        "QST-aabb-river-light-002": {
            "question": "Who is blamed?",
            "tier": "template",
            "kind": "divergence",
            "stability": 0.97,
            "addressed_rate_diff": None,
            "groups": {
                "cn": {
                    "clusters_total": 3,
                    "clusters_addressed": 3,
                    "category_counts": {"us_government": 2, "universities": 1},
                },
                "us": {
                    "clusters_total": 3,
                    "clusters_addressed": 3,
                    "category_counts": {"trump_administration": 2, "universities": 1},
                },
            },
        },
        "QST-aabb-river-light-003": {
            "question": "What happens next?",
            "tier": "reader",
            "kind": "insufficient",
            "stability": None,
            "addressed_rate_diff": None,
            "groups": {
                "cn": {
                    "clusters_total": 3,
                    "clusters_addressed": 0,
                    "category_counts": {},
                },
                "us": {
                    "clusters_total": 3,
                    "clusters_addressed": 0,
                    "category_counts": {},
                },
            },
        },
    }


def render_ev(page_record, answers, **kwargs):
    return render_page(
        page_record,
        EV_ARTICLES,
        manifest(),
        ev_stats(),
        lang="en",
        findings=[ev_finding()],
        answers=answers,
        question_set=question_set(),
        **kwargs,
    )


def test_the_badge_number_and_the_evidence_list_are_the_same_clusters():
    """A badge that says two reports must be able to show two reports."""
    answers = ev_answers(
        ["us_government", "us_government", "universities"],
        ["trump_administration", "trump_administration", "universities"],
    )
    html = render_ev(ev_page(), answers)
    modal = html.split('id="ev-1"')[1].split('<div id="floattip"', 1)[0]
    assert modal.count('class="tabpanel"') == 2
    assert 'data-panel="cn"' in modal and 'data-panel="us"' in modal
    assert modal.count("<th>report source</th>") == 2
    assert 'data-open="ev-1" data-open-tab="cn"' in html
    assert 'data-open="ev-1" data-open-tab="us"' in html
    assert "RC-CN-" not in modal and "RC-US-" not in modal


def test_a_quote_the_badge_does_not_count_is_refused():
    answers = ev_answers(
        ["universities", "us_government", "us_government"],
        ["trump_administration", "trump_administration", "universities"],
    )
    report = check_page(
        ev_page(), EV_ARTICLES, [ev_finding()], ev_stats(), answers=answers
    )
    assert any("which the badge does not count" in e for e in report.errors), (
        report.render()
    )


def _partial(art: Article) -> Article:
    """The same article, retrieved title+lead only — its cluster stops being countable."""
    return art.model_copy(update={"access_level": "partial"})


def test_an_unreadable_cluster_is_in_neither_the_count_nor_the_evidence_list():
    """qa-0.5.0's readable universe reaches the evidence list, not just the statistics.

    The analyze stage learned to count over readable clusters only while
    the editorial layer still drew the reader's evidence from every addressed cluster.
    The two disagreed by exactly the unreadable clusters, so a badge saying two reports
    offered three — which is the failure ``counted_clusters`` exists to prevent.
    """
    answers = ev_answers(
        ["us_government", "us_government", "us_government"],
        ["trump_administration", "trump_administration", "universities"],
    )
    # CN_00000003 answered in the badge's category, but we only ever held its lead.
    articles = [
        _partial(a) if a.article_id == "CN_00000003" else a for a in EV_ARTICLES
    ]
    page = ev_page()
    angle = page.angles[0]
    side = next(s for s in angle.sides if s.group_id == "cn")

    counted = counted_clusters(
        side,
        angle,
        ev_finding(),
        answers,
        readable=readable_clusters_of_articles(articles),
    )
    assert "RC-CN-00000003" not in counted
    assert counted == ["RC-CN-00000001", "RC-CN-00000002"]

    # …and with no universe given, the pre-0.5.0 behaviour is unchanged.
    assert len(counted_clusters(side, angle, ev_finding(), answers)) == 3


def test_answer_label_must_name_the_category_the_badge_counts():
    data = ev_page().model_dump(mode="json")
    data["angles"][0]["sides"][0]["answer_category"] = "universities"
    report = check_page(ReaderPage.model_validate(data), EV_ARTICLES, [ev_finding()])
    assert any("is not the category the badge counts" in e for e in report.errors)


def test_a_shared_answer_is_the_same_words_on_both_cards():
    """When both sides answer the same thing, both cards say so, joined by =."""
    shared = ev_finding(
        kind="consensus", cn_top="us_government", us_top="us_government"
    )
    data = ev_page().model_dump(mode="json")
    data["angles"][0]["kind"] = "consensus"
    data["angles"][0]["sides"][1]["answer_category"] = "us_government"
    data["angles"][0]["sides"][1]["answer_label"] = {
        "values": {"en": "The US government", "zh-CN": "美国政府"}
    }
    report = check_page(ReaderPage.model_validate(data), EV_ARTICLES, [shared])
    assert any("shared_answer_label" in e for e in report.errors)

    data["angles"][0]["shared_answer_label"] = {
        "values": {"en": "The US government", "zh-CN": "美国政府"}
    }
    page_record = ReaderPage.model_validate(data)
    assert check_page(page_record, EV_ARTICLES, [shared]).ok
    answers = ev_answers(
        ["us_government", "us_government", "universities"],
        ["us_government", "us_government", "universities"],
    )
    html = render_page(
        page_record,
        EV_ARTICLES,
        manifest(),
        ev_stats(),
        lang="en",
        findings=[shared],
        answers=answers,
        question_set=question_set(),
    )
    # Every angle draws two cards and the relation between them; agreement
    # is two cards saying the same words, joined by the = connector.
    assert html.count('<div class="alabel">The US government</div>') == 2
    assert html.count('<div class="rel">') == 1


def test_a_source_chip_opens_our_record_before_the_publisher():
    answers = ev_answers(
        ["us_government", "us_government", "universities"],
        ["trump_administration", "trump_administration", "universities"],
    )
    html = render_ev(ev_page(), answers)
    assert 'data-sid="CN_00000001:P01:S01"' in html
    # the quote itself is no longer a bare outbound link
    assert 'class="ann evtable"' in html
    assert 'href="https://example.com/CN_00000001" rel="noopener"' not in html
    # …the URL travels in the detail-view payload instead
    assert '"url": "https://example.com/CN_00000001"' in html
    assert '"title": "CN headline 1"' in html


def test_the_appendix_carries_every_question_in_the_analyze_ranking():
    answers = ev_answers(
        ["us_government", "us_government", "universities"],
        ["trump_administration", "trump_administration", "universities"],
    )
    html = render_ev(ev_page(), answers)
    assert 'id="q-QST-aabb-river-light-002"' in html  # the storyline's question
    assert 'id="q-QST-aabb-river-light-003"' in html  # …and the one no angle used
    # the question with a finding ranks first; the one with none comes after
    assert html.index('id="q-QST-aabb-river-light-002"') < html.index(
        'id="q-QST-aabb-river-light-003"'
    )
    # the used question links back to its angle instead of repeating its table
    assert 'href="#angle-QST-aabb-river-light-002"' in html
    assert html.count("summary QST") == 0

    off = render_ev(ev_page(), answers, appendix=False)
    assert 'id="q-QST-aabb-river-light-003"' not in off


def test_angle_fragment_is_stable_when_editorial_rank_changes():
    answers = ev_answers(
        ["us_government", "us_government", "universities"],
        ["trump_administration", "trump_administration", "universities"],
    )
    original = ev_page()
    reranked = original.model_copy(
        update={"angles": [original.angles[0].model_copy(update={"rank": 7})]}
    )

    before = render_ev(original, answers)
    after = render_ev(reranked, answers)
    fragment = "#angle-QST-aabb-river-light-002"

    assert f'id="{fragment[1:]}"' in before
    assert f'id="{fragment[1:]}"' in after
    assert f'href="{fragment}"' in before
    assert f'href="{fragment}"' in after
    assert 'id="angle-1"' not in before
    assert 'id="angle-7"' not in after


def test_no_render_ships_more_than_half_of_any_one_article():
    """Non-negotiable 7: the appendix may not add up to the whole article."""
    articles = cluster_articles("CN", "zh-CN", 3, sentences=4) + cluster_articles(
        "US", "en", 3, sentences=4
    )
    answers = AnswerIndex(
        [cluster_answer("CN", i, "us_government", anchors=4) for i in (1, 2, 3)]
        + [
            cluster_answer("US", i, "trump_administration", anchors=4)
            for i in (1, 2, 3)
        ]
    )
    html, shipped, withheld = render_page(
        ev_page(),
        articles,
        manifest(),
        ev_stats(),
        lang="en",
        findings=[ev_finding()],
        answers=answers,
        question_set=question_set(),
        return_shipped=True,
    )
    from newsab_editorial.page_render import sentence_load

    for article_id, (used, total) in sentence_load(articles, shipped).items():
        assert used <= max(1, total // 2), f"{article_id}: {used}/{total}"
    assert withheld, "anchors past the budget should be listed by address, not shown"
    assert "badge off" in html


# --------------------------------------------------------------------------------------
# what the reader is shown, after the review of the first previews
# --------------------------------------------------------------------------------------


def test_a_side_is_named_by_its_short_tag_and_its_definition_rides_along():
    """ "中方", not "中文报道" — once, in a tag, with the group definition on hover."""
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert '<span class="badge gtag a"' in html and ">China side<" in html
    assert "Chinese-language coverage" in html  # the full label, in the tooltip
    assert 'data-tip="Chinese coverage — Chinese-language coverage"' in html


def test_the_reader_meets_the_reader_wording_of_the_question_not_the_annotators():
    """The lexicon wins over the annotation wording everywhere the question appears."""
    data = ev_page().model_dump(mode="json")
    data["lexicon"] = {
        "questions": {"QST-aabb-river-light-002": {"values": {"en": "Who is to blame here?"}}},
        "categories": {"us_government": {"values": {"en": "The US government"}}},
    }
    html = render_ev(
        ReaderPage.model_validate(data),
        ev_answers(["us_government"] * 3, ["trump_administration"] * 3),
    )
    assert "Who is to blame here?" in html
    assert '<span class="qm">Q:</span>' in html
    # the counting key never reaches the reader once it has words
    assert "The US government" in html
    assert ">us_government<" not in html


def test_a_count_carries_its_own_explanation():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    # With the finding at hand the tip states the whole chain (audit P12):
    # counted readable reports -> answered -> gave this answer.  The analysis denominator
    # can exclude unreadable collected reports, so the tooltip must not call it collected.
    assert "readable independent reports counted in this analysis" in html
    assert "independent reports we collected" not in html
    assert "answered this question" in html


@pytest.mark.parametrize(
    "key", ["badge_tip_top_full", "badge_tip_addressed", "rate_tip"]
)
def test_analysis_denominator_tooltips_do_not_call_readable_reports_collected(key):
    assert "readable independent reports counted in this analysis" in STRINGS[key]["en"]
    assert "collected" not in STRINGS[key]["en"]
    assert "本次分析计入的" in STRINGS[key]["zh-CN"]
    assert "采集到" not in STRINGS[key]["zh-CN"]


def test_the_hook_is_no_longer_drawn():
    """Retired in favour of angle 1; a page that still carries one renders without it."""
    data = ev_page().model_dump(mode="json")
    data["hook"] = {
        "text": {"values": {"en": "A pull quote nobody asked for."}},
        "claim_type": "corpus_aggregate",
        "computed_from": "FND-aabb-river-light-001",
        "evidence": [],
    }
    html = render_ev(
        ReaderPage.model_validate(data),
        ev_answers(["us_government"] * 3, ["trump_administration"] * 3),
    )
    assert "A pull quote nobody asked for." not in html


def test_the_annotation_tables_wait_in_a_modal_behind_one_button():
    """The record is long; a reader who wants it asks for it."""
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert 'data-open="ann-QST-aabb-river-light-002"' in html
    assert '<div class="modal" id="ann-QST-aabb-river-light-002" hidden>' in html
    assert 'data-tab="cn"' in html and 'data-tab="us"' in html


def test_a_missing_reader_word_is_a_warning_not_a_silent_key():
    report = check_page(
        ev_page(),
        EV_ARTICLES,
        [ev_finding()],
        ev_stats(),
        answers=ev_answers(["us_government"] * 3, ["trump_administration"] * 3),
    )
    assert any("no reader wording" in w for w in report.warnings), report.render()
    assert any("no reader label" in w for w in report.warnings), report.render()


# --------------------------------------------------------------------------------------
# the second review pass
# --------------------------------------------------------------------------------------


def registry() -> SourceRegistry:
    return SourceRegistry(
        sources=[
            {
                "id": "src",
                "name": {"values": {"en": "The Test Herald", "zh-CN": "测试先驱报"}},
                "url": "https://example.com/",
                "lang": "en",
                "country": "US",
                "category": "serious",
                "beat_scope": "general",
                "notes": {
                    "values": {
                        "en": "A newspaper invented for these tests.",
                        "zh-CN": "为测试虚构的一家报纸。",
                    }
                },
            }
        ],
        registry_version="reg-0.1.0",
        updated_at=NOW,
    )


def test_a_multi_fact_intro_is_a_list_not_a_wall():
    """One separately anchored fact per claim — past two of them, that is a list."""
    data = ev_page().model_dump(mode="json")
    data["intro"] = [
        {
            "text": {"values": {"en": f"Background fact {n}."}},
            "claim_type": "source_claim",
            "evidence": ["CN_00000001:P01:S01"],
        }
        for n in range(1, 4)
    ]
    html = render_ev(
        ReaderPage.model_validate(data),
        ev_answers(["us_government"] * 3, ["trump_administration"] * 3),
    )
    assert (
        '<ul class="intro"><li><span class="x">Background fact 1.</span></li>' in html
    )
    assert '<span class="n">01</span>' not in html


def test_every_label_is_a_badge_that_explains_itself():
    """No ⓘ anywhere: the page is consistent, so a badge is always the affordance.

    And only badges: a button or a link is self-evidently clickable, so hovering one
    explains nothing and only gets in the way.
    """
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert 'class="tip"' not in html
    for badge in (
        "badge kind",
        "badge strength supported",
        "badge count",
        "badge gtag",
    ):
        assert badge in html, badge
    # a count badge carries its own sentence rather than a neighbouring question mark
    assert re.search(r'class="badge count"[^>]*data-tip="', html)
    for control in re.findall(r'<button class="(?:qbtn|media)[^>]*>', html):
        assert "data-tip" not in control, control


def test_the_answered_rate_is_a_fraction_never_a_second_percentage():
    """Its numerator is the denominator of every share below it."""
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert "answered 3/3" in html
    assert "answered 3/3 (100%)" not in html


def test_the_storyline_badge_says_featured_not_where_it_went():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert ">featured<" in html
    assert "in the storyline, angle" not in html


def test_a_translated_quote_gets_an_inline_language_switch():
    """The top bar is gone; page-wide quote state is triggered beside a translated quote."""
    html = render_page(
        ev_page(),
        EV_ARTICLES,
        manifest(),
        ev_stats(),
        lang="zh-CN",
        findings=[ev_finding()],
        answers=ev_answers(["us_government"] * 3, ["trump_administration"] * 3),
        question_set=question_set(),
    )
    assert 'body[data-tr="translated"] .q.has-tr{display:none}' in html
    assert 'class="topbar"' not in html
    assert "data-tr-toggle" in html
    evidence = html.split('id="ev-1"')[1].split('<div id="floattip"', 1)[0]
    us_quote = evidence.split('data-panel="us"')[1].split("</div>")[0]
    assert '<span class="q has-tr">' in us_quote and '<span class="tx">' in us_quote
    # the Chinese quote on a Chinese page has nothing to switch to
    cn_quote = evidence.split('data-panel="cn"')[1].split("</div>")[0]
    assert '<span class="tx">' not in cn_quote


def test_the_timeline_plots_every_independent_report_and_opens_its_record():
    """The renderer ships the dates and the browser draws them.

    Granularity, tick density, dot size and lane height all depend on the width of the
    reader's window, which a server-side layout can only guess at.  What the renderer
    still owes is the data: one representative per reporting cluster, and the article
    record card each dot opens.
    """
    import json

    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert '<section class="panel timeline"' in html
    payload = json.loads(html.split('id="timeline-data">')[1].split("</script>")[0])
    plotted = {point["a"] for point in payload["points"]}
    index = json.loads(html.split('id="article-index">')[1].split("</script>")[0])
    assert len(plotted) == len(
        {article.reporting_cluster_id for article in EV_ARTICLES}
    )
    for article in EV_ARTICLES:
        assert article.article_id in index
    # it is an overview, so it sits between the briefing and the storyline…
    assert html.index('<section class="panel timeline"') < html.index(
        '<article class="angle"'
    )
    # …and each lane is named beside itself, not in a legend under the chart
    legend = html.split('id="tl-legend">')[1].split('<div class="tl-canvas"')[0]
    assert "China side" in legend and "US side" in legend


def test_the_report_search_results_do_not_trap_the_wheel():
    """A search must not leave the page unable to scroll.

    The results list is a panel in the page's own flow, not a modal.  It keeps its own
    scroll, but `overscroll-behavior:contain` stopped the wheel chaining to the page, so
    with the results filling the viewport nothing moved while the pointer was over them.
    """
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    rule = html.split(".search-results{list-style:none")[1].split("}")[0]
    assert "overflow-y:auto" in rule
    assert "overscroll-behavior" not in rule


def test_the_topic_search_field_draws_its_own_clear_control():
    """WebKit's own search cancel button is a colour emoji; the home page's is a cross."""
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert 'id="report-search-clear"' in html and 'href="#i-close"' in html
    assert '<symbol id="i-close"' in html
    assert ".search-field input::-webkit-search-cancel-button{-webkit-appearance:none;display:none}" in html


def test_the_timeline_plots_only_the_readable_reports_it_counts_elsewhere():
    """One counting universe, or the reader has to pick.

    The timeline used to total every sampled cluster while every badge below it counted
    the readable ones, so the page stated two different corpus sizes with no way to tell
    which one it meant.
    """
    import json

    from newsab_schema.readability import readable_clusters_of_articles

    articles = [_partial(EV_ARTICLES[0])] + list(EV_ARTICLES[1:])
    readable = readable_clusters_of_articles(articles)
    assert len(readable) < len({a.reporting_cluster_id for a in articles})
    html = render_page(
        ev_page(),
        articles,
        manifest(),
        ev_stats(),
        lang="en",
        findings=[ev_finding()],
        answers=ev_answers(["us_government"] * 3, ["trump_administration"] * 3),
        question_set=question_set(),
    )
    payload = json.loads(html.split('id="timeline-data">')[1].split("</script>")[0])
    assert len(payload["points"]) == len(readable)
    assert f"{len(readable)} independent reports in total" in html


def test_the_concept_cloud_denominator_is_the_readable_reports_too():
    """Same rule, same owner — and the checker re-derives it independently."""
    from newsab_editorial import concept_cloud
    from newsab_schema.readability import readable_clusters_of_articles

    articles = [_partial(EV_ARTICLES[0])] + list(EV_ARTICLES[1:])
    readable = readable_clusters_of_articles(articles)
    topics = {a.article_id: [{"pivot_en": "visa policy"}] for a in articles}
    clouds = concept_cloud.build_from_topics(topics, articles)
    assert sum(cloud.total for cloud in clouds.values()) == len(readable)


def test_an_outlet_name_opens_what_we_know_about_that_outlet():
    """The registry has carried reader-facing media copy since S1; the page now uses it."""
    html = render_page(
        ev_page(),
        EV_ARTICLES,
        manifest(),
        ev_stats(),
        lang="en",
        findings=[ev_finding()],
        answers=ev_answers(["us_government"] * 3, ["trump_administration"] * 3),
        question_set=question_set(),
        registry=registry(),
    )
    assert 'data-media="src"' in html
    assert '"media-index"' in html
    assert '<div class="modal" id="mediamodal" hidden>' in html
    # The card carries what the registry actually keeps, and nothing it used to guess at.
    assert "A newspaper invented for these tests." in html
    assert "ownership" not in html


def test_the_scope_we_signed_off_on_is_one_click_from_the_timeline():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert 'data-open="scopemodal"' in html
    assert "visa policy" in html  # the manifest's own include line


# --------------------------------------------------------------------------------------
# a cluster the analysis left out of its denominator must leave the page's
# evidence list too, or the badge and the reader count different things
# --------------------------------------------------------------------------------------


def test_a_peripheral_cluster_leaves_the_evidence_list_with_the_denominator():
    import json  # noqa: F811

    all_answers = [cluster_answer("CN", i, "us_government") for i in (1, 2, 3)]
    counted = AnswerIndex(all_answers, excluded_clusters=["RC-CN-00000003"])
    assert sorted(counted.for_group("QST-aabb-river-light-002", "cn")) == [
        "RC-CN-00000001",
        "RC-CN-00000002",
    ]
    # …and with no exclusions the index is unchanged, so every run built before
    # exclusions existed renders exactly as it did.
    assert len(AnswerIndex(all_answers).for_group("QST-aabb-river-light-002", "cn")) == 3


def test_load_excluded_clusters_reads_what_the_run_recorded(tmp_path):
    import json

    from newsab_editorial.page_checks import load_excluded_clusters

    assert load_excluded_clusters(tmp_path) == [], (
        "a run without run.json excludes nothing"
    )
    (tmp_path / "run.json").write_text(
        json.dumps({"inputs": {"peripheral_clusters_excluded": ["RC-CN-000000ff"]}}),
        encoding="utf-8",
    )
    assert load_excluded_clusters(tmp_path) == ["RC-CN-000000ff"]


# --------------------------------------------------------------------------------------
# the concept cloud (task_202608221347): two vocabularies, no comparison asserted
# --------------------------------------------------------------------------------------


def cloud_stats() -> dict:
    """Two questions, so the cloud has something to sum across."""
    return {
        "QST-aabb-river-light-002": {
            "question": "Who is blamed?",
            "tier": "template",
            "kind": "divergence",
            "groups": {
                "cn": {
                    "clusters_total": 10,
                    "clusters_addressed": 10,
                    "category_counts": {
                        "us_government": 6,
                        "universities": 3,
                        "students": 1,
                        "unclear": 4,
                    },
                },
                "us": {
                    "clusters_total": 40,
                    "clusters_addressed": 40,
                    "category_counts": {
                        "trump_administration": 20,
                        "universities": 25,
                        "students": 5,
                        "none_reported": 2,
                    },
                },
            },
        },
        "QST-aabb-river-light-003": {
            "question": "What happens next?",
            "tier": "reader",
            "kind": "consensus",
            "groups": {
                "cn": {
                    "clusters_total": 10,
                    "clusters_addressed": 10,
                    "category_counts": {"lawsuits": 8, "universities": 2},
                },
                "us": {
                    "clusters_total": 40,
                    "clusters_addressed": 40,
                    "category_counts": {"lawsuits": 30, "students": 8},
                },
            },
        },
    }


def cloud_page() -> ReaderPage:
    data = page().model_dump(mode="json")
    data["visuals"] = [
        {
            "kind": "concept_cloud",
            "caption": {"values": {"en": "Key concept cloud", "zh-CN": "关键概念云"}},
            "data_from": "qa_run:question_stats",
        }
    ]
    return ReaderPage.model_validate(data)


def test_the_cloud_counts_across_questions_and_drops_the_machinery_categories():
    from newsab_editorial.concept_cloud import build

    clouds = build(cloud_stats())
    # cn: 6+3+1 + 8+2 = 20 — `unclear` leaves the numerator *and* the denominator
    assert clouds["cn"].total == 20
    assert "unclear" not in clouds["cn"].concepts
    assert "none_reported" not in clouds["us"].concepts
    assert (
        clouds["cn"].concepts["universities"].count == 5
    )  # summed across two questions
    assert clouds["cn"].concepts["universities"].share == pytest.approx(0.25)


def test_each_column_is_ranked_by_its_own_share_never_mirrored():
    from newsab_editorial.concept_cloud import build

    clouds = build(cloud_stats())
    assert clouds["cn"].shown[:2] == ["lawsuits", "us_government"]
    assert clouds["us"].shown[:2] == ["lawsuits", "universities"]
    # the same concept sits at a different rank on each side — that gap is the point
    assert clouds["cn"].shown.index("universities") == 2
    assert clouds["us"].shown.index("universities") == 1


def test_below_the_threshold_is_hidden_but_never_silent():
    """A concept the cloud does not draw still carries its real numbers and a reason."""
    from newsab_editorial.concept_cloud import build

    clouds = build(cloud_stats(), threshold=0.10)
    students = clouds["cn"].concepts["students"]
    assert not students.shown and students.hidden_reason == "below_threshold"
    assert students.count == 1, "the count survives being undrawn"

    capped = build(cloud_stats(), threshold=0.0, cap=1)
    assert capped["cn"].shown == ["lawsuits"]
    assert capped["cn"].concepts["us_government"].hidden_reason == "capped"


def test_one_answer_is_hidden_even_when_its_share_exceeds_two_percent():
    """The stricter of 2% and two classified answers is the display floor."""
    from newsab_editorial.concept_cloud import build

    clouds = build(cloud_stats())
    students = clouds["cn"].concepts["students"]  # 1/20 = 5%
    assert students.share == pytest.approx(0.05)
    assert not students.shown
    assert students.hidden_reason == "below_threshold"


def test_size_is_share_and_the_two_sides_share_one_map():
    from newsab_editorial.concept_cloud import FONT_MAX_PX, FONT_MIN_PX, build, font_px

    clouds = build(cloud_stats())
    top = max(clouds[g].top_share for g in clouds)
    # the leader is set at the top of the range; half its share, half its full height
    assert font_px(top, top) == pytest.approx(FONT_MAX_PX)
    assert font_px(top / 2, top) == pytest.approx(FONT_MAX_PX / 2)
    # us "lawsuits" (30/75) outweighs cn "us_government" (6/20) across the midline
    assert font_px(clouds["us"].concepts["lawsuits"].share, top) > font_px(
        clouds["cn"].concepts["us_government"].share, top
    )


def test_the_rendered_cloud_recomputes_from_the_pinned_run():
    from newsab_editorial.page_checks import check_rendered_concept_cloud

    html = render_page(cloud_page(), ARTICLES, manifest(), cloud_stats(), lang="zh-CN")
    assert ">概念云</span>" in html
    assert "至少出现在 2 条回答中" in html
    assert '<span class="pct">40.0%</span>' in html  # cn lawsuits 8/20
    report = check_rendered_concept_cloud(html, cloud_stats(), ["cn", "us"])
    assert report.ok, report.render()

    # …and it is a real recomputation: move one count and the rendered page is refused
    moved = cloud_stats()
    moved["QST-aabb-river-light-003"]["groups"]["cn"]["category_counts"]["lawsuits"] = 5
    refused = check_rendered_concept_cloud(html, moved, ["cn", "us"])
    assert any("recomputes to" in error for error in refused.errors), refused.render()


def test_a_page_with_no_cloud_is_not_a_cloud_that_failed():
    from newsab_editorial.page_checks import check_rendered_concept_cloud

    html = render_page(page(), ARTICLES, manifest(), cloud_stats(), lang="en")
    assert 'class="cloudbox"' not in html
    assert check_rendered_concept_cloud(html, cloud_stats(), ["cn", "us"]).ok


def test_the_cloud_sits_below_the_story_it_asserts_nothing_about():
    """The cloud ends the analysis; the report-search utility follows it.

    It used to sit between the timeline and the storyline, which put the page's only
    non-assertion between the reader and the assertions. Search is navigation, not a
    second analysis module, and belongs between the cloud and footer.
    """
    html = render_page(
        cloud_page(),
        ARTICLES,
        manifest(),
        cloud_stats(),
        lang="en",
        findings=[finding()],
    )
    assert html.index('class="panel timeline"') < html.index(
        'id="angle-QST-aabb-river-light-002"'
    )
    assert html.index('id="angle-QST-aabb-river-light-002"') < html.index(
        'id="concept-cloud"'
    )
    assert html.index('id="concept-cloud"') < html.index('id="report-search"')
    assert html.index('id="report-search"') < html.index("<footer")
    assert 'id="report-search-index"' in html


def test_the_cloud_must_name_the_run_it_sums():
    data = cloud_page().model_dump(mode="json")
    data["visuals"][0]["data_from"] = "ontology:concept_map"
    report = check_page(
        ReaderPage.model_validate(data), ARTICLES, [finding()], cloud_stats()
    )
    assert any("question_stats" in error for error in report.errors), report.render()


def test_a_cloud_cannot_be_pinned_to_one_question():
    import pydantic

    data = cloud_page().model_dump(mode="json")
    data["visuals"][0]["question_id"] = "QST-aabb-river-light-002"
    with pytest.raises(
        pydantic.ValidationError, match="collapses the question dimension"
    ):
        ReaderPage.model_validate(data)


def test_a_page_whose_analysis_run_moved_without_it_is_refused():
    """The numbers recompute against a run the page does not admit to using."""
    report = check_page(
        page(), ARTICLES, [finding()], pinned_qa_run="qa-20260821000000000000-11111111"
    )
    assert any(
        "every number on this page is checked against" in e for e in report.errors
    )


# --------------------------------------------------------------------------------------
# the user's frontend pass
# --------------------------------------------------------------------------------------


def test_the_storyline_is_three_tabs_that_count_their_angles():
    """A kind with no angle keeps its tab and states its zero.

    On some topics that zero is the loudest thing the data has to say — a topic can
    produce five agreements and not one divergence — and a tab that disappears when
    empty hides exactly the finding a reader would most want to see.
    """
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert '<span class="n">(1)</span>' in html  # divergence: the page's one angle
    assert html.count('<span class="n">(0)</span>') == 2  # agreement and silence, empty
    # the tab holding the highest-ranked angle is the one the reader lands on
    assert 'data-kindtab="divergence"' in html
    tabs = html.split('<div class="story-tabs"')[1].split("</div>")[0]
    assert 'class="on" aria-selected="true" data-tip=' in tabs
    assert tabs.index('data-kindtab="divergence"') < tabs.index(
        'data-kindtab="attention_gap"'
    )
    # the kind's explanation rides on the tab, where the kind badge used to be
    assert "The most common answer differs between the two sides." in tabs
    # an empty tab is not an empty page: it says why it is empty
    assert "We found no supported agreement" in html


def test_a_cluster_id_is_a_way_into_the_report_it_names():
    """The middle record level, missing until this round.

    Every count on the page is made of reporting clusters, and until this round a reader
    could open a *sentence* and an *article* but not the thing being counted.
    """
    import json

    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    clusters = json.loads(html.split('id="cluster-index">')[1].split("</script>")[0])
    for article in EV_ARTICLES:
        entry = clusters[article.reporting_cluster_id]
        assert article.article_id in entry["articles"]
    assert '<div class="modal" id="clustermodal" hidden>' in html
    assert 'data-cluster="RC-CN-00000001"' in html
    assert "RC-CN-00000001 · 1 article" in html
    assert "article(s)" not in html


def test_a_question_that_asserts_nothing_gets_no_statistics_panel():
    """No hypothesis, no explanation of one.

    ``QST-aabb-river-light-003`` reaches no finding, so its data card carries no strength chip,
    no interval and no statistics icon — only its rates and its distribution.
    """
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert 'data-open="stat-QST-aabb-river-light-002"' in html
    assert 'data-open="stat-QST-aabb-river-light-003"' not in html
    assert '<div class="modal" id="stat-QST-aabb-river-light-003"' not in html
    # …and the panel that does exist explains the finding in words, not in code names
    panel = html.split('id="stat-QST-aabb-river-light-002"')[1].split("</div></div>")[0]
    assert "top_category_share_diff" not in panel
    assert "90% confidence interval" in panel


def test_the_cloud_can_count_what_the_reports_are_about():
    """The second source: topic phrases, one count per report.

    A phrase repeated across the articles of one reporting cluster counts once — the same
    denominator discipline every other number on the site follows — and the side's total
    is its whole set of reports, not only those carrying a record.
    """
    from newsab_editorial.concept_cloud import build_from_topics

    articles = cluster_articles("CN", "zh-CN", 3) + cluster_articles("US", "en", 3)
    # CN_00000001 and CN_00000002 are separate clusters; both raise "quota cut".
    topics = {
        "CN_00000001": [{"pivot_en": "quota cut"}, {"pivot_en": "prices"}],
        "CN_00000002": [{"pivot_en": "quota cut"}],
        "US_00000001": [{"pivot_en": "quota cut"}, {"pivot_en": "quota cut"}],
    }
    clouds = build_from_topics(topics, articles, threshold=0.0, min_count=1)
    assert clouds["cn"].concepts["quota cut"].count == 2
    assert clouds["cn"].total == 3  # the third report has no record, and still counts
    assert (
        clouds["us"].concepts["quota cut"].count == 1
    )  # one cluster, however often said
    assert "prices" not in clouds["us"].concepts


def test_an_open_ended_window_says_the_day_we_stopped_collecting():
    """ "Still open" told a reader nothing they could use."""
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    scope = html.split('id="scopemodal"')[1].split("</div></div>")[0]
    assert "still open" not in scope
    assert f"{NOW.date().isoformat()} (the day we collected)" in scope
    # the per-side targets are named by the side's own tag, not by its group id
    assert ">cn 20<" not in scope


def test_the_method_and_page_record_are_both_renderer_owned():
    """Two panels, not one appendix.

    The page record is pure artifact metadata: legacy writer notes never render.
    """
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    method = html.split('id="methodmodal"')[1].split('id="disclosuremodal"')[0]
    disclosure = html.split('id="disclosuremodal"')[1].split("</div></div>")[0]
    assert "independent report" in method
    assert "wrt-202608200000-00000001" not in method  # no run id in the standing panel
    assert "Page record" in disclosure
    assert "Corpus snapshot" in disclosure
    assert "qa-20260820040000000000-00000001" in disclosure
    assert "Counts are over independent reporting clusters." not in disclosure
    assert "Every stage of this page" not in disclosure


def test_page_record_resolves_normalization_timestamps_versions_and_models():
    digest = "sha256:" + "1" * 64

    def entry(run_id, skill_id, version, *, inputs=(), model=None, counters=None):
        return ManifestEntry(
            skill_id=skill_id,
            skill_version=version,
            model_id=model,
            run_id=run_id,
            topic_id=TOPIC,
            inputs=list(inputs),
            output_hashes={"artifact": digest},
            counters=dict(counters or {}),
            timestamp=NOW,
        )

    record = page()
    normalization = "nrm-20260820035000000000-00000001"
    entries = [
        entry(
            record.how_we_counted.corpus_run_id,
            "collect",
            "0.4.0",
            counters={"articles": 18, "reporting_clusters": 17},
        ),
        entry(
            record.how_we_counted.questions_run_id,
            "annotate",
            "0.8.0",
            model="claude-opus-5",
        ),
        entry(
            record.how_we_counted.answers_run_id,
            "annotate",
            "0.8.0",
            model="claude-sonnet-5",
        ),
        entry(normalization, "normalize", "0.3.0", model="claude-sonnet-5"),
        entry(
            record.how_we_counted.qa_run_id,
            "analyze",
            "0.4.0",
            inputs=(normalization,),
        ),
        entry(record.provenance.run_id, "write", "0.14.2", model="gpt-5"),
    ]

    components = build_page_components(record, manifest(), entries)

    assert [component.key for component in components] == [
        "scope",
        "corpus",
        "questions",
        "answers",
        "normalization",
        "analysis",
        "page",
    ]
    assert (
        next(c for c in components if c.key == "normalization").run_id == normalization
    )
    assert all(component.timestamp == NOW for component in components)
    assert all(component.version for component in components)
    by_key = {component.key: component for component in components}
    # The model of each step is what replaced the content hash a reader could not use.
    assert by_key["questions"].model_id == "claude-opus-5"
    # A deterministic stage records no model, and the page says nothing rather than
    # claiming an absence.
    assert by_key["analysis"].model_id is None
    assert by_key["corpus"].counters["reporting_clusters"] == 17
    # Nobody signed this fixture's scope but the contributor answers for it either way.
    assert by_key["scope"].actor == "rwen"
    assert by_key["page"].actor == "rwen"
    assert not by_key["page"].actor_is_stand_in


def test_page_record_names_the_run_that_wrote_the_sentences():
    """``page.provenance`` names the renderer; the writer is one ledger hop away."""
    digest = "sha256:" + "1" * 64

    def entry(run_id, skill_id, *, inputs=(), model=None, counters=None):
        return ManifestEntry(
            skill_id=skill_id,
            skill_version="0.14.0",
            model_id=model,
            run_id=run_id,
            topic_id=TOPIC,
            inputs=list(inputs),
            output_hashes={"artifact": digest},
            counters=dict(counters or {}),
            timestamp=NOW,
        )

    record = page().model_copy(
        update={
            "provenance": Provenance(
                skill_version="RL-0.15.2",
                model_id="gpt-5",
                run_id="rl-20260825153200000000-00000001",
                timestamp=NOW,
            )
        }
    )
    write_run = "edt-20260824152000000000-00000001"
    entries = [
        entry(record.how_we_counted.corpus_run_id, "collect"),
        entry(record.how_we_counted.questions_run_id, "annotate"),
        entry(record.how_we_counted.answers_run_id, "annotate"),
        entry(record.how_we_counted.qa_run_id, "analyze"),
        entry(write_run, "write", model="gpt-5.6-sol", counters={"angles": 5}),
        entry(
            "rl-20260824180600000000-00000001",
            "render-localize",
            inputs=(write_run,),
        ),
        entry(
            record.provenance.run_id,
            "render-localize",
            model="gpt-5",
            inputs=("rl-20260824180600000000-00000001",),
            counters={"languages": 2},
        ),
    ]

    components = build_page_components(record, manifest(), entries)
    by_key = {component.key: component for component in components}
    assert [c.key for c in components][-2:] == ["write", "page"]
    assert by_key["write"].run_id == write_run
    assert by_key["write"].model_id == "gpt-5.6-sol"


def test_an_ai_stand_in_reviewer_is_named_as_one():
    """A stand-in has to reach the published record, not only the ledger."""
    stand_in = manifest().model_copy(
        update={"review_stand_in_model_id": "claude-opus-5"}
    )
    components = build_page_components(page(), stand_in, ())
    review = next(c for c in components if c.key == "page")
    assert review.actor == "claude-opus-5"
    assert review.actor_is_stand_in


def test_the_page_record_says_which_language_the_review_was_read_in():
    """An approval is of one rendering, in one language.

    It lives on the manifest beside the stand-in for the same reason — the page states
    who reviews it before it is rendered, and nothing is injected into approved bytes
    afterwards.  A manifest written before the field existed simply says who, and no more.
    """
    from newsab_editorial.render.modals import disclosure_modal

    reviewed = manifest().model_copy(update={"review_locale": "zh-CN"})
    component = next(
        c for c in build_page_components(page(), reviewed, ()) if c.key == "page"
    )
    assert component.actor_locale == "zh-CN"
    assert "（审核语言：中文）" in disclosure_modal([component], (), "zh-CN")
    assert "(review language: Chinese)" in disclosure_modal([component], (), "en")
    silent = next(c for c in build_page_components(page(), manifest(), ()) if c.key == "page")
    assert silent.actor_locale is None
    assert "review language" not in disclosure_modal([silent], (), "en")


def test_the_reviewer_language_is_not_part_of_the_scope_the_user_signed():
    """Adding it must not stale an approval already on disk."""
    base = manifest()
    assert base.scope_hash() == base.model_copy(
        update={"review_locale": "zh-CN"}
    ).scope_hash()


def _gap_row():
    """One question whose only finding is an attention gap — no modal strength at all."""
    from newsab_editorial.evidence import GroupRow, QuestionRow

    return QuestionRow(
        question_id="QST-aabb-river-light-003",
        text={"en": "What happens next?"},
        tier="reader",
        kind="attention_gap",
        stability=None,
        rate_diff={
            "quantity": "addressed_rate_diff",
            "group_a": "cn",
            "group_b": "us",
            "value": 0.67,
            "lo": 0.2,
            "hi": 0.9,
            "level": 0.9,
        },
        groups=[
            GroupRow(
                group_id="cn",
                clusters_total=3,
                clusters_addressed=3,
                category_counts={"us_government": 3},
                top_categories=["us_government"],
                clusters=[],
            ),
            GroupRow(
                group_id="us",
                clusters_total=3,
                clusters_addressed=1,
                category_counts={"universities": 1},
                top_categories=["universities"],
                clusters=[],
            ),
        ],
        attention_gap={
            "finding_id": "FND-aabb-river-light-009",
            "rank": 2,
            "strength": "supported",
            "stability": 0.97,
            "total_silence": False,
        },
    )


def test_a_gap_only_question_still_says_how_it_was_judged():
    """Its strength lives on the gap finding, not on a modal one (regression).

    Reading ``strength`` straight off the row makes the one kind the third statistics
    template was written for the one kind that never reaches it.
    """
    from newsab_editorial.render.qcard import appendix_row
    from newsab_editorial.render.stats import DEFAULT_THRESHOLDS, stat_paragraphs
    from newsab_editorial.page_render import group_meta

    groups = group_meta(manifest(), "en")
    row = _gap_row()
    lines = stat_paragraphs(ev_page(), row, groups, DEFAULT_THRESHOLDS, "en")
    assert lines, "the gap question got no statistics panel"
    assert "97%" in lines[0] and "1000" in lines[0]
    assert "+67%" in lines[1] and "China side: 3/3" in lines[1]
    summary = appendix_row(
        ev_page(), row, groups, DEFAULT_THRESHOLDS, "en", position=2, total=2
    ).split("</summary>")[0]
    assert ">strong<" in summary


def test_group_meta_prefers_the_lexicon_over_the_manifest_but_falls_back_to_it():
    """A side's badge name, tooltip label and definition all used to
    come straight from ``TopicManifest.groups`` at render time — a manifest field
    ``TopicManifest.scope_hash()`` covers, so it can only ever carry the languages
    touchpoint one approved (a manifest that never gained ru/fr/ko/hi/es/ja/ar for these
    three fields is why a side's label stayed English on the nine-locale preview).
    ``page.lexicon.group_labels`` /
    ``group_short_labels`` / ``group_definitions`` exist to carry the extra languages
    without touching the manifest; the renderer must prefer them when present and still
    fall back to the manifest when a language or a group_id is missing from them."""
    from newsab_schema.common import MultiLangText
    from newsab_schema.models.page import ReaderLexicon
    from newsab_editorial.render.common import group_meta

    m = manifest()
    lexicon = ReaderLexicon(
        group_short_labels={
            "cn": MultiLangText(values={"ru": "китайская сторона"}),
        },
        group_labels={
            "cn": MultiLangText(values={"ru": "Освещение на китайском языке"}),
        },
        group_definitions={
            "cn": MultiLangText(values={"ru": "Репортажи на китайском языке"}),
        },
    )
    with_lexicon = group_meta(m, "ru", lexicon=lexicon)
    assert with_lexicon["cn"]["short"] == "китайская сторона"
    assert with_lexicon["cn"]["label"] == "Освещение на китайском языке"
    assert with_lexicon["cn"]["definition"] == "Репортажи на китайском языке"
    # "us" has no lexicon entry at all — degrades to the manifest's English (it has no
    # Russian either), never fabricates a translation.
    assert with_lexicon["us"]["short"] == "US side"
    # No lexicon at all (the older call shape) behaves exactly as before.
    without_lexicon = group_meta(m, "ru")
    assert without_lexicon["cn"]["short"] == "China side"
    assert without_lexicon == group_meta(m, "ru", lexicon=None)
    # A lexicon entry for a language the caller is not asking about does not leak in.
    assert group_meta(m, "en", lexicon=lexicon)["cn"]["short"] == "China side"


def _quiet_row(kind: str):
    """A silence sitting beside a modal comparison that asserts nothing."""
    row = _gap_row()
    return dataclasses.replace(row, kind=kind, quiet_group="us")


def test_a_silence_is_the_only_kind_the_question_is_labelled_with():
    """One question, one angle, and silence outranks every kind.

    A gap says one side barely answered — which is exactly the reason not to read that
    side's leading answer against the other's, so a consensus or divergence beside it is
    not a second finding but a claim the gap has already withdrawn.  "No pattern"
    and "thin data" lose for the mirror reason: they say *we assert nothing*, and
    printing them beside a silence told the reader both at once.
    """
    from newsab_editorial.render.qcard import appendix_row, card_kinds, question_block
    from newsab_editorial.render.stats import DEFAULT_THRESHOLDS
    from newsab_editorial.page_render import group_meta

    groups = group_meta(manifest(), "en")
    losers = (">No pattern<", ">Thin data<", ">Agreement<", ">Divergence<")
    for kind in ("no_significant_relation", "too_thin", "consensus", "divergence"):
        row = _quiet_row(kind)
        assert card_kinds(row) == (["attention_gap"], "supported", 0.97)
        summary = appendix_row(
            ev_page(), row, groups, DEFAULT_THRESHOLDS, "en", position=2, total=2
        ).split("</summary>")[0]
        card = question_block(
            ev_page(), row, groups, DEFAULT_THRESHOLDS, "en", position=2, total=2
        )
        for rendered in (summary, card):
            assert ">Silence<" in rendered
            assert not any(loser in rendered for loser in losers)
        # One kind, one strength chip: the gap's own.
        assert summary.count('class="badge strength') == 1
        assert ">strong<" in summary
        # The panel that was missing on three of four silences.
        assert 'data-open="stat-QST-aabb-river-light-003"' in card


def test_a_silence_panel_does_not_price_the_comparison_it_withdrew():
    """The effect size of a consensus read off a side that barely answered."""
    import dataclasses as _dc

    from newsab_editorial.render.stats import DEFAULT_THRESHOLDS, stat_paragraphs
    from newsab_editorial.page_render import group_meta

    groups = group_meta(manifest(), "en")
    row = _dc.replace(
        _quiet_row("consensus"),
        strength="weak",
        stability=0.8,
        delta={"quantity": "consensus_dominance", "group_a": "cn", "group_b": "us",
               "value": 0.7, "lo": 0.4, "hi": 0.9, "level": 0.9},
    )
    lines = stat_paragraphs(ev_page(), row, groups, DEFAULT_THRESHOLDS, "en")
    assert len(lines) == 2, lines
    assert not any("shared leading answer" in line for line in lines)


def test_a_silence_panel_opens_on_the_two_answer_rates_not_on_a_shared_answer():
    """The one silence that had a panel opened with the *consensus* sentence."""
    from newsab_editorial.render.stats import DEFAULT_THRESHOLDS, stat_paragraphs
    from newsab_editorial.page_render import group_meta

    groups = group_meta(manifest(), "en")
    lines = stat_paragraphs(
        ev_page(), _quiet_row("no_significant_relation"), groups, DEFAULT_THRESHOLDS, "zh-CN"
    )
    assert lines
    assert lines[0].startswith("双方的回答率分别是 **33%**（低于 10%）和 **100%**")
    assert "最常见的答案" not in lines[0]
    # The second bullet is the one ruled correct; it stays.
    assert "回答率差值" in lines[1]


def test_the_silent_side_gives_one_answer_wording_whatever_the_count():
    """Two wordings invited "a small answer" to be read where there is no answer."""
    from newsab_editorial.render.strings import s

    assert s("silent_answer", "zh-CN") == "（回答率过低）"
    assert s("silent_answer", "en") == "(answer rate too low)"


def test_the_statistics_panel_quotes_the_answer_cards_own_wording():
    """A category label and an angle's answer label are two localizations of one answer.

    Printing one in the panel and the other on the card beside it read as two different
    answers.
    """
    from newsab_editorial.render.stats import DEFAULT_THRESHOLDS, stat_paragraphs
    from newsab_editorial.page_render import group_meta

    page = ev_page()
    angle = page.angles[0]
    groups = group_meta(manifest(), "en")
    row = dataclasses.replace(
        _gap_row(),
        question_id=angle.question_id,
        kind="divergence",
        strength="weak",
        stability=0.8,
        attention_gap=None,
    )
    line = stat_paragraphs(page, row, groups, DEFAULT_THRESHOLDS, "en")[0]
    for side in angle.sides:
        if side.answer_label and side.answer_category in ("us_government", "universities"):
            assert f"**{side.answer_label.values['en']}**" in line


def test_the_answer_rate_difference_is_stated_left_minus_right():
    """The run records whichever pair it drew; a sign that disagrees with the two rates
    printed beside it reads as an arithmetic error."""
    from newsab_editorial.render.stats import DEFAULT_THRESHOLDS, stat_paragraphs
    from newsab_editorial.page_render import group_meta

    groups = group_meta(manifest(), "en")
    row = _gap_row()
    flipped = dataclasses.replace(
        row,
        rate_diff={**row.rate_diff, "group_a": "us", "group_b": "cn",
                   "value": -0.67, "lo": -0.9, "hi": -0.2},
    )
    assert "+67%" in stat_paragraphs(ev_page(), row, groups, DEFAULT_THRESHOLDS, "en")[1]
    assert "+67%" in stat_paragraphs(ev_page(), flipped, groups, DEFAULT_THRESHOLDS, "en")[1]


def test_the_statistics_panel_speaks_every_halo_locale_not_english_leftovers():
    """``stat_blocks`` used to build the phenomenon / reproducibility /
    rate / effect-size bullets from literal ``if lang.startswith("zh") else`` Python
    branches — every locale that was neither English nor Chinese silently got the English
    sentence, which is exactly the residue found in the nine-locale preview.
    This pins the fix at the source: every halo locale's rendered
    bullet must actually differ from the English one once the same finding is formatted,
    for every kind the panel covers (a silence, a consensus, a divergence, each with a
    rate line and — off the silence — an effect-size line)."""
    from newsab_editorial.render.stats import DEFAULT_THRESHOLDS, stat_paragraphs
    from newsab_editorial.page_render import group_meta

    page = ev_page()
    rows = {
        "silence": _quiet_row("no_significant_relation"),
        "consensus": dataclasses.replace(
            _quiet_row("consensus"),
            strength="weak",
            stability=0.8,
            attention_gap=None,
            delta={"quantity": "consensus_dominance", "group_a": "cn", "group_b": "us",
                   "value": 0.7, "lo": 0.4, "hi": 0.9, "level": 0.9},
        ),
        "divergence": dataclasses.replace(
            _gap_row(), kind="divergence", strength="weak", stability=0.8, attention_gap=None
        ),
    }
    for kind, row in rows.items():
        en_lines = stat_paragraphs(page, row, group_meta(manifest(), "en"), DEFAULT_THRESHOLDS, "en")
        assert en_lines, kind
        for locale in ("ru", "fr", "ko", "hi", "es", "ja", "ar"):
            lines = stat_paragraphs(
                page, row, group_meta(manifest(), locale), DEFAULT_THRESHOLDS, locale
            )
            assert len(lines) == len(en_lines), (kind, locale)
            for en_line, line in zip(en_lines, lines):
                assert line != en_line, (kind, locale, line)


def test_attention_gap_tooltip_states_the_rate_difference_rule():
    """The rule is quiet < 10% AND a >=25pp gap, never "the loud side exceeds 25%".

    The old copy named a threshold the analyzer never applies: a
    reader checking a 30%-vs-3% gap against it would conclude the page contradicts
    itself.  A run older than qa-0.4.0 pins no ``silent_max_rate`` at all, and
    ``kind_chip`` routes it to its own tip rather than rendering the bare key.
    """
    from newsab_editorial.render.stats import DEFAULT_THRESHOLDS, kind_chip

    for lang, wanted in (
        ("zh-CN", "一方回答率低于 10%，另一方至少高出 25%"),
        ("en", "below 10%; the other side&#x27;s is at least 25% higher"),
    ):
        chip = kind_chip("attention_gap", DEFAULT_THRESHOLDS, lang)
        assert wanted in chip, chip
        assert "超过 25%" not in chip and "exceeds 25%" not in chip

    legacy = {k: v for k, v in DEFAULT_THRESHOLDS.items() if k != "silent_max_rate"}
    for lang, wanted in (
        ("zh-CN", "另一方回答率至少高出 25%"),
        ("en", "response rate is at least 25% higher"),
    ):
        chip = kind_chip("attention_gap", legacy, lang)
        assert wanted in chip, chip
        assert "attention_gap_rate_legacy" not in chip


def test_the_rendered_topics_cloud_is_recomputed_too():
    """The trial source gets the same treatment as the one it may replace.

    Every number the *renderer* computes is re-derived from the artifacts and held
    against the finished HTML before the file is written — the same discipline a count
    badge gets one stage earlier. A second source is a second place that could drift.
    """
    from newsab_editorial.page_checks import check_rendered_concept_cloud

    topics = {
        "CN_00000001": [{"pivot_en": "quota cut"}, {"pivot_en": "prices"}],
        "CN_00000002": [{"pivot_en": "quota cut"}, {"pivot_en": "prices"}],
        "CN_00000003": [{"pivot_en": "quota cut"}],
        "US_00000001": [{"pivot_en": "quota cut"}, {"pivot_en": "enrolment"}],
        "US_00000002": [{"pivot_en": "quota cut"}, {"pivot_en": "enrolment"}],
    }
    html = render_page(
        cloud_page(),
        EV_ARTICLES,
        manifest(),
        cloud_stats(),
        lang="en",
        findings=[finding()],
        topics_by_article=topics,
        cloud_source="topics_raised",
    )
    assert "quota cut" in html
    report = check_rendered_concept_cloud(
        html,
        cloud_stats(),
        ["cn", "us"],
        source="topics_raised",
        topics_by_article=topics,
        articles=EV_ARTICLES,
    )
    assert report.ok, report.render()
    # …and a page whose phrase counts do not recompute is refused
    thinner = dict(topics)
    thinner["CN_00000003"] = []
    broken = check_rendered_concept_cloud(
        html,
        cloud_stats(),
        ["cn", "us"],
        source="topics_raised",
        topics_by_article=thinner,
        articles=EV_ARTICLES,
    )
    assert not broken.ok


def test_a_writer_can_point_at_a_footnote_from_inside_the_prose():
    """``[^1]`` becomes one inline bubble trigger, with page-wide display numbers.

    There is no second marker row and no modal.  When both perspectives point to the same
    angle-local note, each visible occurrence gets a distinct page-wide number.  A marker
    with no note behind it is still dropped rather than rendered.
    """
    data = ev_page().model_dump(mode="json")
    angle = data["angles"][0]
    angle["caveat"] = {"values": {"en": "The two windows are not the same length."}}
    angle["sides"][0]["answer"] = {
        "text": {
            "values": {
                "en": "The coverage here reads the policy as the problem[^1], "
                "and a marker pointing past the list[^7] is dropped."
            }
        },
        "claim_type": "corpus_reading",
        "evidence": ["CN_00000001:P01:S01", "CN_00000002:P01:S01"],
    }
    angle["sides"][1]["answer"]["text"]["values"]["en"] += "[^1]"
    record = ReaderPage.model_validate(data)
    # a marker is punctuation, not a quantity: it must not make this a counted claim
    assert check_page(record, EV_ARTICLES, [ev_finding()]).ok
    html = render_ev(
        record, ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert html.count('class="fnref"') == 2
    assert ">[1]</button>" in html and ">[2]</button>" in html
    assert (
        html.count("The two windows are not the same length.") == 4
    )  # data-tip + aria-label
    assert 'class="note-refs"' not in html and 'id="fn-1-1"' not in html
    assert "[^7]" not in html and 'data-open="fn-' not in html
    assert "togglePinnedTip(tipped)" in html


def test_timeline_layout_has_odd_buckets_two_columns_and_large_hit_targets():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert "for (var day = 3;" in html and "day += 2" in html
    assert "Math.min(2, Math.max(1" in html
    assert "var candidates = [12, 11, 10, 9]" in html
    assert "'class': 'dot-hit'" in html and "r: 9" in html
    assert (
        "y: tlState.topPad" in html
    )  # every precision uses a shaded interval below the label


def test_butterfly_highlights_each_sides_own_lead_only():
    from newsab_editorial.evidence import GroupRow, QuestionRow
    from newsab_editorial.page_render import group_meta
    from newsab_editorial.render.qcard import butterfly

    row = QuestionRow(
        question_id="QST-aabb-river-light-002",
        text={"en": "Who is blamed?"},
        tier="template",
        kind="divergence",
        stability=1.0,
        rate_diff=None,
        groups=[
            GroupRow(
                group_id="cn",
                clusters_total=3,
                clusters_addressed=3,
                category_counts={"us_government": 2, "universities": 1},
                top_categories=["us_government"],
                clusters=[],
            ),
            GroupRow(
                group_id="us",
                clusters_total=3,
                clusters_addressed=3,
                category_counts={"us_government": 1, "universities": 2},
                top_categories=["universities"],
                clusters=[],
            ),
        ],
    )
    html = butterfly(ev_page(), row, group_meta(manifest(), "en"), "en")
    rows = re.findall(r'<div class="axis3(?: top)?">(.*?)</div>', html)
    usgov = next(
        row
        for row in rows
        if ">us government<" in row and "bar a" in row and "bar b" in row
    )
    universities = next(
        row
        for row in rows
        if ">universities<" in row and "bar a" in row and "bar b" in row
    )
    assert "bar a lead" in usgov and "bar b lead" not in usgov
    assert "bar b lead" in universities and "bar a lead" not in universities


def test_appendix_does_not_repeat_summary_metadata_inside_the_open_card():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    row = html.split('id="qrow-QST-aabb-river-light-002"')[1].split("</details>", 1)[0]
    summary, expanded = row.split("</summary>", 1)
    assert "badge rank" in summary and "badge story" in summary
    assert "badge rank" not in expanded and "badge kind" not in expanded
    assert 'data-open="ann-QST-aabb-river-light-002"' in expanded


def test_topics_raised_use_localized_concepts_without_changing_the_pivot_key():
    data = cloud_page().model_dump(mode="json")
    data["lexicon"]["topics"] = {
        "quota cut": {"values": {"en": "quota cut", "zh-CN": "配额削减"}},
        "prices": {"values": {"en": "prices", "zh-CN": "价格"}},
        "enrolment": {"values": {"en": "enrolment", "zh-CN": "入学"}},
    }
    topics = {
        "CN_00000001": [{"pivot_en": "quota cut", "source_phrase": "配额削减"}],
        "CN_00000002": [{"pivot_en": "quota cut", "source_phrase": "削减配额"}],
        "US_00000001": [{"pivot_en": "quota cut", "source_phrase": "quota cut"}],
        "US_00000002": [{"pivot_en": "quota cut", "source_phrase": "reduced quota"}],
    }
    html = render_page(
        ReaderPage.model_validate(data),
        EV_ARTICLES,
        manifest(),
        cloud_stats(),
        lang="zh-CN",
        findings=[finding()],
        topics_by_article=topics,
        cloud_source="topics_raised",
    )
    assert 'data-k="quota cut"' in html
    assert '<span class="lbl">配额削减</span>' in html
    assert '"localized": "配额削减"' in html
    report = check_page(
        ReaderPage.model_validate(data),
        EV_ARTICLES,
        [finding()],
        cloud_stats(),
        required_langs=("en", "zh-CN"),
        topics_by_article=topics,
    )
    assert report.ok, report.render()


# --------------------------------------------------------------------------------------
# the user's second frontend and writing-contract pass
# --------------------------------------------------------------------------------------


def test_answer_counts_are_compact_and_only_the_evidence_icon_opens_the_modal():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    angle = html.split('id="angle-QST-aabb-river-light-002"')[1].split("</article>", 1)[0]
    assert ">2/3</span>" in angle
    assert "3 / 3 independent reports" not in angle
    assert '<button class="badge count"' not in angle
    assert angle.count('class="acontrol"') == 2
    assert angle.count('data-open="ev-1"') == 2


def test_evidence_tabs_repeat_each_cards_fraction_and_name_the_selected_answer():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    modal = html.split('id="ev-1"')[1].split('<div id="floattip"', 1)[0]
    assert ">China side 2/3</button>" in modal
    assert ">US side 2/3</button>" in modal
    assert "Reports supporting “The US government”" in modal
    assert '<div class="modal-meta"><span class="qm">Q:</span>' in modal
    assert 'data-answer="The Trump administration"' in modal
    assert "Every report behind this answer" not in modal


def test_relation_marks_use_the_project_core_symbols():
    consensus = ev_finding(
        kind="consensus", cn_top="us_government", us_top="us_government"
    )
    data = ev_page().model_dump(mode="json")
    data["angles"][0]["kind"] = "consensus"
    data["angles"][0]["sides"][1]["answer_category"] = "us_government"
    data["angles"][0]["shared_answer_label"] = {"values": {"en": "The US government"}}
    equal_html = render_page(
        ReaderPage.model_validate(data),
        EV_ARTICLES,
        manifest(),
        ev_stats(),
        lang="en",
        findings=[consensus],
        answers=ev_answers(["us_government"] * 3, ["us_government"] * 3),
        question_set=question_set(),
    )
    assert '<use href="#i-consensus"></use>' in equal_html
    assert 'class="relmark consensus supported"' in equal_html
    divergence_html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert '<use href="#i-divergence"></use>' in divergence_html
    assert 'class="relmark divergence supported"' in divergence_html


def test_timeline_counts_articles_centres_summary_and_puts_scope_in_the_head():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    timeline = html.split('<section class="panel timeline"')[1].split("</section>", 1)[
        0
    ]
    head, rest = timeline.split('<div class="tl-wrap">', 1)
    assert 'data-open="scopemodal"' in head
    assert 'data-open="scopemodal"' not in rest
    assert (
        "China side: 3 reports / US side: 3 reports · 6 independent reports in total"
        in timeline
    )
    assert timeline.count("independent reports") == 1
    assert "justify-content:center" in html
    assert "tlLegend.style.paddingTop = topPad + 'px'" in html

    # A second publication instance in an existing cluster is not a second timeline dot
    # or a second number in the summary.
    from newsab_editorial.page_render import group_meta
    from newsab_editorial.render.timeline import timeline_section

    duplicate = EV_ARTICLES[0].model_copy(update={"article_id": "CN_00000004"})
    timeline_html, timeline_data = timeline_section(
        [*EV_ARTICLES, duplicate], group_meta(manifest(), "en"), "en"
    )
    assert len(timeline_data["points"]) == 6
    assert (
        "China side: 3 reports / US side: 3 reports · 6 independent reports in total"
        in timeline_html
    )


def test_nested_record_modals_always_stack_above_their_parent():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert "modal.style.zIndex = String(50 + stack.length * 10)" in html
    assert "top.modal.style.zIndex = ''" in html


def test_article_concepts_are_a_concept_switch_and_sentence_records_omit_them():
    html = render_page(
        ev_page(),
        EV_ARTICLES,
        manifest(),
        ev_stats(),
        lang="zh-CN",
        findings=[ev_finding()],
        answers=ev_answers(["us_government"] * 3, ["trump_administration"] * 3),
        question_set=question_set(),
    )
    assert '"topics_switch": "原文 ↔ 概念"' in html
    assert "var chips = card.text ? null : topicChips(card.topics);" in html
    assert "文/A" not in html


def test_angle_data_sits_on_the_rule_without_repeating_featured():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    angle = html.split('id="angle-QST-aabb-river-light-002"')[1].split("</article>", 1)[0]
    qdata = angle.split('<details class="qdata">')[1]
    assert "badge story" not in qdata
    assert "margin:-.78rem 0 .78rem auto" in html
    appendix = html.split('id="qrow-QST-aabb-river-light-002"')[1].split("</summary>", 1)[0]
    assert "badge story" in appendix


def test_strength_tooltip_uses_a_percentage_without_threshold_version_copy():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    angle = html.split('id="angle-QST-aabb-river-light-002"')[1].split("</article>", 1)[0]
    assert "observed stability: 97%" in angle
    assert "Threshold set" not in angle
    assert "qa-0.4.0" not in angle


def test_title_intro_and_concept_cloud_have_the_requested_separation():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert "header.head{max-width:none" in html
    assert "text-align:left" in html
    assert ".cloudbox{position:relative;margin-top:" in html
    assert ".cloudbox::before" not in html


def test_missing_topics_raised_localization_is_refused():
    topics = {"CN_00000001": [{"pivot_en": "quota cut", "source_phrase": "配额削减"}]}
    report = check_page(
        cloud_page(),
        EV_ARTICLES,
        [finding()],
        cloud_stats(),
        required_langs=("en", "zh-CN"),
        topics_by_article=topics,
    )
    assert any("page.lexicon.topics" in error for error in report.errors)


# --------------------------------------------------------------------------------------
# the user's third frontend pass
# --------------------------------------------------------------------------------------


def test_intro_uses_spacing_without_rules_between_paragraphs():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert ".intro{list-style:none;display:grid;gap:.6rem" in html
    assert ".intro{list-style:none;border-top" not in html
    assert "border-bottom:1px solid var(--rule)}\n.intro li" not in html


def test_the_brief_runs_full_width_and_marks_each_fact_with_a_bullet():
    """The brief is a list of separately-anchored facts.

    A centred 44rem column of unmarked lines read as one paragraph broken up by
    accident, and it was the only block on the page narrower than the rest.
    """
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert "max-width:none;margin-inline:0" in html
    assert ".intro li{display:grid;grid-template-columns:.55rem 1fr" in html
    assert ".intro li::before{content:\"\"" in html
    # One or two facts stay a sentence rather than a one-item list.
    assert '.intro.plain li::before{content:none}' in html


def test_answer_count_and_evidence_control_are_neutral_and_share_one_height():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    angle = html.split('id="angle-QST-aabb-river-light-002"')[1].split("</article>", 1)[0]
    duo = angle.split('<div class="duo">')[1].split('<div class="comm', 1)[0]
    assert duo.count('<span class="acontrol"><span class="badge count"') == 2
    assert duo.count('<button class="iconbtn"') == 2
    assert 'class="badge count a"' not in duo and 'class="iconbtn a"' not in duo
    assert ".acard .acontrol .iconbtn{width:1.35rem;height:1.35rem" in html
    assert '<div class="ahead"><span class="badge gtag a"' in angle


def test_weak_statistical_modal_names_the_seventy_percent_boundary():
    finding_data = ev_finding().model_dump(mode="json")
    finding_data["strength"] = "weak"
    finding_data["stability"] = 0.72
    stats = ev_stats()
    stats["QST-aabb-river-light-002"]["stability"] = 0.72
    html = render_page(
        ev_page(),
        EV_ARTICLES,
        manifest(),
        stats,
        lang="zh-CN",
        findings=[QAFinding.model_validate(finding_data)],
        answers=ev_answers(["us_government"] * 3, ["trump_administration"] * 3),
        question_set=question_set(),
    )
    modal = html.split('id="stat-QST-aabb-river-light-002"')[1].split("</div></div>", 1)[0]
    assert "上述现象在 <strong>72%</strong> 的情况下再次出现" in modal
    assert "&gt; 70% 统计可复现率" in modal
    assert "&gt; 95% 统计可复现率" not in modal


def test_appendix_has_q_prefixes_and_one_expand_collapse_icon():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    appendix = html.split('<section class="appendix">')[1].split("</section>", 1)[0]
    assert "Below is a complete data view" not in appendix
    assert appendix.count("data-apx-toggle") == 1
    assert 'href="#i-expand-all"' in appendix
    assert 'class="qsum"><span class="qm">Q:</span>' in appendix


def test_cloud_explanation_is_modal_and_section_help_is_consistent():
    html = render_page(cloud_page(), ARTICLES, manifest(), cloud_stats(), lang="zh-CN")
    cloud = html.split('id="concept-cloud"')[1].split("</section>", 1)[0]
    assert 'data-open="conceptcloudmodal"' in cloud
    assert "至少出现在 2 条回答中" not in cloud
    assert 'id="conceptcloudmodal"' in html
    assert 'data-open="scopemodal"' in html
    assert html.count('href="#i-help"') >= 2


def test_concept_switch_visually_marks_the_active_mode_and_original_follows_title():
    html = render_page(
        ev_page(),
        EV_ARTICLES,
        manifest(),
        ev_stats(),
        lang="zh-CN",
        findings=[ev_finding()],
        answers=ev_answers(["us_government"] * 3, ["trump_administration"] * 3),
        question_set=question_set(),
    )
    assert '"topics_source": "原文"' in html and '"topics_concept": "概念"' in html
    assert "source.className = topicsMode === 'source' ? 'on' : '';" in html
    title_append = html.index("tdTitle.appendChild(tb);")
    original_check = html.index("if (art.origin === 'original')", title_append)
    assert (
        title_append
        < original_check
        < html.index("tr.appendChild(tdOutlet)", title_append)
    )


def test_tabs_and_supporting_sections_share_the_new_icon_vocabulary():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    tabs = html.split('<div class="story-tabs"')[1].split("</div>", 1)[0]
    for symbol in ("i-consensus", "i-divergence", "i-silence"):
        assert f'href="#{symbol}"' in tabs
    assert 'href="#i-timeline"' in html
    assert 'href="#i-appendix"' in html
    assert '<h2><span class="qm">Q:</span>' in html


# --------------------------------------------------------------------------------------
# quick visual corrections after the third frontend pass
# --------------------------------------------------------------------------------------


def test_divergence_symbol_is_symmetric_around_the_centre():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    symbol = html.split('<symbol id="i-divergence"')[1].split("</symbol>", 1)[0]
    assert "M12 12C8.5 12" in symbol and "M12 12c3.5 0" in symbol
    assert '<circle cx="12" cy="12" r="1.8"' in symbol
    assert 'cx="8.5"' not in symbol


def test_timeline_and_cloud_icons_are_rounded_outline_cards():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    for symbol_id in ("i-timeline", "i-cloud"):
        symbol = html.split(f'<symbol id="{symbol_id}"')[1].split("</symbol>", 1)[0]
        assert '<rect x="4" y="3.5" width="16" height="17" rx="2" fill="none"' in symbol
    cloud = html.split('<symbol id="i-cloud"')[1].split("</symbol>", 1)[0]
    assert cloud.count('fill="none"') >= 4
    assert "opacity=" not in cloud


def test_help_button_draws_only_one_outer_circle():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    help_symbol = html.split('<symbol id="i-help"')[1].split("</symbol>", 1)[0]
    assert 'r="8"' not in help_symbol
    assert ".helpbtn{" in html and "border-radius:50%" in html


def test_weak_relation_is_quiet_and_tooltip_names_the_finding_kind():
    finding_data = ev_finding().model_dump(mode="json")
    finding_data["strength"] = "weak"
    finding_data["stability"] = 0.72
    stats = ev_stats()
    stats["QST-aabb-river-light-002"]["stability"] = 0.72
    html = render_page(
        ev_page(),
        EV_ARTICLES,
        manifest(),
        stats,
        lang="zh-CN",
        findings=[QAFinding.model_validate(finding_data)],
        answers=ev_answers(["us_government"] * 3, ["trump_administration"] * 3),
        question_set=question_set(),
    )
    angle = html.split('id="angle-QST-aabb-river-light-002"')[1].split("</article>", 1)[0]
    assert "证据偏弱 — 「分歧」结论的统计可复现率" in angle
    assert ".relmark.weak{border-color:color-mix" in html
    assert "border-style:dotted" in html


def test_collapsed_angles_are_tighter_but_open_angles_keep_the_old_spacing():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert ".angle{margin:0 0 clamp(2.5rem,5vw,3.75rem)" in html
    assert (
        ".angle:has(>details.qdata:not([open])){margin-bottom:clamp(1.35rem,2.7vw,2rem)}"
        in html
    )


def test_appendix_caret_follows_q_colour():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    appendix = html.split('<section class="appendix">')[1].split("</section>", 1)[0]
    assert (
        '<span class="chev"><svg aria-hidden="true"><use href="#i-caret"></use>'
        in appendix
    )
    assert ".qrow>summary .chev{" in html and "color:var(--accent)" in html


def test_article_concept_toggle_uses_the_active_theme_accent():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert ".topics-tr span.on{background:var(--accent);color:var(--panel)}" in html


def test_quick_layout_pass_aligns_timeline_range_and_groups_analysis():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    timeline = html.split('<section class="panel timeline"')[1].split("</section>", 1)[
        0
    ]
    assert (
        '<div class="panel-head timeline-head"><h3 class="section-title">' in timeline
    )
    assert '</div><p class="lede timeline-range">' in timeline
    assert ".timeline-heading{" not in html
    assert "padding-left:calc(var(--timeline-title-size)" not in html
    story = html.split('<section class="storyline">')[1].split("</section>", 1)[0]
    assert '<div class="panel-head story-head"><h2 class="section-title">' in story
    assert (
        'href="#i-perspectives"' in story
        and "<span>Angles</span>" in story
    )
    # The analysis containers are ordinary panels: the warm tint that used to set them
    # apart moved out of the shells and into the data cards inside them, achromatic.
    assert "--qa-surface" not in html
    story_css = html.split(".storyline{", 1)[1].split("}", 1)[0]
    assert "background:var(--panel)" in story_css
    assert "box-shadow:inset 0 0 0 1px var(--rule)" in story_css


def test_angles_icon_and_appendix_use_the_shared_section_language():
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    symbol = html.split('<symbol id="i-perspectives"')[1].split("</symbol>", 1)[0]
    assert symbol.count('<rect x="3.5" y="3.5" width="17" height="17" rx="3"') == 2
    assert '<circle cx="12" cy="12"' not in symbol
    assert "M12 3.5h5.5a3 3 0 0 1 3 3v11" in symbol
    assert 'cx="8.5" cy="8.5"' in symbol and 'cx="15.5" cy="15.5"' in symbol
    assert ".appendix{margin-top:" in html and "border:1px solid color-mix" in html
    assert "background:var(--panel)" in html.split(".appendix{", 1)[1].split("}", 1)[0]
    assert "details.qdata>summary{" in html
    # The pulled-up summary masks the border it sits on, so it wears the shell's colour.
    summary_css = html.split("details.qdata>summary{", 1)[1].split("}", 1)[0]
    assert "background:var(--panel)" in summary_css
    assert ".appendix h2{font:600 clamp(20px,2.2vw,25px)/1.35 var(--sans)" in html


def test_the_answer_cards_lift_and_the_data_card_sinks_on_a_neutral_ground():
    """Two surfaces, stated as literals: answer cards one step above the module that
    holds them, the question-data card one step below it and achromatic, because the
    bars it carries are a cool/warm pair."""
    html = render_ev(
        ev_page(), ev_answers(["us_government"] * 3, ["trump_administration"] * 3)
    )
    assert ".acard{background:var(--answer-surface);" in html
    assert "background:color-mix(in oklab,var(--a) 7%,var(--answer-surface))" in html
    assert "background:color-mix(in oklab,var(--b) 8%,var(--answer-surface))" in html
    # A silent side is the same card without a side, so its grey mixes into the same
    # surface rather than dropping to the page's --sunk.
    assert ".acard.silent{background:color-mix(in oklab,var(--muted) 7%,var(--answer-surface))" in html
    assert "background:var(--data-surface)}" in html.split(".qblock{", 1)[1].split("}", 1)[0] + "}"
    light, dark = "#F3F3F3", "#1C1C1C"
    assert f"--data-surface:{light}" in html and f"--data-surface:{dark}" in html
    for value in (light, dark):
        r, g, b = value[1:3], value[3:5], value[5:7]
        assert r == g == b, f"{value} is not achromatic"
    # Both dark blocks — the system default and the explicit choice — carry both.
    assert html.count("--answer-surface:#262C33") == 2
    assert html.count(f"--data-surface:{dark}") == 2


# --------------------------------------------------------------------------------------
# externalized data islands + the per-language overlay
# --------------------------------------------------------------------------------------

import json  # noqa: E402

from newsab_editorial.render.islands import (  # noqa: E402
    EXTERNAL_ISLANDS,
    asset_name,
    merge_island,
)


def _t122_answers():
    return ev_answers(
        ["us_government", "us_government", "universities"],
        ["trump_administration", "trump_administration", "universities"],
    )


def _t122_render(lang="en", **kwargs):
    return render_page(
        ev_page(),
        EV_ARTICLES,
        manifest(),
        ev_stats(),
        lang=lang,
        findings=[ev_finding()],
        answers=_t122_answers(),
        question_set=question_set(),
        **kwargs,
    )


def _island_json(html: str, island: str):
    return json.loads(html.split(f'id="{island}">')[1].split("</script>", 1)[0])


def test_externalized_islands_reference_content_hashed_assets():
    assets: dict[str, bytes] = {}
    html = _t122_render(data_assets_base="data", assets_out=assets)
    assert set(assets) == {
        re.search(rf'id="{island}" data-src="data/([^"]+)"', html).group(1)
        for island in EXTERNAL_ISLANDS
    }
    for name, blob in assets.items():
        island = name.split(".", 1)[0]
        # The filename is the integrity check: same content, same name, anywhere.
        assert name == asset_name(island, blob)
        json.loads(blob.decode("utf-8"))
    # The externalized nodes are empty references; the overlay rides inline.
    for island in EXTERNAL_ISLANDS:
        assert re.search(rf'id="{island}" data-src="data/[^"]+"></script>', html)
    assert 'id="lang-overlay">' in html


def test_data_islands_are_byte_identical_across_locales():
    en_assets: dict[str, bytes] = {}
    zh_assets: dict[str, bytes] = {}
    _t122_render(lang="en", data_assets_base="data", assets_out=en_assets)
    _t122_render(lang="zh-CN", data_assets_base="data", assets_out=zh_assets)
    assert en_assets == zh_assets


def test_external_and_inline_render_carry_the_same_hydrated_data():
    """Server-side merge (inline mode) and the base+overlay pair must be one dataset."""
    inline = _t122_render()
    assets: dict[str, bytes] = {}
    external = _t122_render(data_assets_base="data", assets_out=assets)
    overlay = _island_json(external, "lang-overlay")
    by_name = {name.split(".", 1)[0]: blob for name, blob in assets.items()}
    for island in EXTERNAL_ISLANDS:
        base = json.loads(by_name[island].decode("utf-8"))
        assert merge_island(island, base, overlay) == _island_json(inline, island)


def test_overlay_carries_the_language_dependent_display_fields():
    assets: dict[str, bytes] = {}
    html = _t122_render(lang="zh-CN", data_assets_base="data", assets_out=assets)
    overlay = _island_json(html, "lang-overlay")
    assert overlay["questions"]["QST-aabb-river-light-002"] == "谁被归咎？"
    assert overlay["groups"]["cn"]["short"]
    assert overlay["origins"]["original"]
    # The neutral base never bakes a display name in.
    sentence_base = json.loads(
        next(blob for name, blob in assets.items() if name.startswith("sentence-index."))
    )
    assert all("source" not in card for card in sentence_base.values())
    assert all("localized" not in topic
               for card in sentence_base.values()
               for topic in card.get("topics") or [])


def test_page_script_loads_and_hydrates_external_islands():
    from newsab_editorial.render.script import JS

    assert "data-src" in JS and "lang-overlay" in JS
    assert "hydrateIsland" in JS and "hydrateSearchDoc" in JS
    assert "data-islands" in JS  # the ready marker the browser gate waits for


def test_explanations_follow_the_cards_when_sides_are_stored_out_of_manifest_order():
    """The two paragraphs sit under the two cards, so both must use the manifest's order.

    Regression: `angle_html` sorted the cards into manifest order while
    `_commentary` iterated `angle.sides` as stored. Every earlier topic happened to store
    sides in manifest order, so nothing fired; the first topic whose analysis run ordered
    the groups the other way round rendered all five angles with each side's explanation
    under the OTHER side's card. No check could see it — the page data pairs correctly and
    only a human reading the render catches it.
    """
    p = page()
    angle = p.angles[0]
    angle.sides.reverse()  # store them the wrong way round
    assert [s.group_id for s in angle.sides] == ["us", "cn"]

    html = render_page(p, ARTICLES, manifest(), lang="en")
    cn_expl = angle.sides[1].answer.text.values["en"][:40]
    us_expl = angle.sides[0].answer.text.values["en"][:40]

    # The cards are drawn cn-then-us (manifest order); the paragraphs must match.
    assert html.index("China side") < html.index("US side")
    assert html.index(cn_expl) < html.index(us_expl), (
        "explanation columns are crossed: the cn paragraph must precede the us paragraph, "
        "because the cn card precedes the us card"
    )


# --------------------------------------------------------------------------------------
# Named things in an explanation paragraph must be anchored on the naming side
# --------------------------------------------------------------------------------------


def named_articles() -> list[Article]:
    """Two outlets per side, so "the side that names it" is a question with an answer."""
    out = []
    for article_id, source_id, lang, sentences, title in (
        ("CN_00000001", "thecover_cn", "zh-CN",
         ["新规将居留期限改为四年。", "IMAX 超前点映上座率达到 94%。"], "签证新规"),
        ("CN_00000002", "thepaper_cn", "zh-CN",
         ["澎湃的报道谈到考古发现。", "全球票房已超过 12 亿美元。"], "考古观察"),
        ("US_00000001", "variety_us", "en",
         ["The rule caps visas at four years.", "DEHOGA lodged an objection."], "Visa rule"),
        ("US_00000002", "deadline_us", "en",
         ["Colleges object to the 1,200 new places.", "The share was 12.1% of the haul."],
         "Colleges object"),
    ):
        out.append(
            article(article_id, lang, sentences, title).model_copy(
                update={"source_id": source_id}
            )
        )
    return out


def named_registry() -> SourceRegistry:
    def entry(source_id, en, url):
        return {
            "id": source_id,
            "name": {"values": {"en": en}},
            "url": url,
            "lang": "en",
            "country": "US",
            "category": "serious",
            "beat_scope": "general",
            "notes": {"values": {"en": "An outlet invented for these tests."}},
        }

    return SourceRegistry(
        sources=[
            # "Cover News" is registered; the page writes "The Cover".
            entry("thecover_cn", "Cover News", "https://www.thecover.cn/"),
            entry("thepaper_cn", "The Paper", "https://www.thepaper.cn/"),
            entry("variety_us", "Variety", "https://variety.com/"),
            # Registered under the long form only; the page writes "Sfen".
            entry("deadline_us", "Sfen — Revue Generale Nucleaire", "https://www.sfen.org/"),
        ],
        registry_version="reg-0.1.0",
        updated_at=NOW,
    )


def named_page(cn_text: str, us_text: str = "The sampled US coverage points at the "
               "Trump administration.", **side_overrides) -> ReaderPage:
    """The clean page with both explanation paragraphs rewritten."""
    data = page().model_dump(mode="json")
    sides = data["angles"][0]["sides"]
    sides[0]["answer"]["text"]["values"]["en"] = cn_text
    sides[0]["answer"]["evidence"] = side_overrides.get(
        "cn_evidence", ["CN_00000001:P01:S01"]
    )
    sides[0]["quotes"] = [{"sentence_id": s} for s in side_overrides.get(
        "cn_quotes", ["CN_00000001:P01:S02"]
    )]
    sides[1]["answer"]["text"]["values"]["en"] = us_text
    sides[1]["answer"]["evidence"] = side_overrides.get(
        "us_evidence", ["US_00000001:P01:S01"]
    )
    sides[1]["quotes"] = [{"sentence_id": s} for s in side_overrides.get(
        "us_quotes", ["US_00000001:P01:S02"]
    )]
    data["intro"][0]["evidence"] = ["CN_00000001:P01:S01", "US_00000001:P01:S01"]
    data["hook"] = None
    return ReaderPage.model_validate(data)


def named_report(page_obj, *, strict_names=False):
    return check_page(
        page_obj,
        named_articles(),
        [finding()],
        registry=named_registry(),
        strict_names=strict_names,
    )


def named_warnings(report) -> list[str]:
    return [w for w in report.warnings if "page_checks_anchors" in w]


def test_an_outlet_named_without_an_anchor_from_it_is_a_warning():
    """The one shape of this defect that resolves across languages.

    The masthead becomes a ``source_id`` through the registry and the anchor becomes a
    ``source_id`` through the corpus, so a Chinese-language anchor and an English pivot
    paragraph are still comparable.  Measured: the only two
    real instances in the repo were caught exactly this way.
    """
    report = named_report(
        named_page("The Paper opens on the archaeology of the site.")
    )
    assert report.ok, "this is a warning, never a refusal"
    assert named_warnings(report) == [
        "angle 1 (cn): names 'The Paper' but this side's anchors carry no sentence from "
        "thepaper_cn — anchor the outlet you name, or drop the name (page_checks_anchors)"
    ]


def test_an_outlet_named_with_an_anchor_from_it_passes():
    report = named_report(
        named_page(
            "The Paper opens on the archaeology of the site.",
            cn_evidence=["CN_00000001:P01:S01", "CN_00000002:P01:S01"],
        )
    )
    assert named_warnings(report) == []


def test_a_quote_from_the_named_outlet_counts_as_its_anchor():
    """``style.md`` says "that side's evidence"; the reader also clicks the quotes."""
    report = named_report(
        named_page(
            "The Paper opens on the archaeology of the site.",
            cn_quotes=["CN_00000002:P01:S02"],
        )
    )
    assert named_warnings(report) == []


def test_an_anchor_on_the_other_side_does_not_anchor_this_side():
    """The whole point is *which* side anchors it, so the other side's evidence is not it."""
    report = named_report(
        named_page(
            "The Paper opens on the archaeology of the site.",
            us_evidence=["CN_00000002:P01:S01", "US_00000001:P01:S01"],
        )
    )
    # The us side's anchors are in the same angle, so the cross-side widening applies only
    # to an outlet belonging to the *other* group; thepaper_cn is a cn outlet named on the
    # cn side, and that side must carry it itself.
    assert len(named_warnings(report)) == 1
    assert "thepaper_cn" in named_warnings(report)[0]


def test_a_masthead_the_registry_spells_differently_still_resolves():
    """"Cover News" in the registry, "The Cover" on the page, ``thecover.cn`` as the host."""
    report = named_report(named_page("The Cover opens on the global record."))
    assert named_warnings(report) == [], (
        "the outlet is anchored (CN_00000001 is thecover_cn); the check must recognise the "
        "spelling the writer used"
    )


def test_a_short_masthead_only_the_domain_knows_still_resolves():
    """``deadline_us`` is registered as "Sfen — Revue Generale Nucleaire"; pages write "Sfen".

    Without the host-label alias the short form falls through to the proper-name check,
    which cannot know the outlet is anchored — measured as a false warning on a correct
    page.
    """
    report = named_report(
        named_page(
            "The sampled Chinese coverage points at the US government.",
            us_text="Sfen adds the half-year loss the withdrawal has already cost.",
            us_evidence=["US_00000002:P01:S01"],
            us_quotes=["US_00000002:P01:S02"],
        )
    )
    assert named_warnings(report) == []


def test_an_all_lower_case_run_of_prose_is_not_a_masthead():
    """Case is the guard that keeps "the cover story" out of the outlet warnings."""
    report = named_report(
        named_page("The sampled coverage returns to the cover story of the week.")
    )
    assert named_warnings(report) == []


def test_a_decimal_figure_with_no_anchor_is_a_warning():
    """The gap ``check_page``'s own digit rules leave open.

    An integer in a ``corpus_aggregate`` sentence is already refused when it does not
    recompute from the finding; a token carrying a decimal point is skipped by that rule
    outright, so "12.1%" can sit in an explanation paragraph with nothing behind it.
    """
    report = named_report(
        named_page("The sampled Chinese coverage puts the share at 12.1% of the haul.")
    )
    assert report.ok
    assert named_warnings(report) == [
        "angle 1 (cn): states the figure '12.1', which appears in none of this side's "
        "anchored sentences and recomputes from no finding (page_checks_anchors)"
    ]


def test_the_same_decimal_anchored_on_this_side_passes():
    report = named_report(
        named_page(
            "The sampled Chinese coverage points at the US government.",
            us_text="The sampled US coverage puts the share at 12.1% of the haul.",
            us_evidence=["US_00000002:P01:S02"],
            us_quotes=["US_00000002:P01:S01"],
        )
    )
    assert named_warnings(report) == []


def test_thousands_separators_are_notation_not_quantity():
    """"1,200" on the page and "1,200" in the anchor are one figure however either is
    punctuated; the fold runs on both sides of the comparison."""
    report = named_report(
        named_page(
            "The sampled Chinese coverage points at the US government.",
            us_text="US reports count 1200.5 new places against the cap.",
            us_evidence=["US_00000002:P01:S01"],
        )
    )
    # 1,200 in the anchored sentence, 1200.5 in the paragraph: the integer part folds to
    # the same digits, the decimal does not exist in the anchor, and the figure is flagged.
    assert len(named_warnings(report)) == 1
    assert "1200.5" in named_warnings(report)[0]


def test_an_acronym_missing_from_a_same_script_anchor_is_a_warning():
    """``DEHOGA`` on the German side of a real topic's page, the one real name catch."""
    report = named_report(
        named_page(
            "The sampled Chinese coverage points at the US government.",
            us_text="The objection was lodged by DEHOGA and the ministry.",
            us_evidence=["US_00000002:P01:S01"],
            us_quotes=["US_00000002:P01:S02"],
        )
    )
    assert named_warnings(report) == [
        "angle 1 (us): names 'DEHOGA', which appears in none of this side's anchored "
        "sentences (page_checks_anchors)"
    ]


def test_an_acronym_the_anchor_spells_in_another_case_is_not_a_defect():
    """A German report writes the association "Dehoga"; the page writes "DEHOGA"."""
    report = named_report(
        named_page(
            "The sampled Chinese coverage points at the US government.",
            us_text="The objection was lodged by DEHOGA and the ministry.",
            us_evidence=["US_00000001:P01:S02"],
        )
    )
    assert named_warnings(report) == []


def test_a_name_is_not_checked_against_an_anchor_in_another_script():
    """An English name reaches a Chinese anchor transliterated, never verbatim.

    Measured: before this gate every proper-name warning on a CJK or Cyrillic side
    of a real page was false — ``IMF`` against a Mongolian anchor that says Олон Улсын
    Валютын Сан, ``Mycenaeans`` against 迈锡尼 — and every true one was on a Latin-script
    side.  The outlet half above is what covers those sides instead.
    """
    report = named_report(
        named_page("The sampled Chinese coverage credits DEHOGA and the IMF."),
        strict_names=True,
    )
    assert named_warnings(report) == []


def test_ordinary_proper_names_need_strict_names():
    text = ("The sampled US coverage points at the Trump administration and the "
            "Prussian Cultural Heritage Foundation.")
    quiet = named_report(named_page("The sampled Chinese coverage points at the US "
                                    "government.", us_text=text))
    assert named_warnings(quiet) == [], "off by default: too noisy across languages"
    loud = named_report(
        named_page("The sampled Chinese coverage points at the US government.",
                   us_text=text),
        strict_names=True,
    )
    assert any("Prussian Cultural Heritage Foundation" in w for w in named_warnings(loud))


def test_a_paragraph_with_no_anchors_at_all_is_counted_not_enumerated():
    """Every named thing would fire, saying one thing many times and burying the rest."""
    data = named_page("The sampled Chinese coverage points at the US "
                      "government.").model_dump(mode="json")
    data["intro"] = [
        {
            "text": {"values": {"en": "The Paper reports 12.1% and credits DEHOGA."}},
            "claim_type": "corpus_aggregate",
            "computed_from": "FND-aabb-river-light-001",
            "evidence": [],
        }
    ]
    report = named_report(ReaderPage.model_validate(data), strict_names=True)
    assert named_warnings(report) == []
    assert "1 paragraph(s) skipped" in report.stats["named-thing warnings"]


def test_the_check_is_off_without_a_registry():
    """The safety switch: ``check_page`` runs this only when a registry is handed to it."""
    report = check_page(
        named_page("The Paper opens on the archaeology of the site."),
        named_articles(),
        [finding()],
    )
    assert named_warnings(report) == []
    assert "named-thing warnings" not in report.stats


def test_the_shared_publish_rerender_path_never_runs_the_named_thing_check():
    """Same contract as the run-directory check, for the same reason.

    ``builder.render_locales`` is the re-render every ``prepare`` / ``review-preview`` /
    ``verify-site`` shares.  A publication shipped before this check existed must not start
    producing new output there, so the call must not pass ``registry``.  Read the source
    rather than trusting a comment: if someone wires it in while editing builder.py, this
    fails immediately.
    """
    import inspect

    from newsab_publish import builder

    source = inspect.getsource(builder.render_locales)
    call = source[source.index("check_page("):]
    call = call[: call.index("\n    )")]
    assert "registry" not in call, (
        "render_locales must not pass registry to check_page: the named-thing warnings "
        "are a write-stage aid and must never reach an already-approved page's re-render"
    )
    assert "strict_names" not in call


def _source_claim_intro(text: str, article_id: str) -> ReaderPage:
    """The clean page with the intro replaced by one anchored source_claim."""
    data = page().model_dump(mode="json")
    data["intro"] = [
        {
            "text": {"values": {"en": text, "zh-CN": text}},
            "claim_type": "source_claim",
            "evidence": [f"{article_id}:P01:S01"],
        }
    ]
    data["hook"] = None
    return ReaderPage.model_validate(data)


def _thousands_articles() -> list[Article]:
    """A French anchor that writes its thousands separator the way French does."""
    return [
        *ARTICLES,
        article(
            "FR_00000001",
            "fr",
            [
                "Les 90 000 tonnes d’uranium que contient le désert de Gobi pourraient "
                "remplacer ces gisements.",
                "Le groupe cherche à diversifier ses sources.",
            ],
            "Uranium mongol",
        ),
    ]


def test_a_thousands_separator_is_notation_not_a_missing_number():
    """A correct page must not be refused over a typographic convention.

    A real topic's page really does anchor "Les 90 000 tonnes…", and an English pivot
    writes that figure "90,000".  Before the fold, the ``source_claim`` digit check
    compared the two as raw strings and raised a hard error on a page whose number is
    exactly where it should be.  Found while measuring the named-but-unanchored check.
    """
    report = check_page(
        _source_claim_intro(
            "The Gobi holds 90,000 tonnes of uranium.", "FR_00000001"
        ),
        _thousands_articles(),
        [finding()],
    )
    assert [e for e in report.errors if "90,000" in e] == [], report.render()


def test_a_number_genuinely_absent_from_the_anchor_is_still_refused():
    """The fold must not turn the check off: only notation is forgiven, never a figure."""
    report = check_page(
        _source_claim_intro(
            "The Gobi holds 91,000 tonnes of uranium.", "FR_00000001"
        ),
        _thousands_articles(),
        [finding()],
    )
    assert any("91,000" in e for e in report.errors), report.render()


def test_the_fold_never_bridges_two_anchored_sentences_into_one_number():
    """Anchors join on a newline, which no separator class contains.

    Otherwise "…12" ending one anchored sentence and "345…" opening the next would fold
    into "12345" and silently pass a number nobody wrote.
    """
    from newsab_editorial.page_checks_anchors import _digit_fold

    assert _digit_fold("ends with 12\n345 opens the next") == "ends with 12\n345 opens the next"
    assert _digit_fold("90 000") == "90000"
    assert _digit_fold("1 234 567") == "1234567"
    assert _digit_fold("3, 4 items") == "3, 4 items"
