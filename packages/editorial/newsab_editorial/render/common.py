"""Shared render primitives: badges, side tags, icons, JSON payload blocks."""

from __future__ import annotations

import json
from typing import Optional

from newsab_schema.models.corpus import TopicManifest
from newsab_schema.models.page import ReaderLexicon

from .strings import e, s, t

#: The inline sprite.  Every icon the page uses is here, so a preview opened offline
#: still carries its whole vocabulary.
ICONS = (
    '<svg width="0" height="0" style="position:absolute" aria-hidden="true">'
    # our record of one sentence
    '<symbol id="i-quote" viewBox="0 0 16 16">'
    '<path d="M3 12.5c0-3.6 1.6-6.2 4.6-7.6l.7 1.3C6.6 7 5.6 8.2 5.3 9.6h1.9v4.4H3z'
    'm7 0c0-3.6 1.6-6.2 4.6-7.6l.7 1.3c-1.7.8-2.7 2-3 3.4h1.9v4.4h-4.2z"'
    ' transform="translate(-1,-2)"/>'
    "</symbol>"
    # "supported": a struck stamp — solid ring, solid tick
    '<symbol id="i-supported" viewBox="0 0 20 20">'
    '<circle cx="10" cy="10" r="8" fill="currentColor"/>'
    '<path d="M6 10.2l2.6 2.6L14.2 7" fill="none" stroke="var(--panel)" stroke-width="2"'
    ' stroke-linecap="round" stroke-linejoin="round"/>'
    "</symbol>"
    # "weak": the same ring, drawn open, with a half-filled centre
    '<symbol id="i-weak" viewBox="0 0 20 20">'
    '<circle cx="10" cy="10" r="7.2" fill="none" stroke="currentColor" stroke-width="1.6"'
    ' stroke-dasharray="3 2.4"/>'
    '<path d="M10 4.6a5.4 5.4 0 0 0 0 10.8z" fill="currentColor"/>'
    "</symbol>"
    # the data view behind a question
    '<symbol id="i-table" viewBox="0 0 20 20">'
    '<rect x="2.5" y="3.5" width="15" height="13" rx="1.5" fill="none" stroke="currentColor"'
    ' stroke-width="1.4"/>'
    '<path d="M2.5 8h15M8 8v8.5M13 8v8.5" fill="none" stroke="currentColor"'
    ' stroke-width="1.2"/>'
    "</symbol>"
    # how the statistics judged it
    '<symbol id="i-stat" viewBox="0 0 20 20">'
    '<circle cx="6" cy="6" r="2.2" fill="none" stroke="currentColor" stroke-width="1.5"/>'
    '<circle cx="14" cy="14" r="2.2" fill="none" stroke="currentColor" stroke-width="1.5"/>'
    '<path d="M15.5 3.5l-11 13" fill="none" stroke="currentColor" stroke-width="1.7"'
    ' stroke-linecap="round"/>'
    "</symbol>"
    # the project's three core readings: meet / part / fade
    '<symbol id="i-consensus" viewBox="0 0 24 24">'
    '<path d="M2.5 12H8.5M15.5 12h6" fill="none" stroke="currentColor" stroke-width="1.8"'
    ' stroke-linecap="round"/><path d="M12 7l5 5-5 5-5-5z" fill="currentColor"/>'
    "</symbol>"
    '<symbol id="i-divergence" viewBox="0 0 24 24">'
    '<path d="M12 12C8.5 12 8.5 6 4.5 6h-2M12 12c3.5 0 3.5-6 7.5-6h2'
    'M12 12c-3.5 0-3.5 6-7.5 6h-2M12 12c3.5 0 3.5 6 7.5 6h2" fill="none"'
    ' stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
    '<circle cx="12" cy="12" r="1.8" fill="currentColor"/>'
    "</symbol>"
    '<symbol id="i-silence" viewBox="0 0 24 24">'
    '<path d="M2.5 12h7" fill="none" stroke="currentColor" stroke-width="1.8"'
    ' stroke-linecap="round"/><circle cx="11" cy="12" r="2.3" fill="currentColor"/>'
    '<circle cx="16" cy="12" r="1.5" fill="currentColor" opacity=".62"/>'
    '<circle cx="20.5" cy="12" r=".9" fill="currentColor" opacity=".32"/>'
    "</symbol>"
    # two sampled perspectives: one open, one solid, held in the same frame
    '<symbol id="i-perspectives" viewBox="0 0 24 24">'
    '<rect x="3.5" y="3.5" width="17" height="17" rx="3" fill="var(--panel)"/>'
    '<path d="M12 3.5h5.5a3 3 0 0 1 3 3v11a3 3 0 0 1-3 3H12'
    'c-3.5-2-3.5-6.5 0-8.5s3.5-6.5 0-8.5z" fill="currentColor"/>'
    '<circle cx="8.5" cy="8.5" r=".8" fill="currentColor"/>'
    '<circle cx="15.5" cy="15.5" r=".8" fill="var(--panel)"/>'
    '<rect x="3.5" y="3.5" width="17" height="17" rx="3" fill="none" stroke="currentColor"'
    ' stroke-width="1.5"/>'
    "</symbol>"
    # the three supporting sections
    '<symbol id="i-timeline" viewBox="0 0 24 24">'
    '<rect x="4" y="3.5" width="16" height="17" rx="2" fill="none" stroke="currentColor"'
    ' stroke-width="1.5"/><path d="M7 15l3.2-4 3.1 2.2L17 8" fill="none" stroke="currentColor"'
    ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
    "</symbol>"
    '<symbol id="i-appendix" viewBox="0 0 24 24">'
    '<rect x="4" y="3.5" width="16" height="17" rx="2" fill="none" stroke="currentColor"'
    ' stroke-width="1.5"/><path d="M8 8h8M8 12h8M8 16h5" fill="none" stroke="currentColor"'
    ' stroke-width="1.5" stroke-linecap="round"/>'
    "</symbol>"
    '<symbol id="i-cloud" viewBox="0 0 24 24">'
    '<rect x="4" y="3.5" width="16" height="17" rx="2" fill="none" stroke="currentColor"'
    ' stroke-width="1.5"/><circle cx="9" cy="10" r="2.3" fill="none" stroke="currentColor"'
    ' stroke-width="1.35"/><circle cx="15" cy="8" r="1.7" fill="none" stroke="currentColor"'
    ' stroke-width="1.35"/><circle cx="14.5" cy="15" r="3" fill="none" stroke="currentColor"'
    ' stroke-width="1.35"/><circle cx="8" cy="16" r="1" fill="currentColor"/>'
    "</symbol>"
    '<symbol id="i-search" viewBox="0 0 24 24">'
    '<rect x="4" y="3.5" width="16" height="17" rx="2" fill="none" stroke="currentColor"'
    ' stroke-width="1.5"/><circle cx="10.5" cy="10.5" r="3.6" fill="none"'
    ' stroke="currentColor" stroke-width="1.5"/><path d="M13.2 13.2l3.3 3.3" fill="none"'
    ' stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'
    "</symbol>"
    # the field's own clear control: a plain cross, drawn rather than left to the
    # browser, whose WebKit default is a colour emoji
    '<symbol id="i-close" viewBox="0 0 24 24">'
    '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11" fill="none" stroke="currentColor"'
    ' stroke-width="1.7" stroke-linecap="round"/>'
    "</symbol>"
    # the unframed search glyph inside the input field
    '<symbol id="i-search-plain" viewBox="0 0 24 24">'
    '<circle cx="10.5" cy="10.5" r="5.8" fill="none" stroke="currentColor"'
    ' stroke-width="1.6"/><path d="M14.8 14.8L20 20" fill="none" stroke="currentColor"'
    ' stroke-width="1.8" stroke-linecap="round"/>'
    "</symbol>"
    '<symbol id="i-help" viewBox="0 0 20 20">'
    '<path d="M7.6 6.4a2.6 2.6 0 1 1 3.55 2.45C10.25 9.27 10 9.75 10 11" fill="none"'
    ' stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>'
    '<circle cx="10" cy="14.2" r=".9" fill="currentColor"/>'
    "</symbol>"
    '<symbol id="i-caret" viewBox="0 0 20 20">'
    '<path d="M7.2 5.8l4.5 4.2-4.5 4.2" fill="none" stroke="currentColor" stroke-width="2"'
    ' stroke-linecap="round" stroke-linejoin="round"/>'
    "</symbol>"
    '<symbol id="i-expand-all" viewBox="0 0 20 20">'
    '<rect x="3" y="6" width="11" height="11" rx="1" fill="var(--panel)" stroke="currentColor"'
    ' stroke-width="1.3"/><path d="M6 3h11v11" fill="none" stroke="currentColor" stroke-width="1.3"/>'
    '<path d="M8.5 9v5M6 11.5h5" fill="none" stroke="currentColor" stroke-width="1.4"'
    ' stroke-linecap="round"/>'
    "</symbol>"
    '<symbol id="i-collapse-all" viewBox="0 0 20 20">'
    '<rect x="3" y="6" width="11" height="11" rx="1" fill="var(--panel)" stroke="currentColor"'
    ' stroke-width="1.3"/><path d="M6 3h11v11" fill="none" stroke="currentColor" stroke-width="1.3"/>'
    '<path d="M6 11.5h5" fill="none" stroke="currentColor" stroke-width="1.4"'
    ' stroke-linecap="round"/>'
    "</symbol>"
    '<symbol id="i-sun" viewBox="0 0 20 20">'
    '<circle cx="10" cy="10" r="3.2" fill="none" stroke="currentColor" stroke-width="1.6"/>'
    '<path d="M10 1.8v2M10 16.2v2M1.8 10h2M16.2 10h2M4.2 4.2l1.4 1.4M14.4 14.4l1.4 1.4M15.8 4.2l-1.4 1.4M5.6 14.4l-1.4 1.4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'
    "</symbol>"
    '<symbol id="i-moon" viewBox="0 0 20 20">'
    '<path d="M15.9 12.9A6.6 6.6 0 0 1 7.1 4.1a6.7 6.7 0 1 0 8.8 8.8z" fill="currentColor"/>'
    "</symbol>"
    "</svg>"
)


