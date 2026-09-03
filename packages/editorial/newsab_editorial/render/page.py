"""Assemble the whole reader page.

Reading order, which is also the order below: optional **home link** →
**title and briefing** → **timeline** → the
**storyline** in three tabs → any question-level visual the writer asked for → the
**appendix** of every question → the **concept cloud** → **report search** → the footer.

The theme and back-to-top controls float outside that document reading order.

The concept cloud moved to the bottom this round: it is the one
section on the page that asserts nothing, and it was sitting between the reader and the
story.
"""

from __future__ import annotations

from typing import Iterable, Optional

from newsab_schema.ids import SentenceId
from newsab_schema.locales import direction as locale_direction
from newsab_schema.models.corpus import Article, SourceRegistry, TopicManifest
from newsab_schema.models.findings import QAFinding
from newsab_schema.models.page import ReaderPage
from newsab_schema.models.qa import QuestionSet

from .. import concept_cloud
from ..evidence import (
    AnswerIndex,
    QuestionRow,
    SentenceIndex,
    build_question_rows,
    side_evidence,
)
from .cloud import concept_cloud_viz
from ..provenance import PageComponent, build_page_components, page_contributions
from .common import (
    ICONS,
    badge,
    category_label,
    css_of,
    group_meta,
    gtag,
    json_block,
    ordered_ids,
    pct,
    reader_question,
    section_title,
    short,
    topic_label,
)
from .evidence_view import media_payload
from .islands import (
    EXTERNAL_ISLANDS,
    OVERLAY_ISLAND,
    asset_name,
    canonical_asset_bytes,
    merge_island,
)
from .modals import (
    cluster_modal,
    disclosure_modal,
    media_modal,
    method_modal,
    scope_modal,
    source_modal,
)
from .m2 import PageSiteContext
from .qcard import annotation_modal, appendix_row, question_block
from .search import report_search_payload, report_search_section
from .script import JS
from .stats import DEFAULT_THRESHOLDS, stat_modal
from .storyline import angle_html, footnote_numbering, storyline
from .strings import ORIGIN_LABEL, e, s, t
from .theme import CSS, FONT_LINK
from .timeline import timeline_section


def _theme_button(lang: str) -> str:
    return (
        f'<button type="button" class="theme-fab" id="themebtn" '
        f'aria-label="{e(s("theme_tip", lang))}" title="{e(s("theme_tip", lang))}">'
        '<svg aria-hidden="true"><use href="#i-moon"></use></svg></button>'
    )


def _home_link(home_url: Optional[str], lang: str) -> str:
    """A production-only way back to the site, kept out of preview renders by default."""
    if home_url is None:
        return ""
    return (
        f'<a class="home-link" href="{e(home_url)}">'
        f'<span aria-hidden="true">\u2190</span> {e(s("home_link", lang))}</a>'
    )


def _site_tools(home_url: Optional[str], lang: str, context: PageSiteContext) -> str:
    home = _home_link(home_url, lang)
    links = []
    for locale, url in sorted(context.alternate_urls.items()):
        current = ' aria-current="page"' if locale == context.site_locale else ""
        links.append(
            f'<a href="{e(url)}" hreflang="{e(locale)}" lang="{e(locale)}"{current}>'
            f'{e(locale)}</a>'
        )
    nav = (
        f'<nav aria-label="{e(context.language_label)}">{"".join(links)}</nav>'
        if links
        else ""
    )
    fallback = (
        f'<p class="locale-fallback" role="note">{e(context.fallback_notice)}</p>'
        if context.fallback_notice
        else ""
    )
    return f'<div class="site-tools">{home}{nav}</div>{fallback}'


def _site_head(page: ReaderPage, lang: str, context: PageSiteContext) -> str:
    alternates = "".join(
        f'<link rel="alternate" hreflang="{e(locale)}" href="{e(url)}">'
        for locale, url in sorted(context.alternate_urls.items())
    )
    image_url = context.share_image_url
    description = t(page.intro[0].text, lang) if page.intro else t(page.title, lang)
    image = (
        f'<meta property="og:image" content="{e(image_url)}">'
        '<meta property="og:image:type" content="image/png">'
        '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
        if image_url
        else ""
    )
    return (
        f'<link rel="canonical" href="{e(context.canonical_url)}">{alternates}'
        '<meta property="og:type" content="article">'
        f'<meta property="og:locale" content="{e(context.content_locale)}">'
        f'<meta property="og:title" content="{e(t(page.title, lang))}">'
        f'<meta property="og:description" content="{e(description)}">'
        f'<meta property="og:url" content="{e(context.canonical_url)}">{image}'
    )


