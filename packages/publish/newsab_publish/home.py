"""Pure, deterministic production-home rendering from localized catalog rows.

The home page is the only page on the site that is not an approved content document,
so it carries its own stylesheet and behaviour instead of linking the site chrome.  It
deliberately speaks the topic page's design language — the same serif/sans pairing, the
same paper, rules and the same pair of A/B colours — and adds one idea of its own:

*the masthead states the product.*  ``News`` sits above a giant ``A / B`` split by a
hairline seam that runs down the middle of the hero, and every topic card carries a
miniature of the topic page's answer pair: one question, two answers, and the mark of
the relation between them.  A reader learns the whole model before scrolling once.

Nothing here restyles a topic page: this module emits only the home document, and the
topic pages' look continues to come from ``newsab_publish.chrome``.
"""

from __future__ import annotations

import hashlib
import html
import posixpath
from datetime import date
from typing import Iterable, Literal, Mapping, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

from newsab_schema import CatalogAngle, CatalogRecord, CatalogSide
from newsab_schema.common import normalize_lang
from newsab_schema.locales import HALO_LOCALES
from newsab_schema.locales import direction as locale_direction

from .about import ABOUT_CSS, HOME_ABOUT_JS, about_button_html, about_modal_html
from .brand import ASSET_URL as LOGO_URL
from .identity import official_site
from .metadata import SiteMetadata
from .site_strings import language_name, site_strings
from .suggest import (
    SUGGEST_CSS,
    suggest_button_html,
    suggest_modal_html,
    suggestion_entrance_enabled,
    suggestion_js,
)


UrlMode = Literal["root", "relative"]

#: How many cards the explorer reveals before the reader asks for more.  The whole
#: catalogue is always in the markup (search, crawlers and no-JS readers need it); this
#: only decides what is visible first.
PAGE_STEP = 12


def _catalog_rows(
    records: Iterable[CatalogRecord], locale: str, metadata: SiteMetadata
) -> list[CatalogRecord]:
    canonical_locale = normalize_lang(locale)
    if canonical_locale not in metadata.locales:
        raise ValueError(f"locale absent from site metadata: {canonical_locale}")
    rows = [record for record in records if record.locale == canonical_locale]
    publication_ids = [record.publication_id for record in rows]
    if len(publication_ids) != len(set(publication_ids)):
        raise ValueError(f"duplicate catalog publication in {canonical_locale}")

    controlled = {category.category_id for category in metadata.categories}
    for record in rows:
        unknown = sorted(set(record.category_ids) - controlled)
        if unknown:
            raise ValueError(f"{record.topic_id}: catalog uses unknown categories: {unknown}")
        pinned = metadata.topic_categories.get(record.topic_id)
        if pinned is not None and record.category_ids != pinned:
            raise ValueError(
                f"{record.topic_id}: catalog categories differ from versioned site metadata"
            )
    return rows


def _newest_first(records: Iterable[CatalogRecord]) -> list[CatalogRecord]:
    rows = sorted(records, key=lambda record: record.publication_id)
    return sorted(rows, key=lambda record: record.published_at, reverse=True)


def daily_catalog_order(records: Iterable[CatalogRecord], build_date: date) -> list[CatalogRecord]:
    """Return the site-wide daily order shared by every visitor.

    No runtime entropy enters the key.  A publication keeps the same position for the
    entire explicit build date; the publication id makes revisions independent entries.
    """

    day = build_date.isoformat()

    def daily_key(record: CatalogRecord) -> tuple[bytes, str]:
        value = f"{day}\0{record.publication_id}".encode("utf-8")
        return hashlib.sha256(value).digest(), record.publication_id

    return sorted(records, key=daily_key)


def _href(url: str, *, url_mode: UrlMode, home_path: str) -> str:
    if url_mode == "root":
        return url
    if url_mode != "relative":
        raise ValueError(f"unsupported URL mode: {url_mode}")
    if not url.startswith("/") or url.startswith("//"):
        raise ValueError(f"site URL must be root-relative: {url}")
    if not home_path.startswith("/") or not home_path.endswith("/"):
        raise ValueError("home_path must be a root-relative directory ending in slash")

    split = urlsplit(url)
    start = home_path.strip("/") or "."
    target = split.path.lstrip("/")
    relative = posixpath.relpath(target or ".", start=start)
    if split.path.endswith("/") and not relative.endswith("/"):
        relative += "/"
    return urlunsplit(("", "", relative, split.query, split.fragment))


def _scope(record: CatalogRecord) -> str:
    return f"{record.scope_start.isoformat()} – {record.scope_end.isoformat()}"


def _esc(value: str) -> str:
    return html.escape(value)


def _attr(value: str) -> str:
    return html.escape(value, quote=True)


def _search_text(record: CatalogRecord, pivot: CatalogRecord | None = None) -> str:
    """Everything a card says, casefolded once, so search reads the cards themselves.

    The page used to carry a second copy of every row as a JSON island purely so the
    search box had something to read.  The cards are already in the document; this is
    the same text, folded, and it costs one attribute instead of a second catalogue.

    ``pivot`` is the same topic's English row.  English is the master every other locale
    was translated from, so its words are appended to every non-English card: a reader
    on the zh-CN homepage who types ``india`` finds the topic whose card says 印度.
    """
    parts = _card_words(record)
    if pivot is not None and pivot.locale != record.locale:
        parts.extend(_card_words(pivot))
    return " ".join(" ".join(parts).split()).casefold()


def _card_words(record: CatalogRecord) -> list[str]:
    parts = [record.title.text, record.brief.text]
    parts.extend(
        value for side in record.sides for value in (side.short_label.text, side.definition.text)
    )
    for angle in record.angles:
        parts.append(angle.question.text)
        parts.extend(
            answer.text
            for side in record.sides
            if (answer := angle.answers[side.group_id]) is not None
        )
    return parts


def _media_filter_code(code: str) -> str:
    """Fold source-language variants that are one reader-facing filter choice.

    Catalog rows retain the precise BCP-47 tag.  The homepage filter deliberately treats
    Traditional Chinese from Taiwan and Hong Kong as one choice, so both tags become the
    single ``zh-TW`` value only at this presentation boundary.
    """
    return "zh-TW" if code == "zh-HK" else code


# --------------------------------------------------------------------------------------
# the answer pair — the topic page's core visual, at card scale
# --------------------------------------------------------------------------------------

#: The same three glyphs a topic page uses for the relation between two answers, copied
#: rather than imported: this document links no shared sprite, so it must carry its own.
_KIND_SYMBOL = {
    "consensus": "i-consensus",
    "divergence": "i-divergence",
    "attention_gap": "i-silence",
    "blindspot": "i-silence",
    "coverage_gap": "i-silence",
}

_KIND_STRING = {
    "consensus": "kind_consensus",
    "divergence": "kind_divergence",
    "attention_gap": "kind_attention_gap",
    "blindspot": "kind_attention_gap",
    "coverage_gap": "kind_attention_gap",
}


def _kind_label(kind: str, strings: Mapping[str, str]) -> str:
    return strings[_KIND_STRING.get(kind, "kind_attention_gap")]


def _count_title(count: Optional[str], strings: Mapping[str, str]) -> str:
    if not count or "/" not in count:
        return ""
    numerator, denominator = count.split("/", 1)
    return strings["count_tip"].format(n=numerator, d=denominator)


def _answer_side(
    angle: CatalogAngle,
    side: CatalogSide,
    slot: str,
    strings: Mapping[str, str],
) -> str:
    """One side's answer card: side tag and count on the top rule, answer underneath.

    The count sits in the corner rather than under the answer so the answer itself gets
    the whole width and a size a reader can take in at a glance.
    """
    answer = angle.answers.get(side.group_id)
    count = angle.counts.get(side.group_id) if angle.counts else None
    silent = " tside--silent" if answer is None else ""
    text = answer.text if answer is not None else "—"
    count_markup = ""
    if count:
        tip = _count_title(count, strings)
        # The visible badge is two bare numbers, so the sentence behind them is the
        # better accessible name — nothing is lost by replacing "7/11" with it.
        label = f' data-tip="{_attr(tip)}" aria-label="{_attr(tip)}"' if tip else ""
        count_markup = f'<span class="cnt"{label}>{_esc(count)}</span>'
    return (
        f'<span class="tside tside--{slot}{silent}">'
        f'<span class="thead">'
        f'<span class="gtagw" data-tip="{_attr(side.definition.text)}">'
        f'<span class="gtag">{_esc(side.short_label.text)}</span></span>'
        f"{count_markup}</span>"
        f'<span class="vh">{_esc(side.definition.text)}</span>'
        f'<span class="ans">{_esc(text)}</span></span>'
    )


def _answer_pair(
    record: CatalogRecord, angle: CatalogAngle, strings: Mapping[str, str]
) -> str:
    """Two answers with the relation between them — the shape the whole site is about."""
    first, second = record.sides
    kind = str(angle.finding_kind)
    label = _kind_label(kind, strings)
    symbol = _KIND_SYMBOL.get(kind, "i-silence")
    # Which lead is drawn muted is a fact about the cards either side of the relation
    # column, and CSS in the column cannot ask them: the build states it.
    silent = "".join(
        f" trel--{slot}silent"
        for slot, side in (("a", first), ("b", second))
        if angle.answers.get(side.group_id) is None
    )
    return (
        '<span class="tduo">'
        f"{_answer_side(angle, first, 'a', strings)}"
        f'<span class="trel{silent}"><span class="mark" data-tip="{_attr(label)}">'
        f'<svg aria-hidden="true"><use href="#{symbol}"></use></svg>'
        f'</span><span class="vh">{_esc(label)}</span></span>'
        f"{_answer_side(angle, second, 'b', strings)}"
        "</span>"
    )


# --------------------------------------------------------------------------------------
# cards
# --------------------------------------------------------------------------------------


def _category_label(
    record: CatalogRecord, metadata: SiteMetadata, locale: str
) -> str:
    for category in metadata.categories:
        if category.category_id in record.category_ids:
            return category.labels[locale]
    return ""


def _kicker(record: CatalogRecord, category: str, strings: Mapping[str, str]) -> str:
    """Category and the sample window — never the publication date.

    Two dates on one card is one date too many: a reader reads whichever is newer as the
    period the coverage came from.  The window is the fact the comparison actually rests
    on, so it is the one that stays.
    """
    category_markup = f'<span class="cat">{_esc(category)}</span>' if category else ""
    window = _scope(record)
    return (
        f'<p class="tk">{category_markup}'
        f'<span class="win" data-tip="{_attr(strings["scope"])}" '
        f'aria-label="{_attr(strings["scope"])}：{_attr(window)}">{_esc(window)}</span></p>'
    )


