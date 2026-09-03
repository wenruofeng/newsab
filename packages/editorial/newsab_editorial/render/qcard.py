"""The question data card — one shape, used in the storyline and in the appendix.

The storyline's folded "detailed data" and the appendix share the same numbers. The
appendix's collapsed row owns rank/kind/strength/featured metadata; expanding it does not
print those badges a second time.

The card is: the badge row (rank, kind, strength, tier, provenance flags) with two icon
controls on the right — the annotation table and the statistics panel — then both sides'
rates, then the butterfly of answer shares.  The two long things it used to print inline
(the raw statistics line, the annotation table) are now behind those icons.
"""

from __future__ import annotations

from typing import Optional

from .common import (
    badge,
    category_label,
    cluster_chip,
    css_of,
    icon_button,
    ordered_ids,
    reader_question,
    short,
)
from .evidence_view import anchor_chip, media_button
from .stats import NO_ASSERTION, kind_chip, stat_paragraphs, strength_chip
from .strings import STRINGS, TIER_LABEL, TIER_TIP, e, pick, s


def quiet_group_id(row, groups: dict[str, dict]) -> Optional[str]:
    """The side a silence finding calls quiet — ``None`` when the question has no gap."""
    if not row.attention_gap:
        return None
    ids = ordered_ids(groups)
    if row.quiet_group in ids:
        return row.quiet_group

    def rate(group_id: str) -> float:
        group = next((g for g in row.groups if g.group_id == group_id), None)
        if group is None or not group.clusters_total:
            return 0.0
        return group.clusters_addressed / group.clusters_total

    return min(ids, key=rate) if ids else None


def card_kinds(row) -> tuple[list[str], Optional[str], Optional[float]]:
    """The one kind a question is, and the strength that stands beside it.

    One question, one angle.  **Silence outranks everything**:
    a gap says one side barely answered, and an answer rate that low is exactly the
    reason not to compare that side's leading answer with anything — so a consensus or
    divergence read off it is not a second finding, it is a claim the gap has already
    withdrawn.  "No clear pattern" and "insufficient data" lose to it for the same
    reason from the other direction: they say *we assert nothing here*, and printing
    them beside a silence told a reader both that nothing was found and that something
    was.
    """
    gap = row.attention_gap or {}
    if gap:
        return ["attention_gap"], gap.get("strength"), gap.get("stability")
    strength = row.strength if row.kind not in NO_ASSERTION else None
    return [row.kind], strength, row.stability if strength else None


def _ordered_groups(row, groups: dict[str, dict]) -> list:
    """The question's two sides in the manifest's order — left side first, always."""
    by_id = {group.group_id: group for group in row.groups}
    return [by_id.get(gid) for gid in ordered_ids(groups)]


def _qtext(text: str, tag: str = "div", extra: str = ' class="qtext"') -> str:
    return f'<{tag}{extra}><span class="qm">Q:</span>{e(text)}</{tag}>'


def rates(row, groups: dict[str, dict], lang: str) -> str:
    """How often each side takes the question up at all, on the chart's own axis.

    Deliberately a fraction and not a percentage: the numerator here is the *denominator*
    of every share in the chart below, and two percentages in a column invite the reader
    to read one as the other.
    """
    left, right = (_ordered_groups(row, groups) + [None, None])[:2]

    def rate(group) -> str:
        if group is None:
            return ""
        return badge(
            s("rate_label", lang).format(
                addressed=group.clusters_addressed, total=group.clusters_total
            ),
            "count",
            s("rate_tip", lang).format(
                total=group.clusters_total, addressed=group.clusters_addressed
            ),
        )

    from .common import gtag

    left_cell = f'{rate(left)}{gtag(left.group_id, groups, lang, "tipleft")}' if left else ""
    right_cell = f'{gtag(right.group_id, groups, lang, "tipright")}{rate(right)}' if right else ""
    return (
        f'<div class="axis3 rates"><span class="bf-left">{left_cell}</span>'
        f'<span class="cat"></span>'
        f'<span class="bf-right">{right_cell}</span></div>'
    )


#: The bar never spans its whole half — the count lives just past its outer end, and
#: needs somewhere to live.  Every bar is scaled by the same factor, so the axis stays true.
_BAR_SPAN = 86.0


def _half_bar(count: int, share: float, css: str, *, lead: bool = False, quiet: bool = False) -> str:
    if count <= 0:
        return ""
    width = max(share * _BAR_SPAN, 1.2)
    # The silent side of a gap is drawn in grey here for the same reason its answer card
    # is: a bar in the side's own colour claims a distribution, and one or two clusters
    # out of twenty-three is not one.
    classes = f'bar {css}{" lead" if lead else ""}{" quiet" if quiet else ""}'
    return f'<span class="{classes}" style="width:{width:.1f}%"></span>'