def _back_to_top(lang: str) -> str:
    label = e(s("back_to_top", lang))
    return (
        f'<a class="top-fab" id="backtotop" href="#page-top" '
        f'aria-label="{label}" title="{label}"><span aria-hidden="true">\u2191</span></a>'
    )


def _intro(page: ReaderPage, lang: str) -> str:
    # One fact per claim, each separately anchored — past two of them that is a list, and
    # a list is what it should look like.
    if len(page.intro) > 2:
        items = "".join(
            f'<li><span class="x">{e(t(claim.text, lang))}</span></li>'
            for claim in page.intro
        )
        return f'<ul class="intro">{items}</ul>'
    items = "".join(
        f'<li><span class="x">{e(t(claim.text, lang))}</span></li>'
        for claim in page.intro
    )
    return f'<ul class="intro plain">{items}</ul>'


def _distribution_viz(page, caption: str, stats: dict, groups: dict, lang: str) -> str:
    rows = []
    by_group = stats.get("groups", {})
    for group_id in ordered_ids(groups):
        gstats = by_group.get(group_id)
        if not gstats:
            continue
        css = css_of(group_id, groups)
        addressed = gstats.get("clusters_addressed") or 0
        for category, count in sorted(
            (gstats.get("category_counts") or {}).items(),
            key=lambda kv: (-kv[1], kv[0]),
        ):
            width = pct(count, addressed)
            rows.append(
                f'<div class="axis3"><span class="bf-left">'
                f'<span class="bn">{e(short(group_id, groups))}</span></span>'
                f'<span class="cat">{e(category_label(page, category, lang))}</span>'
                f'<span class="bf-right"><span class="bar {css}" '
                f'style="width:{width:.0f}%"></span>'
                f'<span class="bn">{count}</span></span></div>'
            )
    return (
        f'<section class="panel"><div class="panel-head"><h3>{e(caption)}</h3></div>'
        f"{''.join(rows)}</section>"
    )


def _rates_viz(caption: str, question_stats: dict, groups: dict) -> str:
    rows = []
    for question_id, stats in sorted(question_stats.items()):
        by_group = stats.get("groups", {})
        for group_id in ordered_ids(groups):
            gstats = by_group.get(group_id)
            if not gstats:
                continue
            total = gstats.get("clusters_total") or 0
            addressed = gstats.get("clusters_addressed") or 0
            rows.append(
                f'<div class="axis3"><span class="bf-left">'
                f'<span class="bn">{e(question_id[-7:])} · '
                f'{e(short(group_id, groups))}</span></span><span class="cat"></span>'
                f'<span class="bf-right"><span class="bar {css_of(group_id, groups)}" '
                f'style="width:{pct(addressed, total):.0f}%"></span>'
                f'<span class="bn">{addressed}/{total}</span></span></div>'
            )
    return (
        f'<section class="panel"><div class="panel-head"><h3>{e(caption)}</h3></div>'
        f"{''.join(rows)}</section>"
    )


def _article_payload(
    articles: Iterable[Article],
    index: SentenceIndex,
    topics_by_article: dict,
) -> dict:
    """What a timeline dot — or a cluster row — opens: the record card, minus the sentence.

    Built for every article in the pinned run, not only the ones the timeline drew: the
    cluster panel resolves its members through this, and a cluster can contain an article
    no chart on the page happens to plot.  Language-neutral: the outlet display
    name and the localized topic phrases come from the per-language overlay.
    """
    payload: dict[str, dict] = {}
    for article in articles:
        index.used_sources.add(article.source_id)
        payload[article.article_id] = {
            "title": article.title,
            "url": article.url,
            "source_id": article.source_id,
            "date": article.publish_date.isoformat(),
            "fetched": article.fetch_timestamp.date().isoformat(),
            "origin": article.origin.type.value,
            "wire_source": article.origin.wire_source,
            "cluster": article.reporting_cluster_id,
            "cluster_articles": index.cluster_size(article.reporting_cluster_id),
            "topics": [
                {
                    "source_phrase": entry.get("source_phrase") or "",
                    "pivot_en": entry.get("pivot_en") or "",
                }
                for entry in (topics_by_article.get(article.article_id) or [])
            ],
        }
    return payload