def pct(numerator: int, denominator: int) -> float:
    return 100 * numerator / denominator if denominator else 0.0


def json_block(element_id: str, payload: object) -> str:
    # JSON object order is not reader-visible and must not depend on the order in which
    # upstream dictionaries happened to be assembled.  Canonical key ordering keeps a
    # render byte-for-byte reproducible across processes as well as within one process.
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    return f'<script type="application/json" id="{element_id}">{body}</script>'


def badge(
    text: str,
    css: str = "",
    tip: str = "",
    *,
    href: str = "",
    attrs: str = "",
    lead: str = "",
) -> str:
    """One badge.  Every label on this page is one, and every badge explains itself.

    There is no separate ⓘ affordance: the page is consistent — a badge is always
    hoverable (and tappable) for the sentence behind it.
    """
    classes = f"badge {css}".strip()
    tipped = f' data-tip="{e(tip)}" tabindex="0"' if tip else ""
    if href:
        return f'<a class="{classes}" href="{e(href)}"{tipped}{attrs}>{lead}{e(text)}</a>'
    return f'<span class="{classes}"{tipped}{attrs}>{lead}{e(text)}</span>'


def icon_button(symbol: str, tip: str, *, attrs: str = "", css: str = "") -> str:
    """A square icon control — the page's one shape for "there is more behind this"."""
    return (
        f'<button class="iconbtn{(" " + css) if css else ""}" type="button" '
        f'data-tip="{e(tip)}"{attrs}>'
        f'<svg aria-hidden="true"><use href="#{symbol}"></use></svg></button>'
    )