def _count_text(count: int, share: float) -> str:
    if count <= 0:
        return ""
    return f'<span class="bn">{count} · {share * 100:.0f}%</span>'


def butterfly(page, row, groups: dict[str, dict], lang: str) -> str:
    """Both sides' answer distributions sharing one centred axis of answers.

    Same left/right geometry as the two answer cards above, so a reader reads the page
    one way only; ordered by the two shares added together, which puts the answer both
    sides lead with first.
    """
    left, right = (_ordered_groups(row, groups) + [None, None])[:2]
    quiet_id = quiet_group_id(row, groups)

    def share(group, category: str) -> tuple[int, float]:
        if group is None or not group.clusters_addressed:
            return 0, 0.0
        count = group.category_counts.get(category, 0)
        return count, count / group.clusters_addressed

    categories = sorted(
        {c for group in (left, right) if group for c in group.category_counts},
        key=lambda c: (-(share(left, c)[1] + share(right, c)[1]), c),
    )
    rows = []
    for category in categories:
        count_l, share_l = share(left, category)
        count_r, share_r = share(right, category)
        top_l = bool(left and category in left.top_categories)
        top_r = bool(right and category in right.top_categories)
        rows.append(
            f'<div class="axis3{" top" if top_l or top_r else ""}">'
            f'<span class="bf-left">{_count_text(count_l, share_l)}'
            f'{_half_bar(count_l, share_l, "a", lead=top_l, quiet=bool(left and left.group_id == quiet_id))}</span>'
            f'<span class="cat">{e(category_label(page, category, lang))}</span>'
            f'<span class="bf-right">{_half_bar(count_r, share_r, "b", lead=top_r, quiet=bool(right and right.group_id == quiet_id))}'
            f'{_count_text(count_r, share_r)}</span></div>'
        )
    return "".join(rows)


# --------------------------------------------------------------------------------------
# the annotation table and its modal
# --------------------------------------------------------------------------------------


def _annotation_table(page, group, index, lang: str) -> str:
    ordered = sorted(
        (c for c in group.clusters if c.addressed),
        key=lambda c: (
            -group.category_counts.get(c.category or "", 0),
            c.category or "",
            c.cluster_id,
        ),
    )
    silent = [c for c in group.clusters if not c.addressed]
    header = (
        '<colgroup><col class="meta"><col class="cat"><col><col class="anchors"></colgroup>'
        f"<tr><th>{e(s('cluster', lang))}</th><th>{e(s('category', lang))}</th>"
        f"<th>{e(s('summary', lang))}</th><th>{e(s('quote_source', lang))}</th></tr>"
    )
    body = []
    for cluster in ordered:
        chips = "".join(anchor_chip(sid, index, lang) for sid in cluster.evidence)
        meta = (
            f"{media_button(cluster.source_id, cluster.source_name, index, lang)}<br>"
            f"{e(cluster.publish_date)}<br>"
            f"{cluster_chip(cluster.cluster_id, cluster.articles or None, lang)}"
        )
        note = (
            f"<br><em>{e(s('note', lang))}: {e(cluster.notes)}</em>"
            if cluster.notes
            else ""
        )
        label = category_label(page, cluster.category, lang) if cluster.category else ""
        # Confidence is retired (analyze refactor D-b): the number was never calibrated
        # across topics, so the appendix no longer shows one.
        body.append(
            f'<tr><td class="meta">{meta}</td>'
            f'<td class="cat"><strong>{e(label)}</strong></td>'
            f"<td>{e(cluster.summary or '')}{note}</td>"
            f'<td class="anchors">{chips}</td></tr>'
        )
    for cluster in silent:
        body.append(
            f'<tr class="unaddressed"><td class="meta">'
            f"{cluster_chip(cluster.cluster_id, cluster.articles or None, lang)}</td>"
            f'<td colspan="3">{e(s("not_addressed", lang))}</td></tr>'
        )
    return f'<div class="ann-scroll"><table class="ann">{header}{"".join(body)}</table></div>'


def annotation_modal(page, row, groups: dict[str, dict], index, lang: str) -> str:
    """Every annotated report for one question, one tab per side — opened on demand.

    The table is the annotation record and it is long; a reader who wants it asks for it,
    and everyone else keeps a readable page.
    """
    tabs, panels = [], []
    for position, group in enumerate(_ordered_groups(row, groups)):
        if group is None:
            continue
        css = css_of(group.group_id, groups)
        state = " on" if not tabs else ""
        tabs.append(
            f'<button type="button" class="{css}{state}" data-tab="{e(group.group_id)}">'
            f"{e(short(group.group_id, groups))} · {len(group.clusters)}</button>"
        )
        panels.append(
            f'<div class="tabpanel" data-panel="{e(group.group_id)}"'
            f'{"" if position == 0 else " hidden"}>'
            f"{_annotation_table(page, group, index, lang)}</div>"
        )
    question = reader_question(page, row.question_id, row.text, lang)
    return (
        f'<div class="modal" id="ann-{e(row.question_id)}" hidden>'
        '<div class="modal-backdrop" data-close></div>'
        '<div class="modal-card wide" role="dialog" aria-modal="true">'
        f'<button class="modal-x" type="button" data-close '
        f'aria-label="{e(s("modal_close", lang))}">&times;</button>'
        f'<h4 class="qmodal"><span class="qm">Q:</span> {e(question)}</h4>'
        f'<div class="tabs">{"".join(tabs)}</div>{"".join(panels)}</div></div>'
    )