def _language_overlay(
    page: ReaderPage,
    index: SentenceIndex,
    groups: dict[str, dict],
    rows: list[QuestionRow],
    article_base: dict,
    translations: dict,
    lang: str,
) -> dict:
    """The few-KB per-language lookup maps that re-localize the neutral islands.

    Every map is keyed by a stable id the neutral data already carries (source id, pivot
    phrase, question id, category key, group id, origin code, sentence id), so the same
    hydration walk works in Python (inline render) and in the page script (external
    render).
    """
    pivots: set[str] = set()
    for card in article_base.values():
        for topic in card.get("topics") or []:
            if topic.get("pivot_en"):
                pivots.add(topic["pivot_en"])
    categories: set[str] = set()
    for row in rows:
        for group in row.groups:
            for cluster in group.clusters:
                if cluster.addressed and cluster.category:
                    categories.add(cluster.category)
    return {
        "sources": {
            source_id: index.source_name(source_id)
            for source_id in sorted(index.used_sources)
        },
        "topics": {pivot: topic_label(page, pivot, lang) for pivot in sorted(pivots)},
        "translations": translations,
        "origins": {
            code: entry.get(lang, entry["en"]) for code, entry in ORIGIN_LABEL.items()
        },
        "groups": {
            group_id: {
                "short": meta["short"],
                "label": meta["label"],
                "definition": meta["definition"],
            }
            for group_id, meta in groups.items()
        },
        "questions": {
            row.question_id: reader_question(page, row.question_id, row.text, lang)
            for row in rows
        },
        "categories": {
            category: category_label(page, category, lang)
            for category in sorted(categories)
        },
    }


def _cluster_payload(articles: Iterable[Article]) -> dict:
    out: dict[str, dict] = {}
    for article in articles:
        entry = out.setdefault(
            article.reporting_cluster_id,
            {"group": article.article_id.split("_", 1)[0].lower(), "articles": []},
        )
        entry["articles"].append(article.article_id)
    for entry in out.values():
        entry["articles"].sort()
    return out