def help_button(modal_id: str, label: str) -> str:
    """The shared circular ``?`` control for section-level explanations."""
    return (
        f'<button class="helpbtn" type="button" data-open="{e(modal_id)}" '
        f'aria-label="{e(label)}" title="{e(label)}">'
        '<svg aria-hidden="true"><use href="#i-help"></use></svg></button>'
    )


def section_title(symbol: str, text: str, *, tag: str = "h3") -> str:
    """A heading in the visual vocabulary shared by the page's three data sections."""
    return (
        f'<{tag} class="section-title"><svg aria-hidden="true">'
        f'<use href="#{e(symbol)}"></use></svg><span>{e(text)}</span></{tag}>'
    )


def group_text(
    lexicon: Optional[ReaderLexicon],
    attr: str,
    group_id: str,
    fallback,
    lang: str,
) -> str:
    """One group field, preferring ``lexicon.<attr>[group_id]`` over the manifest.

    ``fallback`` is the manifest's own :class:`MultiLangText` for this field (``label``,
    ``short_label`` or ``definition``). The manifest carries only the languages approved
    at touchpoint one (``TopicManifest.scope_hash()`` covers it, so a run cannot add a
    language there without invalidating that approval); a run that wants to speak more
    languages writes the extra translations into ``page.lexicon.group_labels`` /
    ``group_short_labels`` / ``group_definitions`` instead, and this is the one place
    every renderer of a group field reads through, so a run's own words always win when
    it has them and every caller degrades to the manifest the same way.
    """
    table = getattr(lexicon, attr, None) if lexicon is not None else None
    entry = table.get(group_id) if table else None
    if entry is not None:
        value = entry.get(lang)
        if value:
            return value
    return t(fallback, lang)