def _topic_card(
    record: CatalogRecord,
    *,
    strings: Mapping[str, str] | Sequence[tuple[str, str]],
    metadata: SiteMetadata,
    locale: str,
    url_mode: UrlMode,
    home_path: str,
    latest_index: int = 0,
    daily_index: int = 0,
    lead: bool = False,
    pivot: CatalogRecord | None = None,
) -> str:
    s = dict(strings)
    angle = record.angles[0]
    page_href = _href(record.page_url, url_mode=url_mode, home_path=home_path)
    angle_href = _href(angle.fragment_url, url_mode=url_mode, home_path=home_path)
    category = _category_label(record, metadata, locale)
    rest = record.angles[1:]

    other_questions = ""
    if lead and rest:
        # Every one of them carries the same ``Q:`` the card's own question does: they
        # are the rest of the same question set, not a different kind of link.
        chips = "".join(
            '<a class="qchip" href="{href}" data-tip="{title}">'
            '<span class="qm">{mark}</span><span class="qx">{text}</span></a>'.format(
                href=_attr(_href(item.fragment_url, url_mode=url_mode, home_path=home_path)),
                title=_attr(item.question.text),
                mark=_esc(s["question"]),
                text=_esc(item.question.text),
            )
            for item in rest
        )
        other_questions = f'<p class="qchips">{chips}</p>'

    # What the comparison rests on and how many ways it was asked — the two numbers a
    # reader weighs before opening a topic.
    # The unit belongs to the record, not to the renderer: `report_count` counted raw
    # articles before catalog-0.4.0, and a card that labelled that number "independent
    # reports" would misstate a record nobody had rebuilt yet.
    reports_label = (
        s["card_reports"]
        if record.catalog_version >= "catalog-0.4.0"
        else s["card_reports_articles"]
    )
    foot = (
        f'<p class="tf"><span class="qn">'
        f'<span>{_esc(reports_label.format(n=record.report_count))}</span>'
        f'<span>{_esc(s["card_angles"].format(n=len(record.angles)))}</span></span>'
        f'<span class="read">{_esc(s["read_topic"])} <span aria-hidden="true">→</span></span></p>'
    )

    classes = "tcard tcard--lead" if lead else "tcard"
    body = (
        f'<div class="tbody">{_kicker(record, category, s)}'
        f'<h3 class="tt"><a href="{_attr(page_href)}">{_esc(record.title.text)}</a></h3>'
        f'<p class="tb" data-b>{_esc(record.brief.text)}</p>{foot if lead else ""}</div>'
    )
    qa = (
        f'<a class="tqa" href="{_attr(angle_href)}">'
        f'<span class="tq"><span class="qm">{_esc(s["question"])}</span>'
        f'<span class="qtext">{_esc(angle.question.text)}</span></span>'
        f"{_answer_pair(record, angle, s)}</a>"
    )
    # The lead card is two columns: the story on the left, the comparison on the right.
    # Both halves have to reach the same baseline, so the question pair keeps its own
    # column rather than becoming a third grid item that wraps under the story.
    tail = f'<div class="tlead-side">{qa}{other_questions}</div>' if lead else f"{qa}{foot}"
    media_languages = " ".join(
        sorted({_media_filter_code(code) for code in record.source_languages})
    )
    return (
        f'<article class="{classes}" data-publication-id="{_attr(record.publication_id)}" '
        f'data-cats="{_attr(" ".join(record.category_ids))}" '
        f'data-read="{_attr(" ".join(sorted(record.reader_locales)))}" '
        f'data-media="{_attr(media_languages)}" '
        f'data-i="{latest_index}" data-d="{daily_index}" '
        f'data-search="{_attr(_search_text(record, pivot))}">'
        f"{body}{tail}</article>"
    )


def _card_title_hook(markup: str) -> str:
    """Mark the title text node so the explorer can highlight matches inside it."""
    return markup.replace('<h3 class="tt"><a ', '<h3 class="tt"><a data-t ', 1)


# --------------------------------------------------------------------------------------
# page regions
# --------------------------------------------------------------------------------------


#: The word "news", in the scripts the site samples from, ringed around the ``A / B``
#: lockup.  English is not the label of the ring: it is one of the nine words, and the
#: only thing that makes it different is that its place happens to be the top.  The
#: words and their languages come from ``newsab_schema.locales.HALO_LOCALES`` — the
#: single-source list of the site's nine target languages; only the *layout* (which
#: locale sits where, and how its word hangs on that point) is this page's own.
#:
#: ``(anchor, x, y, locale)``.  ``x``/``y`` are in ``em`` of the lockup's own font size —
#: not rem — measured from the letters' *optical* centre, so the ring keeps its distance
#: from the letters at every size instead of drifting off as the type shrinks.  ``anchor``
#: is how the word hangs on that point: the words beside the letters are hung by their
#: inner edge (``end`` on the left, ``start`` on the right) so the ring has a clean inner
#: line however long the word is; the words above and below, which have the whole width
#: to themselves, hang by their middle.
#:
#: Everything else — the direction a word drifts on hover, the direction its own grey
#: fades in, the order the ring blooms — is derived from where it sits.
_HALO_LAYOUT: tuple[tuple[str, float, float, str], ...] = (
    # the arch over the letters
    ("mid", -0.62, -0.56, "zh-CN"),
    ("mid", 0.00, -0.68, "en"),
    ("mid", 0.62, -0.56, "ru"),
    # the two flanks, bowed a little outward at the waist where the letters are widest
    ("end", -1.00, -0.34, "fr"),
    ("end", -1.06, 0.02, "ko"),
    ("end", -1.02, 0.38, "hi"),
    ("start", 0.98, -0.34, "es"),
    ("start", 1.04, 0.02, "ja"),
    ("start", 1.00, 0.38, "ar"),
)

_HALO_BY_LOCALE = {entry.locale: entry for entry in HALO_LOCALES}

#: One line at .95 leading puts the ink high in its box, so the box's centre is not the
#: letters' optical centre.  The whole ring is hung from the optical one.
_HALO_RISE = -0.056

_HALO_ANCHOR = {"mid": "-50%", "end": "-100%", "start": "0%"}


def _halo() -> str:
    import math

    slots = []
    for anchor, x, y, locale in _HALO_LAYOUT:
        entry = _HALO_BY_LOCALE[locale]
        lang, direction, text = entry.display_lang, entry.direction, entry.halo_word
        # A word beside the letters leaves sideways; one above or below leaves along its
        # own radius.  The same vector aims the grey, so each word fades outward too.
        if anchor == "end":
            dx, dy = -1.0, 0.0
        elif anchor == "start":
            dx, dy = 1.0, 0.0
        else:
            length = math.hypot(x, y) or 1.0
            dx, dy = x / length, y / length
        angle = math.degrees(math.atan2(dx, -dy))
        # The hero is cool on the left and warm on the right; the words take the faintest
        # trace of the letter they stand beside, so the ring belongs to the lockup rather
        # than floating over it.  The word directly above the seam stays neutral.
        tint = "var(--a)" if x < 0 else "var(--b)" if x > 0 else "var(--ink2)"
        style = (
            f"--ax:{_HALO_ANCHOR[anchor]};--x:{x:.4f}em;--y:{y + _HALO_RISE:.4f}em;"
            f"--dx:{dx:.4f};--dy:{dy:.4f};--tint:{tint};"
            f"--g:{angle:.1f}deg;--d:{abs(angle) * 0.6:.0f}ms"
        )
        slots.append(
            f'<span class="wm-slot" style="{_attr(style)}">'
            f'<span class="wm-word" lang="{_attr(lang)}" dir="{direction}">'
            f"{_esc(text)}</span></span>"
        )
    return f'<span class="wm-halo">{"".join(slots)}</span>'


#: One classic saying per halo language — each states the site's point in that
#: language's own idiom, never a translation of another (FOUNDER-EDITABLE DRAFT for the
#: seven beyond en/zh; those two always come from ``site_strings`` at render time).
#: Order mirrors ``newsab_schema.locales.HALO_LOCALES``; ``(lang, dir, text)``.
_TAGLINES: tuple[tuple[str, str, str], ...] = (
    ("zh-Hans", "ltr", "横看成岭侧成峰"),
    ("en", "ltr", "One Story, Two Tales"),
    ("ru", "ltr", "У каждого своя правда"),
    ("fr", "ltr", "Chacun voit midi à sa porte"),
    # Replaced an earlier draft ("장님 코끼리 만지기", the "blind men and an elephant"
    # idiom) after independent translator + judge review agreed it carries a
    # dated/avoided disability-as-metaphor word (장님) and, more importantly, means the
    # opposite of the site's point (several *impaired* observers each getting it wrong,
    # versus two *complete, legitimate* tellings of one event). This proverb instead
    # says the same content lands differently depending on how it's told — exactly this
    # site's premise — with neither issue.
    ("ko", "ltr", "아 다르고 어 다르다"),
    # hi's judge flagged the same idiom family (blind men and an elephant) as an
    # advisory-only meaning mismatch — not the disability-word issue ko had, since
    # "अंधों" here reads as an allusion to the classical parable, not a blunt
    # descriptor — but the parable's own moral (impaired observers mis-seeing one
    # truth) still sits at an angle to the site's actual point (two complete,
    # legitimate tellings). Kept as drafted; revisit only if the user wants to revise
    # it later.
    ("hi", "ltr", "अंधों का हाथी"),
    ("es", "ltr", "Todo es según el color del cristal con que se mira"),
    ("ja", "ltr", "真相は藪の中"),
    ("ar", "rtl", "عين الرضا عن كل عيب كليلة"),
)


def _tagline_band(strings: Mapping[str, str], locale: str) -> str:
    """All nine sayings stacked in one grid cell; the reader's own starts visible.

    The server marks the current locale's entry ``on`` so the page opens on it (and it
    is the only one a no-JS reader ever sees); the script then rotates through the rest
    in a shuffled order.  The en and zh entries read from ``site_strings`` so editing a
    tagline there cannot leave this band behind.
    """
    prefix = locale.split("-")[0]
    items = []
    for lang, direction, text in _TAGLINES:
        current = lang.split("-")[0] == prefix
        if current:
            text = strings["tagline"]
        state = ' class="tagline-item on"' if current else (
            ' class="tagline-item" aria-hidden="true"'
        )
        items.append(
            f'<span{state} lang="{_attr(lang)}" dir="{direction}">{_esc(text)}</span>'
        )
    return f'<p class="tagline" data-taglines>{"".join(items)}</p>'


def _masthead(strings: Mapping[str, str], locale: str) -> str:
    # The lockup, the nine-script halo and the rotating sayings are official brand art:
    # a neutral public-toolkit build opens on its own name alone, keeping the h1 and the
    # #page-top anchor without inheriting the identity around them.
    if not official_site():
        return (
            '<header class="masthead masthead--plain" id="page-top">'
            '<div class="wrap mast-in">'
            f'<h1 class="plainmark">{_esc(strings["site_name"])}</h1>'
            "</div></header>"
        )
    return (
        '<header class="masthead" id="page-top"><div class="wrap mast-in">'
        f'<h1 class="wordmark"><span class="vh">{_esc(strings["site_name"])}</span>'
        '<span class="wm-ab" aria-hidden="true"><span class="wm-a">A</span>'
        '<span class="wm-slash">/</span><span class="wm-b">B</span>'
        f"{_halo()}</span>"
        '<span class="wm-rule" aria-hidden="true"></span></h1>'
        f"{_tagline_band(strings, locale)}"
        "</div></header>"
    )


def _method_band(strings: Mapping[str, str]) -> str:
    steps = []
    for index, key in enumerate(("how_1", "how_2", "how_3"), start=1):
        steps.append(
            f'<li><span class="n">{index:02d}</span>'
            f'<span class="h">{_esc(strings[key])}</span>'
            f'<span class="x">{_esc(strings[f"{key}_text"])}</span></li>'
        )
    return (
        '<aside class="band"><div class="wrap">'
        f'<ol class="how">{"".join(steps)}</ol>'
        "</div></aside>"
    )


def _site_tools(
    metadata: SiteMetadata,
    locale: str,
    strings: Mapping[str, str],
    *,
    url_mode: UrlMode,
    home_path: str,
) -> str:
    links = []
    # Locale-code alphabetical order, matching the topic page's own switcher
    # (``page.py``'s ``_site_tools`` sorts ``alternate_urls`` the same way) — the two
    # menus are the same control in two page kinds, so they list languages the same
    # way.
    for site_locale in sorted(metadata.locales):
        locale_url = _href(f"/{site_locale}/", url_mode=url_mode, home_path=home_path)
        native = dict(site_strings(site_locale))["locale_native"]
        current = ' aria-current="page"' if site_locale == locale else ""
        links.append(
            f'<a hreflang="{_attr(site_locale)}" lang="{_attr(site_locale)}" '
            f'href="{_attr(locale_url)}"{current}>{_esc(native)}</a>'
        )
    # The homepage-only "+" sits immediately before "?" in reading order (physically
    # left under `dir="ltr"`, right under rtl); language/theme take the row's end.
    left = (
        f'{suggest_button_html(locale)}{about_button_html(locale)}'
        if suggestion_entrance_enabled()
        else about_button_html(locale)
    )
    return (
        '<div class="site-tools"><div class="toolgroup toolgroup--left">'
        f'{left}</div><div class="toolgroup">'
        '<div class="langmenu"><button class="toolbtn" id="langbtn" type="button" '
        'aria-haspopup="true" aria-expanded="false" aria-controls="site-language-menu" '
        f'aria-label="{_attr(strings["language"])}" title="{_attr(strings["language"])}">'
        '<svg aria-hidden="true"><use href="#i-globe"></use></svg></button>'
        f'<nav id="site-language-menu" aria-label="{_attr(strings["language"])}" hidden>'
        f'{"".join(links)}</nav></div>'
        '<button class="toolbtn" id="themebtn" type="button" '
        f'aria-label="{_attr(strings["theme"])}" title="{_attr(strings["theme"])}">'
        '<svg aria-hidden="true"><use href="#i-moon"></use></svg></button>'
        "</div></div>"
    )


