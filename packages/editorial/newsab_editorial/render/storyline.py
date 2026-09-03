"""The storyline: three tabs, two answer cards, and the relation between them.

This is the page.  Everything above it is background and
everything below it is apparatus; a reader who shares this page shares these cards.

Three changes this round carry the weight:

* the three angle kinds became **tabs with their counts** — a reader sees at a glance
  that a topic produced five agreements and no divergence at all, which on some topics is
  the loudest thing the data has to say.  A kind with no angle keeps its tab and states
  its zero honestly rather than disappearing;
* every angle now draws **two answer cards with a relation between them** — agreement,
  divergence, silence — instead of one wide card for agreement and two for the rest.  The
  relation is the finding, so the relation is what is drawn;
* the counted detail (the side tag and compact ``X/Y`` badge) moved **into the card it
  supports**.  A separate upper-right control opens every supporting report. What is left
  below the cards is the writer's two explanations and nothing else.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Optional

from newsab_schema.models.page import AngleBlock, PageClaim, ReaderPage, SideAnswerBlock

from ..evidence import AnswerIndex, EvidenceItem, SentenceIndex, badge_selector, side_evidence
from .common import (
    badge,
    css_of,
    gtag,
    icon_button,
    ordered_ids,
    reader_question,
    section_title,
)
from .evidence_view import evidence_modal
from .stats import TIP_FALLBACK, strength_label_tip
from .strings import KIND_EMPTY, KIND_LABEL, KIND_TIP, e, pick, s, t

#: Tab order.  Agreement first because it is the least expected of the three and the one
#: a reader most often does not believe until they see the counts.
KIND_ORDER = ("consensus", "divergence", "attention_gap")


# --------------------------------------------------------------------------------------
# the relation between the two cards
# --------------------------------------------------------------------------------------


_KIND_SYMBOL = {
    "consensus": "i-consensus",
    "divergence": "i-divergence",
    "attention_gap": "i-silence",
}


def _kind_icon(kind: str, css: str = "") -> str:
    symbol = _KIND_SYMBOL.get(kind, "i-silence")
    return (
        f'<svg class="kindicon{(" " + css) if css else ""}" aria-hidden="true">'
        f'<use href="#{symbol}"></use></svg>'
    )


def _relation_svg(
    kind: str,
    silent_css: Optional[str],
    strength: Optional[str],
    stability: Optional[float],
    thresholds: dict,
    lang: str,
) -> str:
    """The middle column of the angle: what the two answers are to each other.

    Drawn rather than labelled.  A reader scanning the storyline should be able to tell
    an agreement from a divergence from a silence without reading a word.
    """
    left = "muted" if kind == "attention_gap" and silent_css == "a" else "la"
    right = "muted" if kind == "attention_gap" and silent_css == "b" else "lb"
    dash_left = ' stroke-dasharray="2 4"' if left == "muted" else ""
    dash_right = ' stroke-dasharray="2 4"' if right == "muted" else ""
    leads = (
        '<svg class="rel-leads" viewBox="0 0 56 40" aria-hidden="true" fill="none" '
        'stroke-linecap="round">'
        f'<path class="{left}" d="M0 20H12" stroke-width="2"{dash_left}/>'
        f'<path class="{right}" d="M44 20H56" stroke-width="2"{dash_right}/></svg>'
    )
    strength_css = strength if strength in ("supported", "weak") else "unrated"
    tip = (
        strength_label_tip(
            strength,
            stability,
            thresholds,
            lang,
            conclusion=pick(KIND_LABEL, kind, lang),
        )
        if strength in ("supported", "weak")
        else ""
    )
    tipped = f' data-tip="{e(tip)}" tabindex="0"' if tip else ""
    flip = " flip" if kind == "attention_gap" and silent_css == "a" else ""
    mark = (
        f'<span class="relmark {e(kind)} {strength_css}"{tipped}>'
        f'{_kind_icon(kind, flip.strip())}</span>'
    )
    return f'<div class="rel">{leads}{mark}</div>'


# --------------------------------------------------------------------------------------
# one angle
# --------------------------------------------------------------------------------------


def _badge_tip(side: SideAnswerBlock, lang: str, clusters_total: Optional[int] = None) -> str:
    # A top_category badge counts x of the answering reports; with the finding at hand
    # the tip states the whole chain — collected → answered → gave this answer (P12).
    if badge_selector(side) == "top_category":
        if clusters_total is not None:
            return s("badge_tip_top_full", lang).format(
                numerator=side.badge.numerator,
                denominator=side.badge.denominator,
                total=clusters_total,
            )
        return s("badge_tip_top", lang).format(
            numerator=side.badge.numerator, denominator=side.badge.denominator
        )
    return s("badge_tip_addressed", lang).format(
        numerator=side.badge.numerator, denominator=side.badge.denominator
    )


def _answer_text(angle: AngleBlock, side: SideAnswerBlock, lang: str) -> str:
    if side.is_silent_side:
        # One wording for both shapes of silence — total, or a mention or two.  The
        # counts stay on the badge beside it.
        return s("silent_answer", lang)
    if angle.shared_answer_label is not None:
        return t(angle.shared_answer_label, lang)
    return t(side.answer_label, lang) if side.answer_label else ""


def _answer_card(
    angle: AngleBlock,
    side: SideAnswerBlock,
    groups: dict[str, dict],
    lang: str,
    *,
    clusters_total: Optional[int],
    evidence_id: str,
) -> str:
    css = css_of(side.group_id, groups)
    count = f"{side.badge.numerator}/{side.badge.denominator}"
    tip = _badge_tip(side, lang, clusters_total)
    answer = _answer_text(angle, side, lang)
    counter = badge(count, "count", tip)
    if evidence_id:
        evidence_label = (
            s("evidence_title_silent", lang)
            if side.is_silent_side
            else s("evidence_title", lang).format(answer=answer)
        )
        evidence_button = icon_button(
            "i-table", evidence_label,
            attrs=f' data-open="{e(evidence_id)}" data-open-tab="{e(side.group_id)}"',
        )
    else:
        evidence_button = ""
    evidence_control = f'<span class="acontrol">{counter}{evidence_button}</span>'
    silent = " silent" if side.is_silent_side else ""
    return (
        f'<div class="acard {css}{silent}">'
        f'{evidence_control}<div class="ahead">{gtag(side.group_id, groups, lang)}</div>'
        f'<div class="alabel">{e(answer)}</div></div>'
    )


#: A writer's inline footnote marker, ``[^1]``, tying a point in the prose to one of the
#: angle's notes.  Markdown's own syntax, chosen so it cannot collide with anything this
#: prose says: bracketed digits do occur in reader text, ``[^`` followed by digits does not.
_FOOTNOTE_MARK = re.compile(r"\[\^(\d{1,2})\]")


def _note_items(angle: AngleBlock, lang: str) -> list[tuple[str, str]]:
    """Return this angle's writer notes in the order used by ``[^n]`` markers."""
    notes: list[tuple[str, str]] = []
    if angle.caveat is not None:
        notes.append((s("caveat_label", lang), t(angle.caveat, lang)))
    notes.extend((s("detail_label", lang), t(claim.text, lang)) for claim in angle.detail)
    return notes