# --------------------------------------------------------------------------------------
# the card itself
# --------------------------------------------------------------------------------------


def question_block(
    page,
    row,
    groups: dict[str, dict],
    thresholds: dict,
    lang: str,
    *,
    position: int,
    total: int,
    with_question: bool = True,
    with_metadata: bool = True,
    with_featured: bool = True,
) -> str:
    gap = row.attention_gap or {}
    kinds, strength, stability = card_kinds(row)
    badges = [
        badge(f"#{position}", "rank", s("rank_tip", lang).format(n=position, total=total))
    ]
    for kind in kinds:
        badges.append(
            kind_chip(
                kind,
                thresholds,
                lang,
                total_silence=bool(gap.get("total_silence")) if kind == "attention_gap" else False,
            )
        )
    if strength:
        badges.append(strength_chip(strength, stability, thresholds, lang))
    if any(len(group.top_categories) > 1 for group in row.groups):
        badges.append(badge(s("tied_label", lang), "soft", s("tied_tip", lang)))
    if row.secondary:
        badges.append(badge(s("secondary_label", lang), "soft", s("secondary_tip", lang)))
    badges.append(
        badge(pick(TIER_LABEL, row.tier, lang), "soft", pick(TIER_TIP, row.tier, lang))
    )
    if row.angle_rank and with_featured:
        badges.append(
            badge(
                s("featured", lang),
                "story",
                s("featured_tip", lang),
                href=f"#angle-{row.question_id}",
                attrs=f' data-angle="{e(row.question_id)}"',
            )
        )
    controls = ""
    if stat_paragraphs(page, row, groups, thresholds, lang):
        controls += icon_button(
            "i-stat", s("open_stats", lang),
            attrs=f' data-open="stat-{e(row.question_id)}"',
        )
    controls += icon_button(
        "i-table", s("open_annotations", lang),
        attrs=f' data-open="ann-{e(row.question_id)}"',
    )
    question = (
        _qtext(reader_question(page, row.question_id, row.text, lang))
        if with_question
        else ""
    )
    meta = "".join(badges) if with_metadata else ""
    qhead = f'<div class="qhead">{meta}<span class="grow"></span>{controls}</div>'
    return (
        f'<div class="qblock" id="q-{e(row.question_id)}">'
        f'{qhead}'
        f"{question}"
        f"{rates(row, groups, lang)}{butterfly(page, row, groups, lang)}</div>"
    )


def appendix_row(
    page,
    row,
    groups: dict[str, dict],
    thresholds: dict,
    lang: str,
    *,
    position: int,
    total: int,
) -> str:
    """One appendix entry: the question line, the whole card one click behind it.

    Fourteen expanded data cards is a page nobody scrolls to the end of; the question
    list is what a reader is actually scanning for.
    """
    # The appendix line and the data card inside it must name the same findings: the
    # collapsed row used to print the modal comparison alone, so a silence appeared in
    # the storyline and as "no clear pattern" (or "insufficient data") in the appendix.
    gap = row.attention_gap or {}
    kinds, strength, stability = card_kinds(row)
    summary_badges = [
        badge(f"#{position}", "rank", s("rank_tip", lang).format(n=position, total=total))
    ]
    for kind in kinds:
        summary_badges.append(
            kind_chip(
                kind,
                thresholds,
                lang,
                total_silence=bool(gap.get("total_silence")) if kind == "attention_gap" else False,
            )
        )
    if strength:
        summary_badges.append(strength_chip(strength, stability, thresholds, lang))
    if row.angle_rank:
        summary_badges.append(
            badge(
                s("featured", lang), "story", s("featured_tip", lang),
                href=f"#angle-{row.question_id}",
                attrs=f' data-angle="{e(row.question_id)}"',
            )
        )
    question = reader_question(page, row.question_id, row.text, lang)
    return (
        f'<details class="qrow" id="qrow-{e(row.question_id)}"><summary>'
        f'<span class="chev"><svg aria-hidden="true">'
        f'<use href="#i-caret"></use></svg></span>'
        f'<span class="qsum"><span class="qm">Q:</span> {e(question)}</span>'
        f'{"".join(summary_badges)}</summary>'
        + question_block(
            page,
            row,
            groups,
            thresholds,
            lang,
            position=position,
            total=total,
            with_question=False,
            with_metadata=False,
        )
        + "</details>"
    )