def _language_filter(
    *,
    key: str,
    label: str,
    options: Sequence[tuple[str, str]],
    selected: frozenset[str],
    empty_label: str,
    any_label: str | None,
) -> str:
    """One multi-select language filter: a button that states its own current answer.

    ``any_label`` is what makes the two filters different kinds of question.  The media
    filter is a restriction — "show only topics one of whose samples reports in this
    language" — so it needs a way to say *no restriction*, and starts there.  The reading
    filter is a preference over languages the topic is published in, so an empty
    selection simply means all of them.
    """
    items = []
    if any_label is not None:
        pressed = "true" if not selected else "false"
        items.append(
            f'<button class="lfany" type="button" data-lf-any aria-pressed="{pressed}">'
            f"{_esc(any_label)}</button>"
        )
    for code, name in options:
        checked = " checked" if code in selected else ""
        items.append(
            f'<label class="lfopt"><input type="checkbox" value="{_attr(code)}"{checked}>'
            f"<span>{_esc(name)}</span></label>"
        )
    summary = (
        "、".join(name for code, name in options if code in selected)
        if selected
        else (any_label if any_label is not None else empty_label)
    )
    return (
        f'<div class="lf" data-lf="{_attr(key)}" '
        f'data-lf-empty="{_attr(any_label if any_label is not None else empty_label)}">'
        f'<button class="lfbtn" type="button" id="lf-{_attr(key)}-btn" aria-expanded="false" '
        f'aria-controls="lf-{_attr(key)}-menu">'
        f'<span class="lfl">{_esc(label)}</span>'
        f'<span class="lfv" data-lf-summary>{_esc(summary)}</span>'
        '<svg class="lfc" aria-hidden="true"><use href="#i-chevron"></use></svg></button>'
        f'<div class="lfmenu" id="lf-{_attr(key)}-menu" role="group" '
        f'aria-labelledby="lf-{_attr(key)}-btn" hidden>{"".join(items)}</div></div>'
    )


def _explorer(
    rows: Sequence[CatalogRecord],
    metadata: SiteMetadata,
    locale: str,
    strings: Mapping[str, str],
    *,
    url_mode: UrlMode,
    home_path: str,
    build_date: date,
    daily_positions: Mapping[str, int],
    pivot_records: Mapping[str, CatalogRecord],
) -> str:
    # The category filter is the same kind of control as the media filter: a restriction
    # that starts at "no restriction", offering only categories some topic actually has
    # (one dropdown beside the language ones, not a row of chips).
    present = {category_id for row in rows for category_id in row.category_ids}
    category_options = [
        (category.category_id, category.labels[locale])
        for category in metadata.categories
        if category.category_id in present
    ]
    category_filter = _language_filter(
        key="cat",
        label=strings["filter_category"],
        options=category_options,
        selected=frozenset(),
        empty_label=strings["filter_all"],
        any_label=strings["filter_media_any"],
    )

    cards = "".join(
        _card_title_hook(
            _topic_card(
                row,
                strings=strings,
                metadata=metadata,
                locale=locale,
                url_mode=url_mode,
                home_path=home_path,
                latest_index=index,
                daily_index=daily_positions[row.publication_id],
                pivot=pivot_records.get(row.publication_id),
            )
        )
        for index, row in enumerate(rows)
    )
    empty_state = (
        f'<p class="empty" data-empty hidden>{_esc(strings["search_empty"])}</p>'
        if rows
        else f'<p class="empty">{_esc(strings["catalog_empty"])}</p>'
    )

    # Reading languages come from the site's own locale list, named in themselves — this
    # is the same choice the globe in the corner offers, asked of the topics instead of
    # the chrome.  Media languages come from the catalogue, named in the reader's own
    # language, because the reader is picking them out of a list, not reading them.
    reading_options = [
        (site_locale, dict(site_strings(site_locale))["locale_native"])
        for site_locale in metadata.locales
    ]
    reading_filter = _language_filter(
        key="read",
        label=strings["filter_reading"],
        options=reading_options,
        selected=frozenset({locale}),
        empty_label=strings["filter_all"],
        any_label=None,
    )
    media_codes = sorted(
        {_media_filter_code(code) for row in rows for code in row.source_languages}
    )
    media_options = sorted(
        ((code, language_name(code, locale)) for code in media_codes),
        key=lambda item: (item[1], item[0]),
    )
    media_filter = _language_filter(
        key="media",
        label=strings["filter_media"],
        options=media_options,
        selected=frozenset(),
        empty_label=strings["filter_all"],
        any_label=strings["filter_media_any"],
    )
    return (
        '<section class="section" id="browse">'
        f'<div class="shead"><h2>{_esc(strings["browse"])}</h2>'
        f'<p class="n" data-search-count aria-live="polite"></p></div>'
        '<div class="exp-bar">'
        '<div class="exp-search" id="search">'
        '<span class="ic" aria-hidden="true"><svg><use href="#i-search"></use></svg></span>'
        '<input type="search" data-site-search autocomplete="off" spellcheck="false" '
        f'placeholder="{_attr(strings["search_placeholder"])}" '
        f'aria-label="{_attr(strings["search"])}">'
        '<kbd aria-hidden="true">/</kbd>'
        f'<button class="clear" type="button" data-clear hidden '
        f'aria-label="{_attr(strings["search_clear"])}" '
        f'title="{_attr(strings["search_clear"])}">'
        '<svg aria-hidden="true"><use href="#i-close"></use></svg></button></div>'
        '<div class="exp-filters">'
        f'<div class="exp-langs">{category_filter}{reading_filter}{media_filter}</div>'
        f'<div class="seg" id="daily" data-build-date="{build_date.isoformat()}" role="group" '
        f'aria-label="{_attr(strings["order"])}">'
        f'<button type="button" data-order="latest" aria-pressed="true">'
        f'{_esc(strings["latest"])}</button>'
        f'<button type="button" data-order="daily" aria-pressed="false">'
        f'{_esc(strings["daily_random"])}</button>'
        "</div></div></div>"
        f'<div class="grid" data-grid>{cards}</div>{empty_state}'
        f'<p class="more-row"><button class="more" type="button" data-more hidden>'
        f'{_esc(strings["show_more"])}</button></p>'
        "</section>"
    )


#: The GitHub mark (Simple Icons, CC0), sized by the footer's own font so it sits on the
#: byline like one more glyph.
_ICON_GITHUB = (
    '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M12 '
    ".297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 "
    "0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 "
    "17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 "
    "1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-"
    "2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 "
    "3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 "
    "3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 "
    "0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 "
    '12.297c0-6.627-5.373-12-12-12"/></svg>'
)


def _footer(strings: Mapping[str, str], *, build_date: date) -> str:
    """One centred byline: ``by rwen @ <date> | <GitHub mark>``, nothing else.

    The method blurb came out; the stamp holds the corner until the real site facts —
    the detailed methodology page above all — are written.  The producer version that
    used to follow the bar became the GitHub mark: it links to the public toolkit
    repository — the same one the suggest modal offers — and the version moves into
    a data attribute, still on
    the page for anyone reading the source but no longer part of the reader's line.  The
    language chooser is still not repeated here: the globe in the corner is the site's one
    place to change language.
    """
    from .builder import PACKAGE_VERSION
    from .suggest import TOOLKIT_REPO_URL

    return (
        '<footer><div class="wrap foot">'
        f'<p class="fstamp" data-producer="{_attr(PACKAGE_VERSION)}">by rwen @ '
        f'<time datetime="{build_date.isoformat()}">{build_date.isoformat()}</time>'
        f' <span class="fbar" aria-hidden="true">|</span> <a class="fgit" '
        f'href="{_attr(TOOLKIT_REPO_URL)}" target="_blank" rel="noopener noreferrer" '
        f'aria-label="GitHub" title="GitHub">{_ICON_GITHUB}</a></p>'
        "</div></footer>"
    )


# --------------------------------------------------------------------------------------
# chrome of this one page: icons, stylesheet, behaviour
# --------------------------------------------------------------------------------------

#: The typefaces the topic pages use.  The full local stack lives in the CSS below, so a
#: reader offline gets a plain page, never a broken one.
_FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    "family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700"
    "&family=Noto+Serif+SC:wght@400;500;600"
    "&family=Noto+Sans+SC:wght@400;500;600"
    "&family=IBM+Plex+Sans:wght@400;500;600"
    "&family=IBM+Plex+Mono:wght@400;500"
    # Body-copy reading faces for the halo locales beyond Latin/Cyrillic/SC —
    # same families the topic pages load (render/theme.py's FONT_LINK), so a reader who
    # visits both the home page and an article never re-downloads a different face for
    # the same script.
    "&family=Noto+Serif+KR:wght@400;500;600"
    "&family=Noto+Sans+KR:wght@400;500;600"
    "&family=Noto+Serif+JP:wght@400;500;600"
    "&family=Noto+Sans+JP:wght@400;500;600"
    "&family=Noto+Serif+Devanagari:wght@400;500;600"
    "&family=Noto+Sans+Devanagari:wght@400;500;600"
    "&family=Noto+Naskh+Arabic:wght@400;500;600"
    "&family=Noto+Sans+Arabic:wght@400;500;600"
    # The masthead halo writes "news" in scripts a Latin/CJK stack cannot draw; the
    # Noto Sans KR/Devanagari/Arabic families above already carry weight 600 for it (a
    # Google Fonts family may only appear once per request — a second weight list would
    # be a malformed request, not a second face).
    '&display=swap" rel="stylesheet">'
)

_ICONS = (
    '<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">'
    '<symbol id="i-sun" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
    'stroke-width="1.5" stroke-linecap="round">'
    '<circle cx="10" cy="10" r="3.6"/>'
    '<path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.3 4.3l1.4 1.4M14.3 14.3l1.4 1.4'
    'M15.7 4.3l-1.4 1.4M5.7 14.3l-1.4 1.4"/></symbol>'
    '<symbol id="i-moon" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M16.2 12.4A6.8 6.8 0 0 1 7.6 3.8a6.8 6.8 0 1 0 8.6 8.6Z"/></symbol>'
    '<symbol id="i-globe" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="10" cy="10" r="7.1"/><path d="M2.9 10h14.2"/>'
    '<path d="M10 2.9c1.9 2.1 2.9 4.5 2.9 7.1s-1 5-2.9 7.1c-1.9-2.1-2.9-4.5-2.9-7.1S8.1 5 10 2.9Z"/>'
    "</symbol>"
    '<symbol id="i-search" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round">'
    '<circle cx="8.8" cy="8.8" r="5.3"/><path d="M12.7 12.7 17 17"/></symbol>'
    '<symbol id="i-close" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round"><path d="M5.5 5.5l9 9M14.5 5.5l-9 9"/></symbol>'
    '<symbol id="i-chevron" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M5.5 8l4.5 4.5L14.5 8"/></symbol>'
    # the project's three core readings: meet / part / fade — the topic pages' own glyphs
    '<symbol id="i-consensus" viewBox="0 0 24 24">'
    '<path d="M2.5 12H8.5M15.5 12h6" fill="none" stroke="currentColor" stroke-width="1.8"'
    ' stroke-linecap="round"/><path d="M12 7l5 5-5 5-5-5z" fill="currentColor"/></symbol>'
    '<symbol id="i-divergence" viewBox="0 0 24 24">'
    '<path d="M12 12C8.5 12 8.5 6 4.5 6h-2M12 12c3.5 0 3.5-6 7.5-6h2'
    'M12 12c-3.5 0-3.5 6-7.5 6h-2M12 12c3.5 0 3.5 6 7.5 6h2" fill="none"'
    ' stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
    '<circle cx="12" cy="12" r="1.8" fill="currentColor"/></symbol>'
    '<symbol id="i-silence" viewBox="0 0 24 24">'
    '<path d="M2.5 12h7" fill="none" stroke="currentColor" stroke-width="1.8"'
    ' stroke-linecap="round"/><circle cx="11" cy="12" r="2.3" fill="currentColor"/>'
    '<circle cx="16" cy="12" r="1.5" fill="currentColor" opacity=".62"/>'
    '<circle cx="20.5" cy="12" r=".9" fill="currentColor" opacity=".32"/></symbol>'
    "</svg>"
)

