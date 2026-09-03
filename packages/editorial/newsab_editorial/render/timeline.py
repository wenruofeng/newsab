"""The reporting timeline — the server ships the dates, the browser draws them.

Density and gap are the two things a reader cannot get from any count: whether one side
was reporting for weeks before the other started, and whether a side's sample is three
busy days or three months of steady coverage.

Everything about *how* that picture is drawn — how wide a bucket is, how many tick
labels fit, how big a dot is, how tall a lane needs to be — depends on the width of the
reader's window, which the renderer does not know.  So this module emits the data and
``script.JS`` draws it.  No number is computed there: the points are the
pinned corpus run's articles and nothing else.
"""

from __future__ import annotations

from typing import Iterable

from newsab_schema.models.corpus import Article, TopicManifest
from newsab_schema.readability import readable_clusters_of_articles

from .common import gtag, help_button, ordered_ids, section_title, short
from .strings import e, s


def timeline_section(
    articles: list[Article],
    groups: dict[str, dict],
    lang: str,
) -> tuple[str, dict]:
    if not articles:
        return "", {}
    # The overview's unit is one independent report. A wire item and its reprints make one
    # point, represented by the original article when present and otherwise the earliest
    # captured version. The article/cluster records still expose every member one click in.
    #
    # And it is the same universe every count on the page is drawn from: the readable
    # clusters (``newsab_schema.readability``).  A timeline that plotted every sampled
    # cluster put a bigger total above the page than the badges below it, and left the
    # reader to guess which one the site meant.  The unreadable
    # ones are still in the corpus and still findable in the report search.
    readable = readable_clusters_of_articles(articles)
    by_cluster: dict[str, list[Article]] = {}
    for article in articles:
        if article.reporting_cluster_id not in readable:
            continue
        by_cluster.setdefault(article.reporting_cluster_id, []).append(article)
    if not by_cluster:
        return "", {}
    reports = [
        min(
            members,
            key=lambda article: (
                0 if article.origin.type.value == "original" else 1,
                article.publish_date,
                article.article_id,
            ),
        )
        for members in by_cluster.values()
    ]
    dates = sorted(article.publish_date for article in reports)
    first, last = dates[0], dates[-1]
    order = ordered_ids(groups)
    lane_of = {group_id: position for position, group_id in enumerate(order)}

    points = []
    for article in sorted(reports, key=lambda a: (a.publish_date, a.article_id)):
        group_id = article.article_id.split("_", 1)[0].lower()
        if group_id not in lane_of:
            continue
        points.append(
            {
                "d": (article.publish_date - first).days,
                "g": lane_of[group_id],
                "a": article.article_id,
            }
        )

    payload = {
        "first": first.isoformat(),
        "last": last.isoformat(),
        "span": (last - first).days,
        "points": points,
        "strings": {"title": s("timeline_title", lang)},
    }

    legend = "".join(
        f'<span class="slot {"up" if position == 0 else "down"}">'
        f"{gtag(group_id, groups, lang, 'tipright')}</span>"
        for position, group_id in enumerate(order)
    )
    sides = " / ".join(
        s("window_side", lang).format(
            who=short(group_id, groups),
            n=len(
                [
                    a
                    for a in reports
                    if a.article_id.split("_", 1)[0].lower() == group_id
                ]
            ),
        )
        for group_id in order
    )
    summary = s("window_counts", lang).format(sides=sides, articles=len(reports))
    html = (
        f'<section class="panel timeline" id="timeline">'
        f'<div class="panel-head timeline-head">'
        f'{section_title("i-timeline", s("timeline_title", lang))}'
        f'{help_button("scopemodal", s("scope_tip", lang))}</div>'
        f'<p class="lede timeline-range">{e(first.isoformat())} – {e(last.isoformat())}</p>'
        f'<div class="tl-wrap"><div class="tl-legend" id="tl-legend">{legend}</div>'
        f'<div class="tl-canvas" id="tl-canvas"></div></div>'
        f'<div class="tl-foot"><span class="sum">{e(summary)}</span></div>'
        f"</section>"
    )
    return html, payload