def _mark_footnotes(
    text: str,
    notes: list[tuple[str, str]],
    page_numbers: Iterator[int],
) -> str:
    """Turn ``[^1]`` into a superscript bubble trigger, escaped text in hand.

    A marker with no note behind it is dropped rather than rendered: a superscript that
    points nowhere is worse than the sentence without it.  The source marker remains
    angle-local for authoring, while its displayed number is allocated per occurrence
    across the whole page.  Two perspectives can therefore point to the same note without
    showing two confusing ``[1]`` controls.
    """
    def render(match: "re.Match[str]") -> str:
        local_index = int(match.group(1))
        if not 1 <= local_index <= len(notes):
            return ""
        display_index = next(page_numbers)
        label, note = notes[local_index - 1]
        tip = f"{label} [{display_index}] · {note}"
        return (
            f'<button class="fnref" type="button" data-tip="{e(tip)}" '
            f'aria-label="{e(tip)}">[{display_index}]</button>'
        )

    return _FOOTNOTE_MARK.sub(render, text)


def _commentary(
    angle: AngleBlock,
    groups: dict[str, dict],
    lang: str,
    footnote_numbers: Iterator[int],
) -> str:
    """The writer's paragraphs, tight under the cards they explain.

    One column per side normally; one full-width column when the writer judged the angle
    is better explained once for both sides (``commentary_joint``) — an explanation of
    where a divergence comes from is usually one thought, not two.
    """
    notes = _note_items(angle, lang)
    mark = lambda text: _mark_footnotes(e(text), notes, footnote_numbers)  # noqa: E731
    joint = getattr(angle, "commentary_joint", None)
    if joint is not None:
        return f'<div class="comm joint"><p>{mark(t(joint.text, lang))}</p></div>'
    columns = []
    # The cards above are drawn in the manifest's group order (`angle_html`, and see
    # qcard.py: "left side first, always").  These paragraphs sit directly under those
    # cards, so they must be ordered the same way — `angle.sides` is stored in whatever
    # order the writing stage built it, and when the two orders differ every angle on the
    # page shows each side's explanation under the OTHER side's card.  No check can see
    # it: the page data pairs correctly, and only a human reading the render catches it.
    order = ordered_ids(groups)
    for side in sorted(
        angle.sides,
        key=lambda s: order.index(s.group_id) if s.group_id in order else 9,
    ):
        css = css_of(side.group_id, groups)
        quiet = " class=\"silent\"" if side.is_silent_side else ""
        columns.append(
            f'<p{quiet}><span class="cmark {css}"></span>'
            f"{mark(t(side.answer.text, lang))}</p>"
        )
    return f'<div class="comm">{"".join(columns)}</div>'