_STYLE = """
/* Three theme states, the same contract a topic page keeps: the bare palette below is
   the complete light one, the media query is the system default, and an explicit choice
   must win in both directions. */
:root{
  --serif:"Source Serif 4","Noto Serif SC",Georgia,"Songti SC",serif;
  /* The masthead's literal Latin "A"/"B" is a mark, not reading text — it must print
     the same face at every locale, the way its colours and layout already do.  A fixed copy of the *default* serif
     stack, never touched by the :lang() overrides below, keeps that true; wiring the
     wordmark straight to ``--serif`` (as it did before) let each locale's own reading
     face reach in and re-letter it too, since hi/ja/ar/ko's Noto Serif families each
     carry their own (differently metriced) Latin glyphs that shadow Source Serif 4's
     the moment `--serif` is redefined for `:root:lang(...)` — this is what changed
     the "A/B" mark's face and size under hi/ja/ar while en/zh, whose --serif override
     never fires, looked unaffected. */
  --wm-serif:"Source Serif 4","Noto Serif SC",Georgia,"Songti SC",serif;
  --sans:"IBM Plex Sans","Noto Sans SC",system-ui,-apple-system,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --paper:#FBFAF7;--panel:#FFFFFF;--ink:#14171A;--ink2:#41484E;--muted:#666D73;
  /* --muted is set one step darker than the topic pages' own: on this page it also has
     to clear 4.5:1 against --sunk (the footer band and the search hint), not only paper. */
  --rule:#E0DCD2;--accent:#8C2F1E;--a:#1D4E6B;--b:#8A5A16;
  --a-soft:color-mix(in oklab,var(--a) 12%,var(--panel));
  --b-soft:color-mix(in oklab,var(--b) 14%,var(--panel));
  --a-line:color-mix(in oklab,var(--a) 32%,var(--panel));
  --b-line:color-mix(in oklab,var(--b) 34%,var(--panel));
  --sunk:color-mix(in oklab,var(--ink) 4%,var(--paper));
  /* The topic stylesheet's own literal: the elevation an answer card sits at, one step
     above the module holding it.  The home grid's answer pair is the same component and
     has to be the same colour, which it was not while it mixed its tint into --paper —
     in dark that put the two answers *below* the card they sit in. */
  --answer-surface:#FFFFFF;
  --shadow:0 10px 30px rgba(20,23,26,.07);
  --tool:2.75rem;--page:74rem;--gutter:clamp(1.1rem,4vw,2.5rem);
  color-scheme:light dark;font-variant-numeric:tabular-nums;
}
/* Per-script reading faces (same stack as render/theme.py's topic-page CSS, so a
   reader crossing from the home page to an article never sees the face change). */
:root:lang(ko){
  --serif:"Noto Serif KR","Source Serif 4",Georgia,serif;
  --sans:"Noto Sans KR","IBM Plex Sans",system-ui,-apple-system,sans-serif;
}
:root:lang(ja){
  --serif:"Noto Serif JP","Source Serif 4",Georgia,serif;
  --sans:"Noto Sans JP","IBM Plex Sans",system-ui,-apple-system,sans-serif;
}
:root:lang(hi){
  --serif:"Noto Serif Devanagari","Source Serif 4",Georgia,serif;
  --sans:"Noto Sans Devanagari","IBM Plex Sans",system-ui,-apple-system,sans-serif;
}
:root:lang(ar){
  --serif:"Noto Naskh Arabic","Source Serif 4",Georgia,serif;
  --sans:"Noto Sans Arabic","IBM Plex Sans",system-ui,-apple-system,sans-serif;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#171B20;--panel:#1E242A;--ink:#E7E3DB;--ink2:#C4BFB6;--muted:#98A0A8;
    --rule:#363E46;--accent:#E08265;--a:#77AECD;--b:#D6A860;
    --a-soft:color-mix(in oklab,var(--a) 18%,var(--panel));
    --b-soft:color-mix(in oklab,var(--b) 18%,var(--panel));
    --a-line:color-mix(in oklab,var(--a) 40%,var(--panel));
    --b-line:color-mix(in oklab,var(--b) 40%,var(--panel));
    --sunk:color-mix(in oklab,var(--ink) 6%,var(--paper));
    --answer-surface:#262C33;
    --shadow:0 10px 30px rgba(0,0,0,.4);
  }
}
:root[data-theme="light"]{color-scheme:light}
:root[data-theme="dark"]{
  color-scheme:dark;
  --paper:#171B20;--panel:#1E242A;--ink:#E7E3DB;--ink2:#C4BFB6;--muted:#98A0A8;
  --rule:#363E46;--accent:#E08265;--a:#77AECD;--b:#D6A860;
  --a-soft:color-mix(in oklab,var(--a) 18%,var(--panel));
  --b-soft:color-mix(in oklab,var(--b) 18%,var(--panel));
  --a-line:color-mix(in oklab,var(--a) 40%,var(--panel));
  --b-line:color-mix(in oklab,var(--b) 40%,var(--panel));
  --sunk:color-mix(in oklab,var(--ink) 6%,var(--paper));
  --answer-surface:#262C33;
  --shadow:0 10px 30px rgba(0,0,0,.4);
}

*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth;scrollbar-gutter:stable}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:16px;
  line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:hidden}
a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:2px}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:2px}
::selection{background:var(--a-soft);color:var(--ink)}
[hidden]{display:none!important}
mark{background:color-mix(in oklab,var(--accent) 20%,var(--panel));color:var(--ink);
  border-radius:1px;padding:0 .06em}
/* The page's own tooltip.  A native ``title`` waits out the browser's ~1s dwell timer
   before it says anything, which on a card full of small badges reads as the page being
   slow rather than as a deliberate delay — nothing is being fetched, the browser is just
   waiting.  This one is CSS only, so it also works with scripting off, and no ancestor
   of a tip may clip its overflow. */
[data-tip]{position:relative}
/* ``display:none`` rather than a hidden-but-laid-out bubble: an invisible absolutely
   positioned box still counts towards the document's scroll width, and twenty of them
   on a phone push the page sideways.  The dwell is an animation delay instead of a
   transition, which is the one way to have both a delay and no layout when idle. */
[data-tip]::after{content:attr(data-tip);display:none;position:absolute;z-index:70;
  left:50%;bottom:calc(100% + .45rem);transform:translateX(-50%);
  width:max-content;max-width:min(17rem,62vw);padding:.42rem .58rem;border-radius:3px;
  background:var(--ink);color:var(--paper);font:500 11px/1.5 var(--sans);
  letter-spacing:.01em;text-align:left;white-space:normal;text-transform:none;
  pointer-events:none;box-shadow:0 6px 20px rgba(0,0,0,.24)}
[data-tip]:hover::after,[data-tip]:focus-visible::after{display:block;
  animation:tip-in .12s ease .07s both}
@keyframes tip-in{
  from{opacity:0;transform:translateX(-50%) translateY(.2rem)}
  to{opacity:1;transform:translateX(-50%) translateY(0)}}
@media (hover:none){[data-tip]::after{content:none}}
.vh{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
  clip-path:inset(50%);white-space:nowrap;border:0}
.wrap{width:min(var(--page),100%);margin-inline:auto;padding-inline:var(--gutter)}
/* A huge negative `left` used to push this off-screen.  That is direction-blind —
   in a `dir="rtl"` document a negative-x offset extends the document's *scrollable*
   overflow (RTL scrolls toward negative x) instead of just leaving the viewport the way
   it does under ltr, so the -9999px trick alone turned a hidden link into an 11,000px
   wide page.  A small transform keeps the link out of view without moving its box
   thousands of pixels off the layout in either direction. */
.skip{position:absolute;top:1rem;left:1rem;z-index:80;padding:.6rem .9rem;
  background:var(--panel);border:1px solid var(--accent);border-radius:3px;
  font:600 13px/1 var(--sans);color:var(--accent);text-decoration:none;
  transform:translateY(-150%);transition:transform .12s ease}
.skip:focus{transform:translateY(0)}
[dir="rtl"] .skip{left:auto;right:1rem}

/* ------------------------------------------------------------------ site-level tools
   The same circular controls a topic page pins to its corners, so one site, one row.
   ``justify-content:space-between`` is the logical half of the split (packs the two
   groups at the row's start/end, which flips with `dir` on its own — the same
   mechanism the topic page toolbar already relies on, see m2.py); it is not, on its
   own, enough. */
.site-tools{position:absolute;z-index:46;
  top:max(1rem,env(safe-area-inset-top));
  left:max(1rem,calc(env(safe-area-inset-left) + .5rem));
  right:max(1rem,calc(env(safe-area-inset-right) + .5rem));
  display:flex;justify-content:space-between;pointer-events:none}
.site-tools>*{pointer-events:auto}
/* ``.toolgroup--left`` never needs a pull of its own — ``justify-content:space
   -between`` above already seats it at the row's start — so its share of the
   ``margin-left:auto`` below (meant only to push the language/theme group to the
   row's end) is fixed at zero.  Before this, both groups shared the plain
   ``.toolgroup`` class and so shared that one auto margin; a flex row with the same
   physical auto-margin on every item does not split them one per edge, and under
   `dir="rtl"` it collapsed all four buttons onto the row's right end (see the RTL
   block below for the matching direction-aware swap, the piece the first RTL pass missed). */
.toolgroup{display:flex;align-items:center;gap:.4rem;margin-left:auto}
.toolgroup--left{margin-left:0}
.toolbtn{position:relative;display:inline-flex;align-items:center;justify-content:center;
  flex:none;width:var(--tool);height:var(--tool);padding:0;border:1px solid var(--rule);
  border-radius:50%;background:var(--panel);color:var(--ink2);cursor:pointer;
  box-shadow:0 5px 18px rgba(0,0,0,.12);
  transition:color .12s ease,border-color .12s ease}
.toolbtn:hover,.toolbtn:focus-visible,.toolbtn[aria-expanded="true"]{color:var(--accent);
  border-color:var(--accent)}
.toolbtn>svg{width:1.15rem;height:1.15rem;display:block;flex:none}
.langmenu{position:relative;display:flex}
.langmenu>nav{position:absolute;z-index:60;top:calc(100% + .4rem);right:0;
  display:flex;flex-direction:column;gap:.1rem;min-width:9rem;padding:.3rem;
  border:1px solid var(--rule);border-radius:7px;background:var(--panel);
  box-shadow:0 8px 26px rgba(0,0,0,.18)}
.langmenu>nav a{display:flex;align-items:center;gap:.5rem;min-height:2.3rem;
  padding:.3rem .55rem;border-radius:4px;color:var(--ink2);white-space:nowrap;
  font:500 13px/1.4 var(--sans);text-decoration:none}
.langmenu>nav a:hover{background:var(--sunk);color:var(--ink)}
.langmenu>nav a[aria-current="page"]{color:var(--accent);font-weight:600}
.langmenu>nav a::before{content:"";flex:none;width:.4rem;height:.4rem;border-radius:50%;
  background:transparent}
.langmenu>nav a[aria-current="page"]::before{background:currentColor}

/* --------------------------------------------------------------------- the masthead
   The name is the diagram: A and B are the two sampled sides.  Around them stands the
   word "news" in the scripts the site samples from — the Latin ``News`` in the middle is
   one of that halo, not its centre of gravity.  (There is no seam rule down the hero any
   more: at hairline width it read as a rendering artefact, not as a statement.) */
.masthead{position:relative;isolation:isolate;overflow:hidden;
  padding:calc(var(--tool) + 2.6rem) 0 clamp(2.2rem,5vw,3.4rem);text-align:center}
.masthead::before{content:"";position:absolute;inset:0;z-index:-2;
  background:
    linear-gradient(90deg,color-mix(in oklab,var(--a) 9%,transparent),transparent 48%),
    linear-gradient(270deg,color-mix(in oklab,var(--b) 10%,transparent),transparent 48%);
  -webkit-mask-image:linear-gradient(180deg,#000 0 58%,transparent 100%);
  mask-image:linear-gradient(180deg,#000 0 58%,transparent 100%)}
.mast-in{position:relative}
/* The neutral public-toolkit header: the site's own name, nothing borrowed. */
.masthead--plain{padding:calc(var(--tool) + 1.6rem) 0 clamp(1.2rem,3vw,1.8rem)}
.masthead--plain::before{content:none}
.plainmark{margin:0;font:600 clamp(24px,4vw,34px)/1.2 var(--serif);color:var(--ink);
  letter-spacing:.01em}
.wordmark{position:relative;display:grid;justify-items:center;gap:.1rem;
  margin-bottom:.42rem}
/* The ring lives inside the lockup's own box and is measured in its ``em``, so it holds
   its distance from the letters at every size — narrow screens included.  The offsets resolve in the slot's own font size, so the one narrow-width
   adjustment below is a font-size on the slot: the whole ring tightens proportionally. */
.wm-halo{position:absolute;inset:0;display:block;pointer-events:none}
.wm-slot{position:absolute;left:50%;top:50%;display:block;
  transform:translate(var(--ax),-50%) translate(var(--x),var(--y));
  transition:transform .5s cubic-bezier(.2,.7,.3,1) var(--d)}
.wm-word{display:block;white-space:nowrap;
  transition:opacity .5s ease var(--d),background-image .5s ease var(--d);
  font:600 clamp(11px,1.15vw,14px)/1 "IBM Plex Sans","Noto Sans SC","Noto Sans KR",
    "Noto Sans Devanagari","Noto Sans Arabic",system-ui,-apple-system,sans-serif;
  letter-spacing:.16em;text-indent:.16em;color:var(--muted);opacity:.62}
/* Fallback first: without background-clip the words stay flat grey rather than invisible.
   Each word's grey fades along its own radius, so the whole ring dims away from the name. */
@supports ((-webkit-background-clip:text) or (background-clip:text)){
  .wm-word{color:transparent;-webkit-text-fill-color:transparent;opacity:1;
    background-image:linear-gradient(var(--g),
      color-mix(in oklab,var(--tint) 26%,var(--ink2)) 52%,
      color-mix(in oklab,var(--muted) 38%,transparent));
    -webkit-background-clip:text;background-clip:text}
}
/* Each word drifts outward along its own radius, the far ones a beat later than the near
   ones: the lockup breathing, not sliding. */
.wordmark:hover .wm-slot,.wordmark:focus-within .wm-slot{
  transform:translate(var(--ax),-50%) translate(var(--x),var(--y))
    translate(calc(var(--dx) * .1em),calc(var(--dy) * .1em))}
.wordmark:hover .wm-word,.wordmark:focus-within .wm-word{opacity:.95}
@supports ((-webkit-background-clip:text) or (background-clip:text)){
  .wordmark:hover .wm-word,.wordmark:focus-within .wm-word{opacity:1;
    background-image:linear-gradient(var(--g),
      color-mix(in oklab,var(--tint) 40%,var(--ink)) 56%,
      color-mix(in oklab,var(--muted) 58%,transparent))}
}
.wm-ab{position:relative;display:grid;grid-template-columns:1fr auto 1fr;
  align-items:baseline;width:min(30rem,100%);
  font:700 clamp(4rem,15vw,8.5rem)/.95 var(--wm-serif);letter-spacing:-.03em}
.wm-a{justify-self:end;color:var(--a);padding-right:.14em;
  transition:transform .3s cubic-bezier(.2,.7,.3,1)}
.wm-b{justify-self:start;color:var(--b);padding-left:.14em;
  transition:transform .3s cubic-bezier(.2,.7,.3,1)}
.wm-slash{color:var(--muted);opacity:.45;font-weight:400}
.wordmark:hover .wm-a{transform:translateX(-.035em)}
.wordmark:hover .wm-b{transform:translateX(.035em)}
/* two rules, one per side, parted at the seam — never one blended bar */
.wm-rule{width:min(30rem,100%);height:2px;margin-top:.55rem;transform-origin:center;
  background:linear-gradient(90deg,var(--a) 0 calc(50% - 4px),
    transparent calc(50% - 4px) calc(50% + 4px),var(--b) calc(50% + 4px) 100%);
  animation:wm-part .6s cubic-bezier(.2,.7,.3,1) both}
@keyframes wm-part{from{transform:scaleX(.06);opacity:0}to{transform:scaleX(1);opacity:1}}
/* Sits right under the parted rule and wears the ring's own tracking: the saying, the
   mark and the nine words are one lockup, and a gap or a different colour would make
   this read as an unrelated line of body text. */
.tagline{display:grid;justify-items:center;
  font:400 clamp(15px,1.6vw,19px)/1.45 var(--serif);color:var(--ink2);
  letter-spacing:.16em;max-width:34rem;margin:0 auto}
/* All nine sayings share the one grid cell, so the band is as tall as the tallest and
   the page never jumps when they rotate; the hidden ones keep their layout but no ink. */
.tagline-item{grid-area:1/1;max-width:100%;text-indent:.16em;text-wrap:balance;
  opacity:0;transform:translateX(1.4em);
  transition:opacity .55s ease,transform .55s ease;pointer-events:none}
.tagline-item.on{opacity:1;transform:none}
.tagline-item.out{opacity:0;transform:translateX(-1.4em)}

/* -------------------------------------------------------------- how to read the site */
.band{border-block:1px solid var(--rule);background:var(--sunk)}
.how{list-style:none;display:grid;grid-template-columns:repeat(3,1fr);gap:0}
.how li{display:grid;gap:.2rem;align-content:start;padding:1.15rem 1.3rem 1.25rem;
  border-left:1px solid var(--rule)}
.how li:first-child{border-left:0;padding-left:0}
.how li:last-child{padding-right:0}
.how .n{font:500 10.5px/1 var(--mono);color:var(--accent);letter-spacing:.1em}
.how .h{font:600 13.5px/1.45 var(--sans);color:var(--ink)}
.how .x{font:400 13px/1.6 var(--serif);color:var(--ink2);text-wrap:pretty}

/* ------------------------------------------------------------------------- sections */
main{display:block}
.section{padding-top:clamp(2.4rem,5vw,3.6rem);scroll-margin-top:1rem}
.section>.shead,.section>.exp-bar,.section>.grid,.section>.empty,.section>.more-row,
.section>.lead-hold{width:min(var(--page),100%);margin-inline:auto;
  padding-inline:var(--gutter)}
.shead{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;
  flex-wrap:wrap;margin-bottom:1.15rem;padding-bottom:.55rem;
  border-bottom:1px solid var(--rule)}
.shead h2{font:600 clamp(17px,2vw,21px)/1.3 var(--sans);letter-spacing:.01em;
  display:flex;align-items:center;gap:.55rem}
.shead h2::before{content:"";width:.45rem;height:.45rem;background:var(--accent);
  flex:none;border-radius:1px}
.shead .n{font:500 11px/1.6 var(--mono);color:var(--muted);letter-spacing:.03em}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,20rem),1fr));
  gap:1rem}
.empty{font:400 15px/1.7 var(--serif);color:var(--muted);padding:2.5rem 0;
  text-align:center}
.more-row{display:flex;justify-content:center;margin-top:1.6rem}
.more{font:600 13px/1 var(--sans);padding:.85rem 1.6rem;border:1px solid var(--rule);
  border-radius:2px;background:var(--panel);color:var(--ink2);cursor:pointer}
.more:hover{border-color:var(--accent);color:var(--accent)}
/* Where subgrid exists, the cards in one row share the grid's own rows, so the question
   rule and the answer pair line up on the tallest real headline rather than on a fixed
   three-line reservation.  The min-heights above stay as the fallback. */
@supports (grid-template-rows:subgrid){
  /* The single column has to be stated as `minmax(0,1fr)`: an implicit `auto` track
     is floored at its content's min-content width, so one unbreakable kicker (a
     long category beside a nowrap date range, e.g. `/ru/`) widened the card's own
     track past the card and printed the row out through its border. */
  .grid>.tcard{display:grid;grid-template-columns:minmax(0,1fr);
    grid-template-rows:subgrid;grid-row:span 3;row-gap:0}
  .grid>.tcard>.tbody{grid-row:span 1}
  .grid>.tcard .tt{min-height:0}
  .grid>.tcard .tb{min-height:0;margin-top:.42rem}
}

/* --------------------------------------------------------------- the topic card
   A miniature of the topic page's answer pair: one question, two answers, and the mark
   of the relation between them.  The 3px bar and flat tint on each answer are the
   same A|B pairing the article's answer cards wear. */
.tcard{position:relative;display:flex;flex-direction:column;background:var(--panel);
  border:1px solid var(--rule);border-radius:3px;padding:1.05rem 1.15rem 1.15rem;
  transition:border-color .16s ease,box-shadow .16s ease,transform .16s ease}
/* One quiet accent, not a split A|B bar: the answer cards below already state the two
   sides in colour, and a second pairing at the top of the card only competed with them. */
.tcard::before{content:"";position:absolute;top:-1px;left:-1px;right:-1px;height:2px;
  border-radius:3px 3px 0 0;background:var(--accent);opacity:.42}
/* The lift is a transform, so a hovered card becomes its own stacking context and its
   tooltip would otherwise be painted over by the next card in the grid. */
.tcard:hover,.tcard:focus-within{z-index:5}
.tcard:hover{transform:translateY(-2px);box-shadow:var(--shadow);
  border-color:color-mix(in oklab,var(--accent) 32%,var(--rule))}
.tcard:hover::before,.tcard:focus-within::before{opacity:.85}
.tbody{display:flex;flex-direction:column;gap:.42rem}
/* One line, always: a kicker that wraps on some cards and not on others takes the row
   alignment below it with it.  Nothing here clips its overflow — the sample window
   carries a tooltip, and a clipped ancestor would swallow it. */
.tk{display:flex;align-items:center;gap:.5rem;flex-wrap:nowrap;min-width:0;
  font:500 11px/1.5 var(--sans);color:var(--muted);letter-spacing:.02em}
/* The category is the one part of the kicker that may be any length in any language
   ("Международные отношения" is 203px where "Diplomacy" is 83px) and the only part that
   survives being cut short, so it is what gives when the row runs out of card: the
   sample window keeps its full width, the category ellipsises, and the row stays one
   line inside its card.  Clipping here does not reach the window's tooltip — that lives
   on the sibling `.win`, which nothing clips. */
.tk .cat{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;color:var(--accent);font-weight:600}
.tk .win{flex:none;font-family:var(--mono);font-size:10.5px;white-space:nowrap;cursor:help}
/* A grid card holds the same rows at the same heights, so the question rule and the
   answer pair line up across a row instead of drifting with the length of each brief. */
.tt{font:600 clamp(16.5px,1.25vw,18.5px)/1.35 var(--serif);letter-spacing:-.008em;
  text-wrap:pretty;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;
  overflow:hidden;min-height:4.05em}
.tt a{color:var(--ink);text-decoration:none}
/* one click target over the whole card; the question below keeps its own, above it */
.tt a::after{content:"";position:absolute;inset:0;z-index:1}
.tcard:hover .tt a{color:var(--accent)}
.tb{font:400 13.5px/1.65 var(--serif);color:var(--ink2);text-wrap:pretty;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  min-height:3.3em}
.tqa{position:relative;z-index:2;display:block;margin-top:.85rem;padding-top:.8rem;
  border-top:1px solid var(--rule);text-decoration:none;color:inherit}
.tq{display:flex;gap:.4rem;font:500 12.5px/1.55 var(--sans);color:var(--ink2)}
.tq .qm{color:var(--accent);font-weight:600;flex:none}
.tqa:hover .qtext{color:var(--accent)}
/* No column gap: the relation column *is* the gap, and its two leads have to reach
   from a card's edge to the mark without a hole at either end. */
.tduo{display:grid;grid-template-columns:1fr auto 1fr;align-items:stretch;gap:0;
  margin-top:.65rem}
/* The side tag hugs the top of the card, centred; the count keeps the corner beside it;
   and everything left over belongs to the answer, which centres in it both ways. */
.tside{position:relative;display:flex;flex-direction:column;align-items:center;
  justify-content:flex-start;gap:.35rem;text-align:center;min-width:0;
  padding:.5rem .55rem .7rem;
  border:1px solid var(--rule);border-top-width:3px;border-radius:0 0 3px 3px;
  background:var(--answer-surface)}
/* The same tint the topic page's answer cards wear, on the same surface and at the same
   percentages: a flat wash of the side's colour under the thicker top bar, one step
   quieter than the badge's own soft tone. */
.tside--a{border-top-color:var(--a);
  background:color-mix(in oklab,var(--a) 7%,var(--answer-surface))}
.tside--b{border-top-color:var(--b);
  background:color-mix(in oklab,var(--b) 8%,var(--answer-surface))}
.thead{display:flex;align-items:center;justify-content:center;width:100%;min-width:0}
/* Kept clear of the corner the count sits in, since the two now share a line. */
.gtagw{display:flex;min-width:0;max-width:calc(100% - 2.7rem);cursor:help}
.tside .gtag{display:block;min-width:0;overflow:hidden;text-overflow:ellipsis;
  font:600 9.5px/1.55 var(--sans);letter-spacing:.03em;padding:.04rem .28rem;
  border:1px solid var(--rule);border-radius:2px;white-space:nowrap}
.tside--a .gtag{color:var(--a);background:var(--a-soft);border-color:var(--a-line)}
.tside--b .gtag{color:var(--b);background:var(--b-soft);border-color:var(--b-line)}
.tside .ans{margin:auto 0;font:600 15px/1.4 var(--serif);color:var(--ink);
  text-wrap:pretty;overflow-wrap:anywhere}
.tside .cnt{position:absolute;top:.62rem;right:.45rem;
  font:500 9px/1 var(--mono);color:var(--muted);cursor:help;letter-spacing:.02em}
.tside--silent{background:color-mix(in oklab,var(--muted) 7%,var(--answer-surface));
  border-style:dashed;border-top-style:solid;
  border-top-color:color-mix(in oklab,var(--muted) 50%,var(--panel))}
.tside--silent .ans{font-weight:400;font-style:italic;color:var(--muted)}
/* Two leads, each in its own side's colour, exactly as the topic page draws them: the
   mark is not floating between the answers, it is attached to both.  Each lead is sized
   by the gap it has to close rather than by a guessed length, so it keeps touching both
   ends when the mark or the column changes size. */
.trel{--markw:1.75rem;position:relative;display:flex;align-items:center;
  justify-content:center;width:3.1rem;flex:none}
.trel::before,.trel::after{content:"";position:absolute;top:50%;margin-top:-1px;
  height:2px;border-radius:1px}
.trel::before{left:0;right:calc(50% + var(--markw) / 2);background:var(--a)}
.trel::after{right:0;left:calc(50% + var(--markw) / 2);background:var(--b)}
/* A side that said nothing gets the muted dotted lead the topic page gives it. */
.trel--asilent::before,.trel--bsilent::after{background:none;height:0;
  border-top:2px dotted color-mix(in oklab,var(--muted) 70%,transparent)}
.trel .mark{position:relative;width:1.75rem;height:1.75rem;border-radius:50%;
  border:1.3px solid var(--rule);background:var(--panel);color:var(--ink2);
  display:flex;align-items:center;justify-content:center;cursor:help;
  transition:color .16s ease,border-color .16s ease}
.trel svg{width:1.15rem;height:1.15rem;display:block}
.tcard:hover .trel .mark{border-color:color-mix(in oklab,var(--accent) 40%,var(--rule));
  color:var(--accent)}
/* Wrapping, because the footer is the widest unbreakable thing on the card: two runs
   that each refuse to break — "32 independent reports | 5 angles" and "Read the
   comparison →" — add up to more than a 20rem column in English, and on one line they
   would floor the card's whole column at their sum and push every row of it out past
   the border.  Wrapped, the card's floor is the wider of the two runs, not the sum. */
.tf{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;
  gap:.35rem .6rem;
  margin-top:auto;padding-top:.85rem;font:500 11.5px/1.5 var(--sans);color:var(--muted)}
.tf .read{color:var(--accent);font-weight:600;white-space:nowrap}
.tf .qn{display:inline-flex;align-items:center;min-width:0;
  font-family:var(--mono);font-size:10.5px}
.tf .qn>span{white-space:nowrap}
.tf .qn>span+span::before{content:"|";margin:0 .45rem;opacity:.45}

/* -------------------------------------------------------------------- the lead card */
.lead-hold{margin:0}
.tcard--lead{padding:clamp(1.2rem,2.6vw,1.9rem);gap:0;
  display:grid;grid-template-columns:minmax(0,1.02fr) minmax(0,1fr);
  column-gap:clamp(1.4rem,3.5vw,3rem);align-items:stretch}
.tcard--lead .tbody{gap:.55rem;height:100%}
.tcard--lead .tk{flex-wrap:wrap;overflow:visible}
.tcard--lead .tk .win{overflow:visible;white-space:normal}
/* The lead card's kicker wraps instead of running out of room, so nothing has to give. */
.tcard--lead .tk .cat{overflow:visible;white-space:normal}
.tlead-side{display:flex;flex-direction:column;justify-content:center;min-width:0;
  border-left:1px solid var(--rule);padding-left:clamp(1.2rem,3vw,2.2rem)}
.tcard--lead .tt{font-size:clamp(23px,3.1vw,35px);line-height:1.22;letter-spacing:-.014em;
  display:block;min-height:0;overflow:visible}
.tcard--lead .tb{font-size:15px;line-height:1.7;-webkit-line-clamp:4;min-height:0}
.tcard--lead .tf{padding-top:1.1rem;font-size:12.5px}
.tcard--lead .tqa{margin-top:0;padding-top:0;border-top:0}
.tcard--lead .tq{font-size:13.5px}
.tcard--lead .tduo{margin-top:.85rem}
.tcard--lead .tside{padding:.7rem .8rem 1.1rem}
.tcard--lead .tside .cnt{top:.85rem;right:.7rem;font-size:10px}
.tcard--lead .gtagw{max-width:calc(100% - 3.4rem)}
.tcard--lead .tside .ans{font-size:clamp(16px,1.7vw,19.5px)}
.tcard--lead .trel{--markw:2.1rem;width:3.9rem}
.tcard--lead .trel .mark{width:2.1rem;height:2.1rem}
.tcard--lead .trel svg{width:1.35rem;height:1.35rem}
.qchips{display:flex;flex-wrap:wrap;gap:.35rem;margin-top:.9rem;position:relative;z-index:2}
.qchip{display:inline-flex;align-items:baseline;gap:.3rem;max-width:100%;min-width:0;
  font:500 11.5px/1.5 var(--sans);color:var(--muted);text-decoration:none;
  padding:.28rem .55rem;border:1px dashed var(--rule);border-radius:2px}
.qchip .qm{flex:none;color:var(--accent);font-weight:600}
.qchip .qx{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qchip:hover{color:var(--accent);border-color:var(--accent);border-style:solid}
@media (max-width:56rem){
  .tcard--lead{grid-template-columns:1fr;row-gap:1.1rem}
  .tlead-side{border-left:0;padding-left:0;padding-top:.95rem;
    border-top:1px solid var(--rule)}
}

/* ---------------------------------------------------------------------- the explorer */
/* ``minmax(0,1fr)``, not the default ``auto``: the chip row scrolls sideways on a
   narrow screen, and an auto-sized grid column would take its max-content width and
   push the whole page wider instead. */
.exp-bar{display:grid;grid-template-columns:minmax(0,1fr);gap:.8rem;
  margin-bottom:1.4rem}
.exp-search{position:relative;display:flex}
.exp-search input{width:100%;font:400 15px/1.5 var(--sans);color:var(--ink);
  padding:.85rem 4.4rem .85rem 2.7rem;border:1px solid var(--rule);border-radius:3px;
  background:var(--panel);-webkit-appearance:none;appearance:none}
.exp-search input::-webkit-search-cancel-button{display:none}
.exp-search input::placeholder{color:var(--muted)}
.exp-search input:focus{border-color:var(--accent);outline:none;
  box-shadow:0 0 0 3px color-mix(in oklab,var(--accent) 12%,transparent)}
.exp-search .ic{position:absolute;left:.9rem;top:50%;transform:translateY(-50%);
  color:var(--muted);display:flex}
.exp-search .ic svg{width:1.05rem;height:1.05rem}
.exp-search kbd{position:absolute;right:.75rem;top:50%;transform:translateY(-50%);
  font:500 11px/1 var(--mono);color:var(--muted);border:1px solid var(--rule);
  border-radius:3px;padding:.25rem .45rem;background:var(--sunk)}
.exp-search .clear{position:absolute;right:.6rem;top:50%;transform:translateY(-50%);
  display:flex;align-items:center;justify-content:center;width:2rem;height:2rem;
  border:0;border-radius:50%;background:none;color:var(--muted);cursor:pointer}
.exp-search .clear:hover{color:var(--accent)}
.exp-search .clear svg{width:1rem;height:1rem}
/* Three dropdowns of one shape, asked of the topics rather than of the chrome: which
   category a topic sits in, which languages it can be *read* in, and which languages its
   two samples *report* in.  They stand in one row because they narrow one grid. */
.exp-langs{display:flex;flex-wrap:wrap;gap:.45rem;min-width:0}
.lf{position:relative;min-width:0}
.lfbtn{display:inline-flex;align-items:center;gap:.5rem;max-width:100%;
  padding:.45rem .6rem;border:1px solid var(--rule);border-radius:2px;
  background:var(--panel);color:var(--ink2);cursor:pointer;
  font:500 12px/1.4 var(--sans);text-align:left;
  transition:color .12s ease,border-color .12s ease}
.lfbtn:hover,.lfbtn[aria-expanded="true"]{border-color:var(--accent);color:var(--accent)}
.lfl{flex:none;color:var(--muted)}
.lfbtn:hover .lfl,.lfbtn[aria-expanded="true"] .lfl{color:inherit}
.lfv{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-weight:600;color:var(--ink)}
.lfbtn:hover .lfv,.lfbtn[aria-expanded="true"] .lfv{color:inherit}
.lf[data-lf-on="1"] .lfbtn{border-color:var(--accent);color:var(--accent);
  background:color-mix(in oklab,var(--accent) 6%,var(--panel))}
.lfc{flex:none;width:.85rem;height:.85rem;display:block;color:var(--muted);
  transition:transform .14s ease}
.lfbtn[aria-expanded="true"] .lfc{transform:rotate(180deg)}
.lfmenu{position:absolute;z-index:62;top:calc(100% + .35rem);left:0;
  display:flex;flex-direction:column;gap:.05rem;min-width:12rem;
  max-height:17rem;overflow-y:auto;padding:.35rem;
  border:1px solid var(--rule);border-radius:6px;background:var(--panel);
  box-shadow:0 8px 26px rgba(0,0,0,.18)}
.lfopt{display:flex;align-items:center;gap:.5rem;min-height:2.1rem;padding:.2rem .45rem;
  border-radius:4px;cursor:pointer;font:500 12.5px/1.4 var(--sans);color:var(--ink2);
  white-space:nowrap}
.lfopt:hover{background:var(--sunk);color:var(--ink)}
.lfopt input{flex:none;width:.9rem;height:.9rem;accent-color:var(--accent);cursor:pointer}
/* The one control that says "no restriction at all" — the media filter would otherwise
   have no way back out of itself once a language is ticked. */
.lfany{margin-bottom:.2rem;padding:.35rem .45rem;border:0;border-bottom:1px solid var(--rule);
  border-radius:4px 4px 0 0;background:none;color:var(--ink2);cursor:pointer;
  text-align:left;font:500 12.5px/1.4 var(--sans);white-space:nowrap}
.lfany:hover{background:var(--sunk);color:var(--ink)}
.lfany[aria-pressed="true"]{color:var(--accent);font-weight:600}
.exp-filters{display:flex;align-items:center;gap:.55rem;flex-wrap:wrap;min-width:0}
/* The order control asks a different kind of question from every filter beside it, so it
   keeps the row's far edge to itself. */
.exp-filters>.seg{flex:none;margin-left:auto}
.seg{display:inline-flex;border:1px solid var(--rule);border-radius:2px;overflow:hidden;
  flex:none}
.seg button{font:500 12px/1.4 var(--sans);padding:.45rem .8rem;border:0;
  background:var(--panel);color:var(--muted);cursor:pointer;white-space:nowrap}
.seg button+button{border-left:1px solid var(--rule)}
.seg button[aria-pressed="true"]{background:var(--sunk);color:var(--ink);font-weight:600}
.seg button:hover{color:var(--ink)}

/* -------------------------------------------------------------------------- footer */
footer{margin-top:clamp(3rem,7vw,5rem);border-top:1px solid var(--rule);
  background:var(--sunk)}
.foot{display:flex;align-items:center;justify-content:center;padding-block:1.5rem 1.9rem}
.fstamp{display:inline-flex;align-items:center;gap:.35em;margin:0;text-align:center;
  font:500 10.5px/1.5 var(--mono);color:var(--muted);letter-spacing:.04em}
/* The GitHub mark stands where the producer version used to: same colour as the byline,
   the accent on hover, and a real touch target (var(--tool)) without changing the line's
   height. */
.fgit{display:inline-flex;align-items:center;justify-content:center;width:var(--tool);height:var(--tool);
  margin-block:calc((1.5em - var(--tool)) / 2);border-radius:50%;color:inherit;text-decoration:none}
.fgit svg{width:1.35em;height:1.35em}
.fgit:hover,.fgit:focus-visible{color:var(--accent)}

/* ------------------------------------------------------------------- back to the top
   The same control, in the same corner, with the same reveal as a topic page: one site,
   one way back up. */
.top-fab{position:fixed;z-index:44;
  right:max(1rem,calc(env(safe-area-inset-right) + .5rem));
  bottom:max(1rem,calc(env(safe-area-inset-bottom) + .5rem));
  width:var(--tool);height:var(--tool);display:flex;align-items:center;
  justify-content:center;border:1px solid var(--rule);border-radius:50%;
  background:var(--panel);color:var(--ink2);box-shadow:0 5px 18px rgba(0,0,0,.12);
  font:600 1.15rem/1 var(--sans);text-decoration:none;
  transition:opacity .14s ease,transform .14s ease}
.top-fab:hover{color:var(--accent);border-color:var(--accent)}
.js .top-fab:not(.shown){opacity:0;transform:translateY(.5rem);pointer-events:none}

/* --------------------------------------------------------------------------- RTL
   Same contract as the topic
   page's own RTL layer (render/theme.py) — prose and furniture mirror under
   dir="rtl", but the masthead's A/B split and each topic card's miniature answer pair
   carry the same side semantic the topic page's `.duo` does, so they don't. */
[dir="rtl"] .wm-ab,
[dir="rtl"] .tduo{direction:ltr}
[dir="rtl"] .tside{direction:rtl}
[dir="rtl"] .theme-fab{right:auto;left:1rem}
[dir="rtl"] .top-fab{right:auto;left:max(1rem,calc(env(safe-area-inset-left) + .5rem))}
/* The piece the first RTL pass missed: `.toolgroup`'s ``margin-left:auto`` (above) is a physical
   property, so under rtl it must swap sides to keep pushing the language/theme group
   toward the row's *end* rather than adding to `.toolgroup--left`'s already-zero
   pull — same fix already shipped for the topic page toolbar (render/m2.py). */
[dir="rtl"] .toolgroup:not(.toolgroup--left){margin-left:0;margin-right:auto}
[dir="rtl"] .langmenu>nav{right:auto;left:0}
[dir="rtl"] .exp-search .ic{left:auto;right:.9rem}
[dir="rtl"] .exp-search kbd{right:auto;left:.75rem}
[dir="rtl"] .exp-search .clear{right:auto;left:.6rem}
[dir="rtl"] .exp-search input{padding-right:2.7rem;padding-left:4.4rem}
[dir="rtl"] .exp-filters>.seg{margin-left:0;margin-right:auto}
""".strip()


