"""Statistical labels and the panel behind them — written here, never by a writer.

Two things live in this module:

* the **chips** (kind, strength, tier, tied) whose tooltips restate the pinned run's own
  thresholds, so no page ever quotes a bar it was not produced under;
* the **statistics panel** a reader opens from the data card.  Every sentence in it is a
  template filled from the finding: what the two sides' most common answers were, the
  effect size with its interval, how often resampling reproduces the picture, and what
  that made the claim's strength.  The raw ``quantity`` codes (``divergence_share_gap``
  and friends) no longer reach a reader — they said nothing a reader could use.
"""

from __future__ import annotations

from typing import Optional

from .common import badge, category_label, css_of, ordered_ids, short
from .strings import (
    KIND_LABEL,
    KIND_TIP,
    STAT_EFFECT_DETAIL,
    STAT_EFFECT_LEAD_CONSENSUS,
    STAT_EFFECT_LEAD_DIVERGENCE,
    STAT_ESTIMATE,
    STAT_LOUD_CLAUSE_FLOOR,
    STAT_LOUD_CLAUSE_SPREAD,
    STAT_PHENOMENON_ATTENTION_GAP_GENERIC,
    STAT_PHENOMENON_CONSENSUS,
    STAT_PHENOMENON_DIVERGENCE,
    STAT_PHENOMENON_SILENCE,
    STAT_RATE_DETAIL,
    STAT_RATE_LEAD,
    STAT_READING,
    STAT_REPRODUCIBILITY,
    STAT_SHARE,
    STAT_STRENGTH_CLAUSE,
    STRENGTH_LABEL,
    STRENGTH_TIP_POSTERIOR,
    e,
    pick,
    rich,
    s,
    t,
)

#: Fallback when a page is rendered without the pinned analyze run's thresholds.
DEFAULT_THRESHOLDS = {
    "thresholds_version": "qa-0.4.0",
    "calibrated": True,
    "n_draws": 1000,
    "interval_level": 0.90,
    "pseudo_total": 1.0,
    "supported_min_probability": 0.95,
    "weak_min_probability": 0.70,
    "attention_gap_min_abs_diff": 0.25,
    "silent_max_rate": 0.10,
}

#: Every threshold key any tip template (legacy bootstrap or posterior) may reference.
#: Used only to fill keys the pinned run does not define — e.g. a legacy "insufficient"
#: label rendered beside a posterior run — so a vocabulary mismatch degrades to the
#: historical default instead of refusing the page.  Keys the run defines always win.
TIP_FALLBACK = {
    "n_resamples": 1000,
    "min_addressed_for_comparison": 2,
    "blindspot_min_speaking_rate": 0.20,
    "blindspot_min_speaking_clusters": 3,
    "supported_min_stability": 0.90,
    "supported_min_side_support": 3,
    "weak_min_stability": 0.70,
    "weak_min_side_support": 2,
    "coverage_gap_min_abs_diff": 0.25,
    **DEFAULT_THRESHOLDS,
}

#: The kinds whose data card carries no statistical assertion at all, and therefore no
#: strength chip, no statistics panel and no interval.
NO_ASSERTION = frozenset({"no_significant_relation", "too_thin", "insufficient"})


def kind_chip(kind: str, thresholds: dict, lang: str, *, total_silence: bool = False) -> str:
    tip_key = kind
    if kind == "attention_gap":
        if total_silence:
            tip_key = "attention_gap_silence"
        elif "silent_max_rate" not in thresholds:
            tip_key = "attention_gap_rate_legacy"
    return badge(
        pick(KIND_LABEL, kind, lang),
        "kind",
        pick(KIND_TIP, tip_key, lang).format(**{**TIP_FALLBACK, **thresholds}),
    )


def _strength_tip(
    strength: str, stability: Optional[float], thresholds: dict, lang: str
) -> str:
    if stability is None:
        clause = ""
    else:
        clause = STAT_STRENGTH_CLAUSE.get(lang, STAT_STRENGTH_CLAUSE["en"]).format(
            stability=stability
        )
    tip = pick(STRENGTH_TIP_POSTERIOR, strength, lang).format(
        stability_clause=clause, **{**TIP_FALLBACK, **thresholds}
    )
    return tip


