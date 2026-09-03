"""Verbatim quotes and the controls that open our record of them.

Quotes carry the controls that act on them: a compact original/translation toggle when a
translation exists, and a text button opening our record of the original sentence.
"""

from __future__ import annotations

from typing import Optional

from ..evidence import EvidenceItem, SentenceIndex
from .common import badge, cluster_chip, css_of, short
from .strings import (
    BEAT_SCOPE,
    COUNTRY_LABEL,
    LANG_LABEL,
    SOURCE_CATEGORY,
    e,
    pick,
    s,
    t,
)


def quote_button(sentence_id: str, lang: str) -> str:
    return (
        f'<button class="qbtn" type="button" data-sid="{e(sentence_id)}" '
        f'title="{e(s("quote_tip", lang))}">{e(s("quote_source", lang))}</button>'
    )


def quote_controls(sentence_id: str, translated: bool, lang: str) -> str:
    toggle = (
        f'<button class="qbtn tr" type="button" data-tr-toggle '
        f'title="{e(s("toggle_tr", lang))}">{e(s("tr_translated", lang))}</button>'
        if translated else ""
    )
    return f"{toggle}{quote_button(sentence_id, lang)}"


def evidence_html(item: EvidenceItem, index: SentenceIndex, lang: str) -> str:
    card = index.card(item.sentence_id)
    if card is None:
        return ""
    if not index.allow(item.sentence_id):
        return f"<blockquote>{_withheld_chip(item.sentence_id, lang)}</blockquote>"
    localized = ""
    if item.translation:
        candidate = item.translation.get(lang)
        if candidate and card.lang.split("-")[0] != lang.split("-")[0]:
            localized = candidate
    original = f'<span class="q{" has-tr" if localized else ""}">{e(card.text)}</span>'
    translation = f'<span class="tx">{e(localized)}</span>' if localized else ""
    return (
        f"<blockquote>{original}{translation}"
        f" {quote_controls(item.sentence_id, bool(localized), lang)}</blockquote>"
    )


def anchor_chip(sentence_id: str, index: SentenceIndex, lang: str) -> str:
    """A clickable anchor, or — once this article's display budget is spent — its address.

    An anchor whose text is withheld is still stated: the reader sees which sentence of
    which article the annotation rests on and can go read it at the publisher.
    """
    if index.card(sentence_id) is None:
        return ""
    position = sentence_id.split(":", 1)[1]
    if index.allow(sentence_id):
        return (
            f'<button class="qbtn" type="button" data-sid="{e(sentence_id)}" '
            f'title="{e(s("quote_tip", lang))}">{e(position)}</button> '
        )
    return _withheld_chip(sentence_id, lang) + " "


def _withheld_chip(sentence_id: str, lang: str) -> str:
    return (
        f'<span class="badge off" data-tip="{e(s("withheld", lang))}" tabindex="0">'
        f"{e(sentence_id)}</span>"
    )


def media_button(source_id: str, source_name: str, index: SentenceIndex, lang: str) -> str:
    """An outlet's name, clickable into what we know about that outlet."""
    if not source_id or source_id not in index.sources:
        return e(source_name)
    index.used_sources.add(source_id)
    return (
        f'<button class="media" type="button" data-media="{e(source_id)}" '
        f'title="{e(s("media_tip", lang))}">{e(source_name)}</button>'
    )


def media_payload(index: SentenceIndex, lang: str) -> dict:
    """The media cards behind every outlet the page named, in the reader's language."""
    out: dict[str, dict] = {}
    for source_id in sorted(index.used_sources):
        source = index.sources.get(source_id)
        if source is None:
            continue
        out[source_id] = {
            "name": t(source.name, lang),
            "country": pick(COUNTRY_LABEL, source.country, lang),
            "lang": pick(LANG_LABEL, source.lang, lang),
            "category": pick(SOURCE_CATEGORY, source.category.value, lang),
            "beat_scope": pick(BEAT_SCOPE, source.beat_scope, lang),
            "notes": t(source.notes, lang),
            "url": source.url,
        }
    return out


def _evidence_table(items: list[EvidenceItem], index: SentenceIndex, lang: str) -> str:
    rows = []
    for item in items:
        card = index.card(item.sentence_id)
        if card is None:
            continue
        allowed = index.allow(item.sentence_id)
        candidate = (item.translation or {}).get(lang) if allowed else None
        localized = candidate if candidate and card.lang.split("-")[0] != lang.split("-")[0] else ""
        if allowed:
            quote = f'<span class="q{" has-tr" if localized else ""}">{e(card.text)}</span>'
            if localized:
                quote += f'<span class="tx">{e(localized)}</span> '
                quote += (
                    f'<button class="qbtn tr" type="button" data-tr-toggle '
                    f'title="{e(s("toggle_tr", lang))}">{e(s("tr_translated", lang))}</button>'
                )
            anchor = anchor_chip(item.sentence_id, index, lang)
        else:
            quote = _withheld_chip(item.sentence_id, lang)
            anchor = e(item.sentence_id.split(":", 1)[1])
        report = f"{media_button(card.source_id, card.source_name, index, lang)}<br>{e(card.publish_date)}"
        rows.append(
            f'<tr><td class="meta">{report}</td><td>{quote}</td>'
            f'<td class="anchors">{anchor}</td></tr>'
        )
    head = (
        '<colgroup><col class="meta"><col><col class="anchors"></colgroup><thead><tr>'
        f'<th>{e(s("evidence_report", lang))}</th>'
        f'<th>{e(s("evidence_quote", lang))}</th>'
        f'<th>{e(s("quote_source", lang))}</th></tr></thead>'
    )
    return f'<div class="ann-scroll"><table class="ann evtable">{head}<tbody>{"".join(rows)}</tbody></table></div>'


def evidence_modal(modal_id: str, heading: str, question: str, sides, groups, index, lang: str) -> str:
    """One angle's counted reports, in a two-side tabbed sentence-level table."""
    tabs, panels = [], []
    answers = []
    for position, (group_id, items, numerator, denominator, answer) in enumerate(sides):
        css = css_of(group_id, groups)
        answers.append(answer)
        tabs.append(
            f'<button type="button" class="{css}{" on" if position == 0 else ""}" '
            f'data-tab="{e(group_id)}" data-answer="{e(answer)}">'
            f'{e(short(group_id, groups))} '
            f'{numerator}/{denominator}</button>'
        )
        panels.append(
            f'<div class="tabpanel" data-panel="{e(group_id)}"'
            f'{"" if position == 0 else " hidden"}>{_evidence_table(items, index, lang)}</div>'
        )
    if not panels:
        return ""
    return (
        f'<div class="modal" id="{e(modal_id)}" hidden>'
        '<div class="modal-backdrop" data-close></div>'
        '<div class="modal-card wide" role="dialog" aria-modal="true">'
        f'<button class="modal-x" type="button" data-close '
        f'aria-label="{e(s("modal_close", lang))}">&times;</button>'
        f'<div class="modal-meta"><span class="qm">Q:</span> {e(question)}</div>'
        f'<h4 data-evidence-heading data-template="{e(heading)}">'
        f'{e(heading.format(answer=answers[0]))}</h4>'
        f'<div class="tabs">{"".join(tabs)}</div>'
        f'{"".join(panels)}</div></div>'
    )