def render_page(
    page: ReaderPage,
    articles: Iterable[Article],
    manifest: TopicManifest,
    question_stats: Optional[dict] = None,
    *,
    lang: str = "en",
    findings: Optional[list[QAFinding]] = None,
    answers: Optional[AnswerIndex] = None,
    question_set: Optional[QuestionSet] = None,
    registry: Optional[SourceRegistry] = None,
    thresholds: Optional[dict] = None,
    appendix: bool = True,
    return_shipped: bool = False,
    topics_by_article: Optional[dict] = None,
    cloud_source: str = "categories",
    page_components: Optional[Iterable[PageComponent]] = None,
    home_url: Optional[str] = None,
    site_context: Optional[PageSiteContext] = None,
    data_assets_base: Optional[str] = None,
    assets_out: Optional[dict] = None,
):
    # Article order is not editorial meaning.  Normalize it at the renderer boundary so
    # filesystem or store iteration cannot perturb payload and search-document bytes.
    articles = sorted(articles, key=lambda article: article.article_id)
    topics_by_article = topics_by_article or {}
    index = SentenceIndex(articles, registry, lang=lang)
    groups = group_meta(manifest, lang, lexicon=page.lexicon)
    by_finding = {f.finding_id: f for f in (findings or [])}
    bar = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    collected = (
        max(a.fetch_timestamp for a in articles).date().isoformat()
        if articles
        else None
    )
    page_components = list(
        page_components
        if page_components is not None
        else build_page_components(page, manifest, ())
    )

    rows: list[QuestionRow] = []
    if question_set is not None and answers is not None and question_stats:
        rows = build_question_rows(
            question_set, question_stats, findings or [], answers, index, page.angles
        )
    rows_by_question = {row.question_id: row for row in rows}
    position_of = {row.question_id: i for i, row in enumerate(rows, start=1)}

    # The storyline's own quotes claim their articles' display budget before the
    # appendix does.  They do not bypass it: once half an article is present, every
    # further anchor—including a writer pick—is listed by address only (non-negotiable 7).
    if answers is not None:
        for angle in page.angles:
            for side in angle.sides:
                for item in side_evidence(
                    side, angle, by_finding.get(angle.finding_id), answers, index
                ):
                    index.allow(item.sentence_id)

    timeline_html, timeline_data = timeline_section(articles, groups, lang)

    rendered, evidence_modals = [], []
    # A visible footnote marker gets one page-wide number in final tab/DOM order.  The
    # writer's ``[^n]`` syntax remains local to its angle, but repeated references —
    # including two perspective columns pointing at one shared note — never duplicate.
    footnote_numbers = footnote_numbering(page.angles, lang)
    for angle in page.angles:
        block = (
            question_block(
                page,
                rows_by_question[angle.question_id],
                groups,
                bar,
                lang,
                position=position_of[angle.question_id],
                total=len(rows),
                with_question=True,
                with_featured=False,
            )
            if angle.question_id in rows_by_question
            else ""
        )
        body, modals = angle_html(
            page,
            angle,
            groups,
            by_finding.get(angle.finding_id),
            answers,
            index,
            block,
            bar,
            lang,
            footnote_numbers[angle.rank],
            share_url=(site_context.share_urls.get(angle.question_id) if site_context else None),
            share_landing_url=(
                site_context.share_landing_urls.get(angle.question_id) if site_context else None
            ),
            share_label=(site_context.share_label if site_context else ""),
        )
        rendered.append((angle.kind.value, body))
        evidence_modals.append(modals)
    story = storyline(rendered, bar, lang, accessible_tabs=site_context is not None)

    visuals = ""
    cloud = ""
    for visual in page.visuals:
        caption = t(visual.caption, lang)
        if question_stats is None:
            continue
        if visual.kind == "answer_distribution" and visual.question_id:
            stats = question_stats.get(visual.question_id)
            if stats:
                visuals += _distribution_viz(page, caption, stats, groups, lang)
        elif visual.kind == "addressed_rates":
            visuals += _rates_viz(caption, question_stats, groups)
        elif visual.kind == "concept_cloud":
            clouds = (
                concept_cloud.build_from_topics(topics_by_article, articles)
                if cloud_source == "topics_raised"
                else concept_cloud.build(question_stats)
            )
            cloud += concept_cloud_viz(
                page, caption, clouds, groups, lang, source=cloud_source
            )

    appendix_html = ""
    if rows and appendix:
        blocks = "".join(
            appendix_row(
                page, row, groups, bar, lang, position=position, total=len(rows)
            )
            for position, row in enumerate(rows, start=1)
        )
        appendix_html = (
            f'<section class="appendix"><div class="apx-head">'
            f"{section_title('i-appendix', s('appendix_title', lang), tag='h2')}"
            f'<button class="iconbtn apx-toggle" type="button" data-apx-toggle '
            f'aria-label="{e(s("appendix_expand", lang))}" '
            f'title="{e(s("appendix_expand", lang))}" '
            f'data-expand-label="{e(s("appendix_expand", lang))}" '
            f'data-collapse-label="{e(s("appendix_collapse", lang))}">'
            f'<svg aria-hidden="true"><use href="#i-expand-all"></use></svg></button>'
            f"</div>{blocks}</section>"
        )

    # Every question's annotation table and statistics panel live in modals, rendered
    # after the page body so the storyline claims the display budget first.
    ann_modals = "".join(
        annotation_modal(page, row, groups, index, lang) for row in rows
    )
    stat_modals = "".join(stat_modal(page, row, groups, bar, lang) for row in rows)

    footer = (
        report_search_section(lang)
        # The site name is root-relative to this language's home, so it works identically
        # under the review shell and in production; never the bare production origin.
        + f"<footer><span>{e(s('footer_note', lang))} | "
        f'<a href="/{e(lang)}/">{e(s("footer_site", lang))}</a></span>'
        f'<span class="flinks">'
        f'<button class="tbtn" type="button" data-open="methodmodal">'
        f"{e(s('method_open', lang))}</button>"
        f'<button class="tbtn" type="button" data-open="disclosuremodal">'
        f"{e(s('disclosure_open', lang))}</button></span></footer>"
    )

    sentence_index, translations = _sentence_payload(page, index, lang)
    sentence_base: dict[str, dict] = {}
    for sid, card in sentence_index.items():
        card = dict(card)
        # The neutral base carries the stable ``source_id``; the display name, localized
        # topic phrases and our translation come from the per-language overlay.
        card.pop("source", None)
        index.used_sources.add(card["source_id"])
        article = index.article(sid)
        if article is not None:
            card["fetched"] = article.fetch_timestamp.date().isoformat()
            card["topics"] = [
                {
                    "source_phrase": entry.get("source_phrase") or "",
                    "pivot_en": entry.get("pivot_en") or "",
                }
                for entry in (topics_by_article.get(article.article_id) or [])
            ]
        sentence_base[sid] = card
    article_base = _article_payload(articles, index, topics_by_article)
    search_base = report_search_payload(articles, article_base, rows)
    strings = {
        "position": s("modal_position", lang),
        "para": s("modal_para", lang),
        "cluster": s("modal_cluster", lang),
        "article": s("cluster_article", lang),
        "articles": s("cluster_articles", lang),
        "origin_label": s("modal_origin", lang),
        "origin_original": s("cluster_original", lang),
        "fetched": s("modal_fetched", lang),
        "topics": s("modal_topics", lang),
        "topics_tip": s("modal_topics_tip", lang),
        "topics_switch": s("modal_topics_switch", lang),
        "topics_source": s("modal_topics_source", lang),
        "topics_concept": s("modal_topics_concept", lang),
        "cluster_title": s("cluster_title", lang),
        "cluster_tip": s("cluster_tip", lang),
        "out": s("modal_out", lang),
        "origin": {k: v.get(lang, v["en"]) for k, v in ORIGIN_LABEL.items()},
        "media_tip": s("media_tip", lang),
        "media_country": s("media_country", lang),
        "media_lang": s("media_lang", lang),
        "media_category": s("media_category", lang),
        "media_beat": s("media_beat", lang),
        "media_site": s("media_site", lang),
        "theme_light": _theme_word("light", lang),
        "theme_dark": _theme_word("dark", lang),
        "tr_original": s("tr_original", lang),
        "tr_translated": s("tr_translated", lang),
        "search_count": s("search_count", lang),
        "search_more": s("search_more", lang),
        "search_none": s("search_none", lang),
        "search_phrases": s("search_phrases", lang),
        "search_answers": s("search_answers", lang),
        "search_open": s("search_open", lang),
    }

    base_by_island: dict[str, object] = {
        "sentence-index": sentence_base,
        "article-index": article_base,
        "report-search-index": search_base,
        "cluster-index": _cluster_payload(articles),
    }
    overlay = _language_overlay(
        page, index, groups, rows, article_base, translations, lang
    )
    if data_assets_base is None:
        # Inline render: merge base + overlay server-side into the legacy fully-localized
        # islands, so a standalone document stays self-contained and byte-reproducible.
        data_islands = "".join(
            json_block(island, merge_island(island, base_by_island[island], overlay))
            for island in EXTERNAL_ISLANDS
        )
    else:
        # External render: the page carries one reference per island plus the overlay;
        # the behaviour script fetches and hydrates.  Same content, same hash, same
        # filename — across locales and across page versions.
        prefix = data_assets_base.rstrip("/")
        parts = []
        for island in EXTERNAL_ISLANDS:
            blob = canonical_asset_bytes(base_by_island[island])
            name = asset_name(island, blob)
            if assets_out is not None:
                assets_out[name] = blob
            parts.append(
                f'<script type="application/json" id="{island}" '
                f'data-src="{e(f"{prefix}/{name}")}"></script>'
            )
        parts.append(json_block(OVERLAY_ISLAND, overlay))
        data_islands = "".join(parts)

    head_extra = _site_head(page, lang, site_context) if site_context else ""
    # A production page links the site chrome at a stable URL and carries no stylesheet,
    # font link or behaviour script of its own; a preview is a standalone local file and
    # keeps everything inline.  See ``newsab_publish.chrome`` for why.
    if site_context:
        chrome_head = (
            f'<link rel="stylesheet" href="{e(site_context.stylesheet_url)}">'
            f'<script src="{e(site_context.script_url)}" defer></script>'
        )
        chrome_tail = ""
    else:
        chrome_head = f"{FONT_LINK}<style>{CSS}</style>"
        chrome_tail = f"<script>{JS}</script>"
    site_tools = (
        _site_tools(home_url, lang, site_context)
        if site_context
        else _home_link(home_url, lang)
    )
    root_attrs = (
        f' data-site-locale="{e(site_context.site_locale)}" '
        f'data-content-locale="{e(site_context.content_locale)}" '
        f'data-theme-token="{e(site_context.theme_token)}"'
        if site_context
        else ""
    )
    sharing = (
        '<div class="share-status" id="share-status" role="status" aria-live="polite"></div>'
        f"{json_block('site-strings', {'share_copied': site_context.share_copied, 'share_failed': site_context.share_failed})}"
        if site_context
        else ""
    )
    document = (
        "<!DOCTYPE html>\n"
        f'<html lang="{e(lang)}" dir="{e(locale_direction(lang))}"{root_attrs}>'
        "<head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{e(t(page.title, lang))}</title>{head_extra}{chrome_head}</head><body>"
        f"{ICONS}{_theme_button(lang)}{_back_to_top(lang)}<main id=\"page-top\">"
        f"{site_tools}"
        f'<header class="head"><h1>{e(t(page.title, lang))}</h1>'
        f"{_intro(page, lang)}</header>"
        f"{timeline_html}{story}{visuals}{appendix_html}{cloud}{footer}"
        f"</main>"
        f"{source_modal(lang)}{media_modal(lang)}{cluster_modal(lang)}"
        f"{scope_modal(page, manifest, groups, collected, lang)}"
        f"{method_modal(lang)}"
        f"{disclosure_modal(page_components, page_contributions(manifest), lang)}"
        f"{ann_modals}{stat_modals}{''.join(evidence_modals)}"
        '<div id="floattip" role="status" hidden></div>'
        f"{data_islands}"
        f"{json_block('media-index', media_payload(index, lang))}"
        f"{json_block('timeline-data', timeline_data)}"
        f"{json_block('modal-strings', strings)}{sharing}"
        f"{chrome_tail}</body></html>\n"
    )
    return (
        (document, sorted(index.used), dict(index.withheld))
        if return_shipped
        else document
    )


