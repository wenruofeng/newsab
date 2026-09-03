"""The concept cloud: both sides' vocabularies, each column ranked by its own share.

Everything here is arithmetic over the pinned run (see :mod:`..concept_cloud`); the
writer contributes the caption and nothing else.  The mechanism sentence, the footnote
and the hover panel are the renderer's, identical on every page — the same discipline the
statistical chips follow.

Two sources, one picture.  ``categories`` sums the annotated answers, which
is what the section has always drawn; ``topics_raised`` counts, per independent report,
the phrases the collector noted while reading it.  The second is on trial: it says what
the coverage is *about* rather than what it *answers*, which is a different and possibly
more useful question for a section that asserts nothing.
"""

from __future__ import annotations

from .. import concept_cloud
from .common import (
    category_label,
    css_of,
    gtag,
    help_button,
    json_block,
    ordered_ids,
    section_title,
    short,
    topic_label,
)
from .strings import e, s


def _label(page, key: str, lang: str, source: str) -> str:
    if source == "topics_raised":
        return topic_label(page, key, lang)
    return category_label(page, key, lang)


def concept_cloud_viz(
    page,
    caption: str,
    clouds: dict,
    groups: dict[str, dict],
    lang: str,
    *,
    source: str = "categories",
) -> str:
    order = ordered_ids(groups)
    drawn = [gid for gid in order if gid in clouds and clouds[gid].total]
    if len(drawn) < 2:
        # One side with no classified answers at all is not a cloud with an empty column;
        # it is a section that would invite a comparison it cannot support.
        return ""
    topics = source == "topics_raised"
    total_key = "cc_total_topics" if topics else "cc_total"
    lede_key = "cc_lede_topics" if topics else "cc_lede"
    foot_key = "cc_foot_topics" if topics else "cc_foot"

    top_share = max(clouds[gid].top_share for gid in drawn)
    columns, payload = [], {}
    for group_id in drawn:
        cloud = clouds[group_id]
        css = css_of(group_id, groups)
        head_bits = [
            f"<small>{e(s(total_key, lang).format(n=cloud.total))}</small>",
            gtag(group_id, groups, lang),
        ]
        if css == "b":
            head_bits.reverse()
        pills = []
        for key in cloud.shown:
            entry = cloud.concepts[key]
            px = concept_cloud.font_px(entry.share, top_share)
            label = f'<span class="lbl">{e(_label(page, key, lang, source))}</span>'
            share = f'<span class="pct">{entry.share * 100:.1f}%</span>'
            body = f"{label}{share}" if css == "a" else f"{share}{label}"
            pills.append(
                f'<span class="pill {css}" tabindex="0" data-k="{e(key)}" '
                f'style="font-size:{px:.1f}px">{body}</span>'
            )
        columns.append(
            f'<div class="cc-side {css}"><div class="cc-h">{"".join(head_bits)}</div>'
            f'<div class="cc-body">{"".join(pills)}</div></div>'
        )
        payload[group_id] = {
            "css": css,
            "short": short(group_id, groups),
            "total": cloud.total,
            "concepts": {
                key: {
                    "count": entry.count,
                    "pct": f"{entry.share * 100:.1f}%",
                    # Below the threshold is not silence: the panel always gives the other
                    # side's real number, and says why it is not on the page.
                    "note": {
                        "below_threshold": s("cc_below", lang),
                        "capped": s("cc_capped", lang),
                    }.get(entry.hidden_reason, ""),
                }
                for key, entry in cloud.concepts.items()
            },
        }

    hidden = s("cc_hidden_sep", lang).join(
        s("cc_hidden_side", lang).format(
            who=short(gid, groups), below=clouds[gid].below_threshold
        )
        + (
            s("cc_hidden_capped", lang).format(capped=clouds[gid].capped)
            if clouds[gid].capped
            else ""
        )
        for gid in drawn
    )
    totals = " · ".join(
        s("cc_side_total", lang).format(who=short(gid, groups), n=clouds[gid].total)
        for gid in drawn
    )
    foot = s(foot_key, lang).format(
        threshold=f"{concept_cloud.SHARE_THRESHOLD:.0%}",
        min_count=concept_cloud.MIN_COUNT,
        cap=concept_cloud.MAX_PER_SIDE,
        hidden=hidden,
        totals=totals,
    )
    # The title and calculation note are renderer-owned: all pages show the same section,
    # even when an older page artifact still calls it "Key concept cloud".
    info_modal = (
        '<div class="modal" id="conceptcloudmodal" hidden>'
        '<div class="modal-backdrop" data-close></div>'
        '<div class="modal-card" role="dialog" aria-modal="true">'
        f'<button class="modal-x" type="button" data-close '
        f'aria-label="{e(s("modal_close", lang))}">&times;</button>'
        f'<h4>{e(s("cc_info_title", lang))}</h4>'
        f'<p class="modal-p">{e(foot)}</p></div></div>'
    )
    return (
        f'<section class="panel cloudbox" id="concept-cloud">'
        f'<div class="panel-head cloud-head">'
        f'{section_title("i-cloud", s("cc_title", lang))}'
        f'{help_button("conceptcloudmodal", s("cc_info_open", lang))}</div>'
        f'<p class="lede">{e(s(lede_key, lang))}</p>'
        f'<div class="cc-grid">{"".join(columns)}</div>'
        f'</section>{info_modal}'
        + json_block(
            "concept-cloud-data",
            {"order": drawn, "sides": payload, "strings": {"absent": s("cc_absent", lang)}},
        )
    )