def footnote_numbering(angles: list[AngleBlock], lang: str) -> dict[int, Iterator[int]]:
    """Allocate display numbers in the order the tabbed storyline reaches the DOM.

    The page stores angles in editorial rank order, while :func:`storyline` groups them by
    consensus/divergence/silence tabs.  Allocate after applying that tab order so the
    unique page-wide numbers also read upwards within the rendered document.
    """
    next_number = 1
    allocated: dict[int, Iterator[int]] = {}
    for kind in KIND_ORDER:
        for angle in angles:
            if angle.kind.value != kind:
                continue
            note_count = len(_note_items(angle, lang))
            prose = (
                [t(angle.commentary_joint.text, lang)]
                if angle.commentary_joint is not None
                else [t(side.answer.text, lang) for side in angle.sides]
            )
            visible = sum(
                1
                for text in prose
                for match in _FOOTNOTE_MARK.finditer(text)
                if 1 <= int(match.group(1)) <= note_count
            )
            allocated[angle.rank] = iter(range(next_number, next_number + visible))
            next_number += visible
    return allocated


def angle_html(
    page: ReaderPage,
    angle: AngleBlock,
    groups: dict[str, dict],
    finding,
    answers: Optional[AnswerIndex],
    index: SentenceIndex,
    question_block: str,
    thresholds: dict,
    lang: str,
    footnote_numbers: Iterator[int],
    *,
    share_url: Optional[str] = None,
    share_landing_url: Optional[str] = None,
    share_label: str = "",
) -> tuple[str, str]:
    """One angle card, plus the evidence modal its two evidence controls open."""
    totals_by_group = {g.group_id: g.clusters_total for g in finding.groups} if finding else {}
    order = ordered_ids(groups)
    sides = sorted(
        angle.sides,
        key=lambda side: order.index(side.group_id) if side.group_id in order else 9,
    )
    cards: list[str] = []
    evidence_sides = []
    silent_css = next(
        (css_of(side.group_id, groups) for side in sides if side.is_silent_side), None
    )
    for side in sides:
        if answers is not None:
            items = side_evidence(side, angle, finding, answers, index)
        else:
            items = [
                EvidenceItem(
                    cluster_id=index.cluster_of(q.sentence_id) or "",
                    sentence_id=q.sentence_id,
                    writer_pick=True,
                    translation=dict(q.translation.values) if q.translation else None,
                )
                for q in side.quotes
            ]
        evidence_id = f"ev-{angle.rank}"
        evidence_sides.append(
            (
                side.group_id,
                items,
                side.badge.numerator,
                side.badge.denominator,
                _answer_text(angle, side, lang),
            )
        )
        cards.append(
            _answer_card(
                angle,
                side,
                groups,
                lang,
                clusters_total=totals_by_group.get(side.group_id),
                evidence_id=evidence_id if items else "",
            )
        )
    head_badges = ""
    if finding is not None and any(group.top_category_tied for group in finding.groups):
        head_badges = badge(s("tied_label", lang), "soft", s("tied_tip", lang))
    data = ""
    if question_block:
        data = (
            f'<details class="qdata"><summary>{e(s("annotations", lang))}</summary>'
            f"{question_block}</details>"
        )
    question = reader_question(page, angle.question_id, angle.question_display, lang)
    modal = evidence_modal(
        f"ev-{angle.rank}", s("evidence_title", lang), question,
        evidence_sides, groups, index, lang,
    )
    share = ""
    if share_url and share_label:
        share = (
            f'<button class="angle-share" type="button" data-share-angle="{e(angle.question_id)}" '
            f'data-share-url="{e(share_url)}" data-share-landing="{e(share_landing_url or share_url)}" '
            f'aria-label="{e(share_label)}">'
            '<svg viewBox="0 0 20 20" aria-hidden="true" fill="none" stroke="currentColor" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
            '<circle cx="5" cy="10" r="2.2"/><circle cx="15" cy="5" r="2.2"/>'
            '<circle cx="15" cy="15" r="2.2"/><path d="M7 9l5.8-3M7 11l5.8 3"/></svg>'
            f'<span>{e(share_label)}</span></button>'
        )
    body = (
        # Editorial rank may change between revisions.  The question identity does not,
        # so public fragments and the links readers share are pinned to the question.
        f'<article class="angle" id="angle-{e(angle.question_id)}">'
        f'<div class="angle-top"><span class="left">{head_badges}</span>{share}</div>'
        f'<h2><span class="qm">Q:</span><span>{e(question)}</span></h2>'
        f'<div class="duo">{cards[0]}'
        f"{_relation_svg(angle.kind.value, silent_css, finding.strength.value if finding else None, finding.stability if finding else None, thresholds, lang)}"
        f"{cards[1] if len(cards) > 1 else ''}</div>"
        f"{_commentary(angle, groups, lang, footnote_numbers)}{data}</article>"
    )
    return body, modal