#: Refinements that only apply once the page is a real site page: touch targets, the
#: narrow layouts, and the reduced-motion contract.
_M2_STYLE = """
@media (max-width:56rem){
  /* Stacked, the story must not end in its own call to action and then continue: the
     comparison moves above the foot, so the card still reads top to bottom. */
  .tcard--lead{display:flex;flex-direction:column;gap:.55rem}
  .tcard--lead>.tbody{display:contents}
  .tcard--lead .tk{order:1}
  .tcard--lead .tt{order:2}
  .tcard--lead .tb{order:3}
  .tlead-side{order:4;margin-top:.4rem}
  .tcard--lead .tf{order:5;margin-top:.2rem}
}
@media (max-width:44rem){
  .how{grid-template-columns:1fr}
  .how li{border-left:0;border-top:1px solid var(--rule);padding-inline:0}
  .how li:first-child{border-top:0}
}
@media (max-width:40rem){
  .masthead{padding-top:calc(var(--tool) + 1.8rem)}
  .wm-ab{font-size:clamp(3.2rem,22vw,5rem);width:100%}
  /* The ring stays a ring on a phone; it only tightens.  The slot font is what the
     offsets resolve in, so shrinking it pulls every word inward by the same fraction,
     and the words themselves drop a step so the flanks clear the screen edge. */
  .wm-slot{font-size:.92em}
  .wm-word{font-size:10.5px;letter-spacing:.12em;text-indent:.12em}
  .wm-rule{width:100%}
  .tagline{font-size:clamp(14px,4vw,17px)}
  .grid{grid-template-columns:1fr;gap:.85rem}
  /* One card per row, so there is no neighbour left for the kicker to stay aligned
     with -- which is the only reason it is held to one line.  Let it wrap here, or on
     the narrowest phones the sample window is what pushes past the card's edge. */
  .tk{flex-wrap:wrap}
  .tduo{grid-template-columns:1fr}
  /* Stacked, the relation stands between the cards and its two leads stand up with it,
     each still closing the whole distance from a card's edge to the mark. */
  .trel,.tcard--lead .trel{width:auto;height:2.9rem}
  .trel::before,.trel::after{left:50%;right:auto;top:auto;bottom:auto;
    margin:0 0 0 -1px;width:2px;height:auto;border-radius:1px}
  .trel::before{top:0;bottom:calc(50% + var(--markw) / 2)}
  .trel::after{bottom:0;top:calc(50% + var(--markw) / 2)}
  .trel--asilent::before,.trel--bsilent::after{background:none;width:0;
    border-top:0;border-left:2px dotted color-mix(in oklab,var(--muted) 70%,transparent)}
  /* The connector turned a quarter turn, so the mark it carries turns with it — the
     topic page does exactly this at the same width, and without it a silence points
     sideways at a card that is now above or below. */
  .trel svg{transform:rotate(90deg)}
  /* Everything in the filter row wraps together — the three dropdowns and the order
     control are one flow of buttons, not stacked blocks.  The group box dissolves into
     the row itself, so the line breaks fall between buttons rather than between groups. */
  .exp-langs{display:contents}
  .exp-filters>.seg{margin-left:0}
  .lfmenu{min-width:min(15rem,calc(100vw - 2 * var(--gutter)))}
  .qchip{max-width:100%}
}
@media (pointer:coarse){
  .seg button,.more,.lfbtn,.lfany{min-height:44px}
  .lfopt{min-height:2.6rem}
  a,input,button{touch-action:manipulation}
  .exp-search kbd{display:none}
}
@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  *,*::before,*::after{transition:none!important;animation:none!important}
}
@media (forced-colors:active){
  .tcard::before,.wm-rule{forced-color-adjust:none}
}
""".strip()