_THEME_WORDS = {
    "light": {"en": "Light", "zh-CN": "浅色"},
    "dark": {"en": "Dark", "zh-CN": "深色"},
}


def _theme_word(key: str, lang: str) -> str:
    entry = _THEME_WORDS[key]
    return entry.get(lang, entry["en"])


def _sentence_payload(
    page: ReaderPage, index: SentenceIndex, lang: str
) -> tuple[dict, dict]:
    """The detail view behind every rendered ``[source]`` chip, plus our translations.

    Built from what the renderer actually marked as displayed, so the payload never
    carries a sentence the page does not show — one click, one sentence, non-negotiable 7.
    """
    translations: dict[str, str] = {}
    for angle in page.angles:
        for side in angle.sides:
            for quote in side.quotes:
                if quote.translation is None:
                    continue
                localized = quote.translation.get(lang)
                article = index.article(quote.sentence_id)
                if (
                    localized
                    and article
                    and article.lang.split("-")[0] != lang.split("-")[0]
                ):
                    translations[quote.sentence_id] = localized
    payload: dict[str, dict] = {}
    for sid in sorted(index.used):
        card = index.card(sid)
        if card is not None:
            payload[sid] = card.to_json()
    return payload, translations


def sentence_load(articles: Iterable[Article], sentence_ids: Iterable[str]) -> dict:
    """Sentences the page ships per article, against that article's own sentence count.

    Non-negotiable 7 forbids shipping full text; this is how a render says how close it
    came, so the number is on the record instead of assumed harmless.
    """
    by_article = {a.article_id: a for a in articles}
    counts: dict[str, int] = {}
    for sid in sentence_ids:
        article_id = SentenceId.parse(sid).article_id
        counts[article_id] = counts.get(article_id, 0) + 1
    out: dict[str, tuple[int, int]] = {}
    for article_id, shipped in sorted(counts.items()):
        article = by_article.get(article_id)
        if article is None:
            continue
        out[article_id] = (
            shipped,
            sum(len(p.sentences) for p in article.structured_text),
        )
    return out