_STRENGTH_DOT = {"supported": "dot-ok", "weak": "dot-warn", "unsupported": "dot-bad"}


def strength_chip(
    strength: str, stability: Optional[float], thresholds: dict, lang: str
) -> str:
    lead = f'<span class="{_STRENGTH_DOT.get(strength, "dot-bad")}"></span>'
    return badge(
        pick(STRENGTH_LABEL, strength, lang),
        f"strength {strength}",
        _strength_tip(strength, stability, thresholds, lang),
        lead=lead,
    )


def strength_icon(
    strength: str, stability: Optional[float], thresholds: dict, lang: str
) -> str:
    """The storyline's form of the strength chip: an icon in front of the question.

    A story angle can only ever be ``supported`` or ``weak`` — an unsupported claim is
    not written — so two icons carry the whole vocabulary, and the words move into the
    tooltip where they no longer compete with the question for the reader's eye.
    """
    if strength not in ("supported", "weak"):
        return ""
    symbol = "i-supported" if strength == "supported" else "i-weak"
    label = pick(STRENGTH_LABEL, strength, lang)
    tip = strength_label_tip(strength, stability, thresholds, lang)
    return (
        f'<span class="sig {strength}" data-tip="{e(tip)}" tabindex="0" '
        f'aria-label="{e(label)}"><svg aria-hidden="true">'
        f'<use href="#{symbol}"></use></svg></span>'
    )


def strength_label_tip(
    strength: str,
    stability: Optional[float],
    thresholds: dict,
    lang: str,
    *,
    conclusion: str = "",
) -> str:
    """The generated label + rule used by any visual carrier of evidence strength."""
    label = pick(STRENGTH_LABEL, strength, lang)
    explanation = _strength_tip(strength, stability, thresholds, lang)
    if conclusion:
        if lang.startswith("zh"):
            explanation = explanation.replace("该结论", f"「{conclusion}」结论", 1)
        else:
            explanation = explanation.replace(
                "this statement", f'the “{conclusion.lower()}” finding', 1
            )
    return f"{label} — {explanation}"


# --------------------------------------------------------------------------------------
# the statistics panel
# --------------------------------------------------------------------------------------


def _share_phrase(row, group_id: str, category: str, groups: dict, lang: str) -> str:
    group = next((g for g in row.groups if g.group_id == group_id), None)
    if group is None or not group.clusters_addressed:
        return ""
    count = group.category_counts.get(category, 0)
    return STAT_SHARE.get(lang, STAT_SHARE["en"]).format(
        who=short(group_id, groups),
        numerator=count,
        denominator=group.clusters_addressed,
        share=count / group.clusters_addressed,
    )


def _rate_phrase(row, group_id: str, groups: dict, lang: str) -> str:
    group = next((g for g in row.groups if g.group_id == group_id), None)
    if group is None or not group.clusters_total:
        return ""
    return STAT_SHARE.get(lang, STAT_SHARE["en"]).format(
        who=short(group_id, groups),
        numerator=group.clusters_addressed,
        denominator=group.clusters_total,
        share=group.clusters_addressed / group.clusters_total,
    )


def stat_paragraphs(page, row, groups: dict[str, dict], thresholds: dict, lang: str) -> list[str]:
    """Compatibility view of :func:`stat_blocks`, one combined string per bullet."""
    return [f"{lead} {detail}" for lead, detail in stat_blocks(page, row, groups, thresholds, lang)]


def _angle_of(page, question_id: str):
    return next((a for a in page.angles if a.question_id == question_id), None)


def _answer_words(page, row, group_id: Optional[str], category: str, lang: str) -> str:
    """The words the *answer card* uses for this side's leading answer.

    The panel is generated from the page's own data, so it has to quote the page's own
    wording.  A normalized category label and an angle's answer label are two
    localizations of the same answer written by two different steps; printing one here
    and the other on the card beside it reads as two different answers, which is what a
    reader actually reported seeing.  Questions with no angle —
    every appendix-only row — still fall back to the category label.
    """
    angle = _angle_of(page, row.question_id)
    if angle is not None:
        if angle.shared_answer_label is not None:
            return t(angle.shared_answer_label, lang)
        for side in angle.sides:
            if side.group_id == group_id and side.answer_category == category:
                if side.answer_label:
                    return t(side.answer_label, lang)
    return category_label(page, category, lang)