#: Applied in ``<head>`` so a stored dark choice never flashes light first, and so
#: JavaScript-only affordances can be declared before the first paint.
_HEAD_JS = """
document.documentElement.classList.add('js');
try{var p=JSON.parse(localStorage.getItem('newsab.prefs')||'{}')||{};
if(p.theme==='dark'||p.theme==='light')document.documentElement.setAttribute('data-theme',p.theme)}catch(e){}
""".strip()


#: The same preference key and the same two icons a topic page uses, so one choice holds
#: across the whole site.
_THEME_JS = r"""
(()=>{const b=document.getElementById('themebtn');if(!b)return;
const dark=()=>{const set=document.documentElement.getAttribute('data-theme');
return set?set==='dark':matchMedia('(prefers-color-scheme:dark)').matches};
const sync=()=>{b.querySelector('use').setAttribute('href',dark()?'#i-sun':'#i-moon')};
b.addEventListener('click',()=>{const next=dark()?'light':'dark';
document.documentElement.setAttribute('data-theme',next);
try{const p=JSON.parse(localStorage.getItem('newsab.prefs')||'{}')||{};p.theme=next;
localStorage.setItem('newsab.prefs',JSON.stringify(p))}catch(e){}sync()});sync()})();
""".strip()


#: The locale chooser, opened from the globe: same behaviour as the topic pages' menu.
_LANG_JS = r"""
(()=>{const t=document.getElementById('langbtn');if(!t)return;
const menu=document.getElementById('site-language-menu');if(!menu)return;
const close=()=>{menu.hidden=true;t.setAttribute('aria-expanded','false')};
t.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();
const open=menu.hidden;menu.hidden=!open;t.setAttribute('aria-expanded',open?'true':'false');
if(open){const first=menu.querySelector('a');if(first)first.focus()}});
document.addEventListener('click',event=>{if(menu.hidden)return;
if(t.parentNode.contains(event.target))return;close()});
document.addEventListener('keydown',event=>{if(event.key!=='Escape'||menu.hidden)return;
close();t.focus()})})();
""".strip()