def group_meta(
    manifest: TopicManifest, lang: str, lexicon: Optional[ReaderLexicon] = None
) -> dict[str, dict]:
    """Everything the page may say about a side, keyed by ``group_id``.

    ``short`` is what the reader sees (the tag), ``label`` + ``definition`` are what the
    tag's tooltip says, and ``css`` fixes which side is drawn in which colour, from the
    manifest's own order — so a group is the same colour in the answer cards, the side
    blocks and every chart on the page. ``lexicon`` (``page.lexicon``, when the caller has
    a page) supplies languages the manifest itself does not carry; see ``group_text``.
    """
    meta: dict[str, dict] = {}
    for css, group in zip(("a", "b"), manifest.groups):
        label = group_text(lexicon, "group_labels", group.group_id, group.label, lang)
        short_fallback = group.short_label if group.short_label else group.label
        short = group_text(
            lexicon, "group_short_labels", group.group_id, short_fallback, lang
        )
        definition = group_text(
            lexicon, "group_definitions", group.group_id, group.definition, lang
        )
        meta[group.group_id] = {
            "label": label,
            "short": short,
            "definition": definition,
            "css": css,
        }
    return meta


def gtag(group_id: str, groups: dict[str, dict], lang: str, css_extra: str = "") -> str:
    """The side's name, everywhere: a badge whose tooltip carries the group definition."""
    meta = groups.get(group_id)
    if meta is None:
        return badge(group_id, "gtag")
    return badge(
        meta["short"],
        f"gtag {meta['css']} {css_extra}".strip(),
        f"{meta['label']} — {meta['definition']}",
    )


def short(group_id: str, groups: dict[str, dict]) -> str:
    meta = groups.get(group_id)
    return meta["short"] if meta else group_id


def css_of(group_id: str, groups: dict[str, dict]) -> str:
    meta = groups.get(group_id)
    return meta["css"] if meta else "a"


def ordered_ids(groups: dict[str, dict]) -> list[str]:
    """The two group ids in the manifest's own order — left side first, always."""
    return sorted(groups, key=lambda gid: groups[gid]["css"])


def unit_label(badge_label, lang: str) -> str:
    return t(badge_label, lang) if badge_label else s("of_clusters", lang)


def cluster_chip(cluster_id: str, count: Optional[int], lang: str) -> str:
    """A reporting cluster id, clickable into the cluster it names.

    Every place a cluster id appears is a place a reader may ask "what *is* that report?" —
    the annotation table, the sentence card, the article card.
    """
    count_label = "cluster_article" if count == 1 else "cluster_articles"
    label = (
        cluster_id
        if count is None
        else f"{cluster_id} · {s(count_label, lang).format(n=count)}"
    )
    return (
        f'<button class="clusterid" type="button" data-cluster="{e(cluster_id)}" '
        f'title="{e(s("cluster_tip", lang))}">{e(label)}</button>'
    )


def reader_question(page, question_id: str, fallback, lang: str) -> str:
    """The question as a reader meets it: the lexicon first, annotation wording last."""
    entry = page.lexicon.questions.get(question_id) if page.lexicon else None
    if entry is not None and (entry.get(lang) or entry.get("en")):
        return t(entry, lang)
    if fallback is None:
        return question_id
    if isinstance(fallback, dict):
        return fallback.get(lang) or fallback.get("en") or question_id
    return t(fallback, lang)


def category_label(page, category: str, lang: str) -> str:
    """A counting key in reader words — ``unclear`` included, raw key as the last resort."""
    entry = page.lexicon.categories.get(category) if page.lexicon else None
    if entry is not None and (entry.get(lang) or entry.get("en")):
        return t(entry, lang)
    return category.replace("_", " ")


def topic_label(page, pivot: str, lang: str) -> str:
    """A collect-stage English pivot in reader language, never a source-phrase lookup."""
    entry = page.lexicon.topics.get(pivot) if page.lexicon else None
    if entry is not None and (entry.get(lang) or entry.get("en")):
        return t(entry, lang)
    return pivot


def scope_text(page, phrase: str, lang: str) -> str:
    """A manifest scope bullet in the reader's language.

    The manifest is hashed into every topic's ``scope_approval``, so it cannot grow a
    translation field without invalidating five signed-off topics.  The reader wording
    therefore lives in the page's lexicon, keyed by the English original, and a missing
    entry degrades to that original rather than fabricating one.
    """
    entry = page.lexicon.scope.get(phrase) if page.lexicon else None
    if entry is not None and (entry.get(lang) or entry.get("en")):
        return t(entry, lang)
    return phrase