def _rate_of(row, group_id: Optional[str]) -> float:
    group = next((g for g in row.groups if g.group_id == group_id), None)
    if group is None or not group.clusters_total:
        return 0.0
    return group.clusters_addressed / group.clusters_total


def _quiet_side(row, left: Optional[str], right: Optional[str]) -> Optional[str]:
    """Which side the silence finding calls quiet.

    The analyze run records it; a run old enough not to have is read off the observed
    rates, which is the same rule that produced it.
    """
    if row.quiet_group in (left, right) and row.quiet_group is not None:
        return row.quiet_group
    return left if _rate_of(row, left) <= _rate_of(row, right) else right


def stat_blocks(page, row, groups: dict[str, dict], thresholds: dict, lang: str) -> list[tuple[str, str]]:
    """Three reader-shaped evidence bullets: phenomenon, answer rate, effect size."""
    gap = row.attention_gap or {}
    # The panel explains the finding the card is about, and a silence outranks every
    # other kind: one question gets one angle, and a side that barely answered is the
    # reason not to compare its leading answer at all.  Two things followed from not
    # doing that: a question whose comparison was `no_significant_relation` had no panel
    # at all even though its silence was a real finding, and the one silence that did
    # get a panel opened with "both sides' most common answer is the same" — a sentence
    # that says nothing about a side which barely answered.
    silence = bool(gap)
    if silence:
        strength = gap.get("strength")
        stability = gap.get("stability")
    else:
        if row.kind in NO_ASSERTION:
            return []
        strength = row.strength
        stability = row.stability
    if not strength:
        return []
    left, right = (ordered_ids(groups) + [None, None])[:2]
    tops = {
        group.group_id: (group.top_categories[0] if group.top_categories else None)
        for group in row.groups
    }
    blocks: list[tuple[str, str]] = []
    delta = row.delta or {}
    bar = {**TIP_FALLBACK, **thresholds}
    if silence:
        quiet = _quiet_side(row, left, right)
        loud = right if quiet == left else left
        quiet_rate, loud_rate = _rate_of(row, quiet), _rate_of(row, loud)
        smax = float(bar["silent_max_rate"])
        # Exactly the clause the run was produced under: an absolute floor on the loud
        # side when the run set one, the relative separation otherwise.
        floor = bar.get("loud_min_rate")
        if floor is not None:
            loud_clause = STAT_LOUD_CLAUSE_FLOOR.get(
                lang, STAT_LOUD_CLAUSE_FLOOR["en"]
            ).format(floor=float(floor))
        else:
            spread = float(bar["attention_gap_min_abs_diff"])
            loud_clause = STAT_LOUD_CLAUSE_SPREAD.get(
                lang, STAT_LOUD_CLAUSE_SPREAD["en"]
            ).format(spread=spread)
        phenomenon = STAT_PHENOMENON_SILENCE.get(
            lang, STAT_PHENOMENON_SILENCE["en"]
        ).format(
            quiet_rate=quiet_rate, smax=smax, loud_rate=loud_rate, loud_clause=loud_clause
        )
    elif row.kind == "consensus":
        answer = tops.get(left) or tops.get(right) or ""
        shared = _answer_words(page, row, left if tops.get(left) else right, answer, lang)
        phenomenon = STAT_PHENOMENON_CONSENSUS.get(
            lang, STAT_PHENOMENON_CONSENSUS["en"]
        ).format(shared=shared)
    elif row.kind == "divergence":
        lanswer = _answer_words(page, row, left, tops.get(left) or "", lang)
        ranswer = _answer_words(page, row, right, tops.get(right) or "", lang)
        phenomenon = STAT_PHENOMENON_DIVERGENCE.get(
            lang, STAT_PHENOMENON_DIVERGENCE["en"]
        ).format(
            left_short=short(left, groups), lanswer=lanswer,
            right_short=short(right, groups), ranswer=ranswer,
        )
    else:
        phenomenon = STAT_PHENOMENON_ATTENTION_GAP_GENERIC.get(
            lang, STAT_PHENOMENON_ATTENTION_GAP_GENERIC["en"]
        )
    draws = int(thresholds.get("n_draws", 1000))
    # The sentence explains the band this particular finding cleared.  A weak 72%
    # finding cleared the 70% boundary, not the 95% supported boundary.
    gate_key = "supported_min_probability" if strength == "supported" else "weak_min_probability"
    gate = float(thresholds.get(gate_key, 0.95 if strength == "supported" else 0.70))
    stable = stability or 0.0
    reproducibility = STAT_REPRODUCIBILITY.get(
        lang, STAT_REPRODUCIBILITY["en"]
    ).format(draws=draws, stable=stable, gate=gate)
    blocks.append((phenomenon, reproducibility))

    rate = row.rate_diff or (delta if row.kind == "attention_gap" else {})
    if rate:
        value = rate.get("value", 0.0)
        lo, hi = rate.get("lo", 0.0), rate.get("hi", 0.0)
        # Always left-minus-right, in the manifest's own order.  The run records
        # whichever pair it happened to draw, and a sign that disagreed with the two
        # rates printed right beside it read as an arithmetic error.
        if rate.get("group_b") == left and rate.get("group_a") == right:
            value, lo, hi = -value, -hi, -lo
        no_diff = lo <= 0 <= hi
        rate_lead = STAT_RATE_LEAD.get(lang, STAT_RATE_LEAD["en"]).format(
            value=value,
            left_phrase=_rate_phrase(row, left, groups, lang),
            right_phrase=_rate_phrase(row, right, groups, lang),
        )
        reading = pick(STAT_READING, "same" if no_diff else "diff", lang)
        rate_detail = STAT_RATE_DETAIL.get(lang, STAT_RATE_DETAIL["en"]).format(
            draws=draws, lo=lo, hi=hi, reading=reading
        )
        blocks.append((rate_lead, rate_detail))

    # Not beside a silence: an answer rate low enough to assert a gap is exactly the
    # reason not to read that side's leading answer against the other's, so the effect
    # size of a comparison the gap has already withdrawn does not belong here either
    # (one question, one angle, and silence outranks the rest).
    if delta and not silence and row.kind in {"consensus", "divergence"}:
        value, lo, hi = delta.get("value", 0.0), delta.get("lo", 0.0), delta.get("hi", 0.0)
        if row.kind == "consensus":
            answer = tops.get(left) or tops.get(right) or ""
            effect_lead = STAT_EFFECT_LEAD_CONSENSUS.get(
                lang, STAT_EFFECT_LEAD_CONSENSUS["en"]
            ).format(
                value=value,
                left_phrase=_share_phrase(row, left, answer, groups, lang),
                right_phrase=_share_phrase(row, right, answer, groups, lang),
            )
            estimate = pick(STAT_ESTIMATE, "consensus", lang)
        else:
            effect_lead = STAT_EFFECT_LEAD_DIVERGENCE.get(
                lang, STAT_EFFECT_LEAD_DIVERGENCE["en"]
            ).format(value=value)
            estimate = pick(STAT_ESTIMATE, "divergence", lang)
        effect_detail = STAT_EFFECT_DETAIL.get(lang, STAT_EFFECT_DETAIL["en"]).format(
            draws=draws, lo=lo, hi=hi, estimate=estimate
        )
        blocks.append((effect_lead, effect_detail))
    return blocks


def stat_modal(page, row, groups: dict[str, dict], thresholds: dict, lang: str) -> str:
    blocks = stat_blocks(page, row, groups, thresholds, lang)
    if not blocks:
        return ""
    body = "".join(
        f'<li><p>{rich(lead)}</p><p class="stat-sub">{rich(detail)}</p></li>'
        for lead, detail in blocks
    )
    return (
        f'<div class="modal" id="stat-{e(row.question_id)}" hidden>'
        '<div class="modal-backdrop" data-close></div>'
        '<div class="modal-card" role="dialog" aria-modal="true">'
        f'<button class="modal-x" type="button" data-close '
        f'aria-label="{e(s("modal_close", lang))}">&times;</button>'
        f'<h4>{e(s("stats_title", lang))}</h4>'
        f'<ul class="stat-list">{body}</ul></div></div>'
    )