#: The tagline band: hold each saying a few beats, slide it out left, bring the next in
#: from the right.  The order is the reader's own saying first, then a shuffle of the
#: rest; readers who asked for reduced motion keep the static line.
_TAGLINE_JS = r"""
(()=>{const box=document.querySelector('[data-taglines]');if(!box)return;
if(matchMedia('(prefers-reduced-motion:reduce)').matches)return;
const items=Array.from(box.children);if(items.length<2)return;
let start=items.findIndex(item=>item.classList.contains('on'));
if(start<0)start=0;
const rest=items.map((_,index)=>index).filter(index=>index!==start);
for(let i=rest.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));
[rest[i],rest[j]]=[rest[j],rest[i]]}
const order=[start,...rest];let at=0;
setInterval(()=>{const current=items[order[at]];
at=(at+1)%order.length;
const next=items[order[at]];
current.classList.remove('on');current.classList.add('out');
current.setAttribute('aria-hidden','true');
next.classList.remove('out');void next.offsetWidth;
next.classList.add('on');next.removeAttribute('aria-hidden')},5000)})();
""".strip()


#: The same reveal a topic page uses, so the control appears at the same point on both.
_TOP_JS = r"""
(()=>{const fab=document.getElementById('backtotop');if(!fab)return;
const sync=()=>{const show=window.scrollY>Math.max(320,window.innerHeight/2);
fab.classList.toggle('shown',show);fab.tabIndex=show?0:-1;
fab.setAttribute('aria-hidden',show?'false':'true')};
sync();window.addEventListener('scroll',sync,{passive:true});
window.addEventListener('resize',sync,{passive:true})})();
""".strip()