# --------------------------------------------------------------------------------------
# the three tabs
# --------------------------------------------------------------------------------------


def storyline(
    rendered: list[tuple[str, str]], thresholds: dict, lang: str, *, accessible_tabs: bool = False
) -> str:
    """Group the rendered angles into their three tabs, counts and empty states included.

    ``rendered`` is ``(kind, html)`` in rank order.  The tab a reader lands on is the one
    holding the highest-ranked angle — usually a divergence, but never assumed to be.

    The kind's explanation rides on the tab, where the kind badge used to be: a tab cannot
    also be a click target for its own tooltip, so it explains itself on hover and tap
    while the click switches tabs.
    """
    by_kind: dict[str, list[str]] = {kind: [] for kind in KIND_ORDER}
    default = KIND_ORDER[0]
    for position, (kind, html) in enumerate(rendered):
        by_kind.setdefault(kind, []).append(html)
        if position == 0:
            default = kind
    tabs, panels = [], []
    for kind in KIND_ORDER:
        entries = by_kind.get(kind) or []
        classes = " ".join(
            part for part in ("on" if kind == default else "", "zero" if not entries else "")
            if part
        )
        tip = pick(KIND_TIP, kind, lang).format(**{**TIP_FALLBACK, **thresholds})
        tab_links = (
            f' id="story-tab-{kind}" aria-controls="story-panel-{kind}" '
            f'tabindex="{0 if kind == default else -1}"'
            if accessible_tabs
            else ""
        )
        tabs.append(
            f'<button type="button" role="tab" class="{classes}" '
            f'aria-selected="{"true" if kind == default else "false"}" '
            f'data-tip="{e(tip)}" data-kindtab="{kind}"{tab_links}>{_kind_icon(kind)}'
            f'<span>{e(pick(KIND_LABEL, kind, lang))}</span>'
            f'<span class="n">({len(entries)})</span></button>'
        )
        inner = "".join(entries) or (
            f'<p class="story-empty">{e(pick(KIND_EMPTY, kind, lang))}</p>'
        )
        panel_links = (
            f' id="story-panel-{kind}" aria-labelledby="story-tab-{kind}" tabindex="0"'
            if accessible_tabs
            else ""
        )
        panels.append(
            f'<div data-kindpanel="{kind}" role="tabpanel"{panel_links}'
            f'{"" if kind == default else " hidden"}>{inner}</div>'
        )
    return (
        f'<section class="storyline">'
        f'<div class="panel-head story-head">'
        f'{section_title("i-perspectives", s("perspectives_title", lang), tag="h2")}'
        f'</div>'
        f'<div class="story-tabs" role="tablist">{"".join(tabs)}</div>'
        f'{"".join(panels)}</section>'
    )