#: The explorer reads the cards themselves — their folded text, their categories and the
#: two orders the server computed.  It never re-creates a card, so what a filtered page
#: shows is exactly what the build wrote.
_EXPLORER_JS = r"""
(()=>{
const root=document.getElementById('browse');if(!root)return;
const grid=root.querySelector('[data-grid]');if(!grid)return;
const input=root.querySelector('[data-site-search]');
const status=root.querySelector('[data-search-count]');
const emptyBox=root.querySelector('[data-empty]');
const clearBtn=root.querySelector('[data-clear]');
const moreBtn=root.querySelector('[data-more]');
const orders=Array.from(root.querySelectorAll('[data-order]'));
const data=document.documentElement.dataset;
const STEP=Number(data.pageStep)||12;
let shown=STEP,order='latest',terms=[];
const rows=Array.from(grid.querySelectorAll('.tcard')).map(card=>{
  const t=card.querySelector('[data-t]'),b=card.querySelector('[data-b]');
  const list=name=>(card.getAttribute(name)||'').split(' ').filter(Boolean);
  return {card:card,t:t,b:b,tText:t?t.textContent:'',bText:b?b.textContent:'',
    hay:card.getAttribute('data-search')||'',
    cats:list('data-cats'),read:list('data-read'),media:list('data-media'),
    i:Number(card.getAttribute('data-i')),d:Number(card.getAttribute('data-d'))};
});
// Three dropdowns, two kinds of question.  Reading language is a *preference over* the
// locales a topic is published in, so it matches when any ticked locale is among them.
// Media language is a *restriction on* the two samples, so every ticked language must be
// one the topic sampled -- and an empty selection is the way to say "no restriction".
// Category is a restriction too, but a topic may sit in two, so any ticked one matches.
const langPick={cat:[],read:[],media:[]};
const langBoxes=Array.from(root.querySelectorAll('.lf'));
function syncLangBox(box){
  const key=box.getAttribute('data-lf')||'';
  const opts=Array.from(box.querySelectorAll('.lfopt input'));
  const picked=opts.filter(opt=>opt.checked);
  langPick[key]=picked.map(opt=>opt.value);
  const summary=box.querySelector('[data-lf-summary]');
  if(summary)summary.textContent=picked.length
    ?picked.map(opt=>(opt.parentNode.textContent||'').trim()).join('\u3001')
    :(box.getAttribute('data-lf-empty')||'');
  const changed=langPick[key].join(' ')!==(box.getAttribute('data-lf-initial')||'');
  box.setAttribute('data-lf-on',changed?'1':'0');
  const anyBtn=box.querySelector('[data-lf-any]');
  if(anyBtn)anyBtn.setAttribute('aria-pressed',picked.length?'false':'true');
}
function closeLang(box){
  const button=box.querySelector('.lfbtn'),menu=box.querySelector('.lfmenu');
  if(!button||!menu)return;menu.hidden=true;button.setAttribute('aria-expanded','false');
}
for(const box of langBoxes){
  const opts=Array.from(box.querySelectorAll('.lfopt input'));
  box.setAttribute('data-lf-initial',
    opts.filter(opt=>opt.checked).map(opt=>opt.value).join(' '));
  syncLangBox(box);
  for(const opt of opts)
    opt.addEventListener('change',()=>{syncLangBox(box);refilter()});
  const anyBtn=box.querySelector('[data-lf-any]');
  if(anyBtn)anyBtn.addEventListener('click',()=>{
    for(const opt of opts)opt.checked=false;syncLangBox(box);refilter()});
  const button=box.querySelector('.lfbtn'),menu=box.querySelector('.lfmenu');
  if(!button||!menu)continue;
  button.addEventListener('click',event=>{
    event.stopPropagation();
    const open=menu.hidden;
    for(const other of langBoxes)closeLang(other);
    if(!open)return;
    menu.hidden=false;button.setAttribute('aria-expanded','true');
  });
  document.addEventListener('click',event=>{
    if(menu.hidden||box.contains(event.target))return;closeLang(box);
  });
  document.addEventListener('keydown',event=>{
    if(event.key!=='Escape'||menu.hidden)return;closeLang(box);button.focus();
  });
}
function paint(node,text){
  node.textContent='';
  if(!terms.length){node.textContent=text;return}
  const low=text.toLocaleLowerCase();let at=0;
  for(;;){
    let best=-1,len=0;
    for(const term of terms){const hit=low.indexOf(term,at);
      if(hit>=0&&(best<0||hit<best)){best=hit;len=term.length}}
    if(best<0)break;
    if(best>at)node.appendChild(document.createTextNode(text.slice(at,best)));
    const m=document.createElement('mark');m.textContent=text.slice(best,best+len);
    node.appendChild(m);at=best+len;
  }
  if(at<text.length)node.appendChild(document.createTextNode(text.slice(at)));
}
function apply(){
  const cat=langPick.cat,read=langPick.read,media=langPick.media;
  const hits=rows.filter(row=>(!cat.length||cat.some(code=>row.cats.indexOf(code)>=0))
    &&(!read.length||read.some(code=>row.read.indexOf(code)>=0))
    &&media.every(code=>row.media.indexOf(code)>=0)
    &&terms.every(term=>row.hay.indexOf(term)>=0));
  hits.sort((x,y)=>order==='daily'?x.d-y.d:x.i-y.i);
  for(const row of rows)row.card.hidden=true;
  hits.forEach((row,index)=>{
    row.card.style.order=String(index);
    row.card.hidden=index>=shown;
    if(row.t)paint(row.t,row.tText);
    if(row.b)paint(row.b,row.bText);
  });
  if(status)status.textContent=hits.length+' '+(data.searchSuffix||'');
  if(emptyBox)emptyBox.hidden=hits.length>0;
  if(moreBtn)moreBtn.hidden=hits.length<=shown;
  const typed=Boolean(input&&input.value);
  if(clearBtn)clearBtn.hidden=!typed;
  const hint=root.querySelector('.exp-search kbd');
  if(hint)hint.hidden=typed;
}
function refilter(){shown=STEP;apply()}
if(input){
  input.addEventListener('input',()=>{
    terms=input.value.trim().toLocaleLowerCase().split(/\s+/u).filter(Boolean);
    refilter();
  });
}
for(const button of orders){
  button.addEventListener('click',()=>{
    order=button.getAttribute('data-order')||'latest';
    for(const other of orders)
      other.setAttribute('aria-pressed',other===button?'true':'false');
    refilter();
  });
}
if(moreBtn)moreBtn.addEventListener('click',()=>{
  shown+=STEP;apply();
  const next=Array.from(grid.querySelectorAll('.tcard:not([hidden])')).pop();
  if(next)next.querySelector('a').focus();
});
if(clearBtn)clearBtn.addEventListener('click',()=>{
  if(!input)return;input.value='';terms=[];refilter();input.focus();
});
document.addEventListener('keydown',event=>{
  if(!input)return;
  const tag=(event.target&&event.target.tagName||'').toLowerCase();
  if(event.key==='/'&&tag!=='input'&&tag!=='textarea'&&tag!=='select'){
    event.preventDefault();input.focus();input.select();return;
  }
  if(event.key==='Escape'&&document.activeElement===input&&input.value){
    input.value='';terms=[];refilter();
  }
});
apply();
})();
""".strip()


def render_home(
    records: Iterable[CatalogRecord],
    *,
    locale: str,
    metadata: SiteMetadata,
    build_date: date,
    url_mode: UrlMode = "root",
    home_path: str | None = None,
    canonical_url: str | None = None,
    alternate_urls: dict[str, str] | None = None,
    pivot_records: Mapping[str, CatalogRecord] | None = None,
) -> str:
    """Render one locale homepage from validated public-safe catalog rows only.

    ``pivot_records`` maps publication id to the same topic's English-pivot row; each
    card's search text carries those English words too, so English finds a topic on
    every homepage.  Omit it (or pass the English rows on the English page) for none.
    """

    canonical_locale = normalize_lang(locale)
    path = home_path or f"/{canonical_locale}/"
    rows = _catalog_rows(records, canonical_locale, metadata)
    strings = dict(site_strings(canonical_locale))
    # The tab, the bookmark and the shared link all read this one line, so the home page
    # states the name and what it is for; every other page states its own topic.
    page_title = f'{strings["site_name"]} — {strings["tagline"].rstrip("。.")}'

    latest = _newest_first(rows)
    daily_positions = {
        row.publication_id: index
        for index, row in enumerate(daily_catalog_order(rows, build_date))
    }

    lead_markup = ""
    if latest:
        lead_markup = (
            '<section class="section" id="latest">'
            f'<div class="shead"><h2>{_esc(strings["latest"])}</h2></div>'
            '<div class="lead-hold">'
            + _topic_card(
                latest[0],
                strings=strings,
                metadata=metadata,
                locale=canonical_locale,
                url_mode=url_mode,
                home_path=path,
                latest_index=0,
                daily_index=daily_positions[latest[0].publication_id],
                lead=True,
                pivot=(pivot_records or {}).get(latest[0].publication_id),
            )
            + "</div></section>"
        )

    explorer = _explorer(
        latest,
        metadata,
        canonical_locale,
        strings,
        url_mode=url_mode,
        home_path=path,
        build_date=build_date,
        daily_positions=daily_positions,
        pivot_records=pivot_records or {},
    )

    m2_head = ""
    style = f"{_STYLE}\n{ABOUT_CSS}\n{SUGGEST_CSS}"
    if canonical_url is not None:
        if not canonical_url.startswith("/"):
            raise ValueError("home canonical URL must be root-relative")
        alternates = alternate_urls or {}
        m2_head = f'<link rel="canonical" href="{_attr(canonical_url)}">' + "".join(
            f'<link rel="alternate" hreflang="{_attr(item_locale)}" href="{_attr(url)}">'
            for item_locale, url in sorted(alternates.items())
        )
        style = f"{_STYLE}\n{_M2_STYLE}\n{ABOUT_CSS}\n{SUGGEST_CSS}"

    return (
        "<!doctype html>\n"
        f'<html lang="{_attr(canonical_locale)}" dir="{_attr(locale_direction(canonical_locale))}" '
        f'data-search-empty="{_attr(strings["search_empty"])}" '
        f'data-search-suffix="{_attr(strings["search_count"])}" '
        f'data-page-step="{PAGE_STEP}"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(page_title)}</title>"
        f'<meta name="description" content="{_attr(strings["meta_description"])}">'
        f'<meta property="og:type" content="website">'
        f'<meta property="og:site_name" content="{_attr(strings["site_name"])}">'
        f'<meta property="og:title" content="{_attr(page_title)}">'
        f'<meta property="og:description" content="{_attr(strings["meta_description"])}">'
        f'<meta property="og:locale" content="{_attr(canonical_locale)}">'
        f'<meta name="twitter:card" content="summary">{m2_head}'
        f'<link rel="icon" type="image/svg+xml" href="{LOGO_URL}">'
        f"{_FONT_LINK}<style>{style}</style>"
        f"<script>{_HEAD_JS}</script></head><body>{_ICONS}"
        f'<a class="skip" href="#browse">{_esc(strings["skip_to_content"])}</a>'
        + _site_tools(
            metadata, canonical_locale, strings, url_mode=url_mode, home_path=path
        )
        + _masthead(strings, canonical_locale)
        + _method_band(strings)
        + f"<main>{lead_markup}{explorer}</main>"
        + _footer(strings, build_date=build_date)
        + f'<a class="top-fab" id="backtotop" href="#page-top" '
        f'aria-label="{_attr(strings["back_to_top"])}" '
        f'title="{_attr(strings["back_to_top"])}"><span aria-hidden="true">\u2191</span></a>'
        + about_modal_html(canonical_locale)
        + (suggest_modal_html(canonical_locale) if suggestion_entrance_enabled() else "")
        + f"<script>{_THEME_JS}</script><script>{_LANG_JS}</script>"
        f"<script>{_TOP_JS}</script>"
        f"<script>{_TAGLINE_JS if official_site() else ''}</script>"
        f"<script>{HOME_ABOUT_JS}</script>"
        f"<script>{suggestion_js(canonical_locale) if suggestion_entrance_enabled() else ''}</script>"
        f"<script>{_EXPLORER_JS}</script></body></html>\n"
    )
