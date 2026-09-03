"""Static report search over reader-visible metadata and annotations.

The search payload deliberately never reads an article's ``structured_text``. It is
built from the same article record, collection-stage phrases and Q×A annotation rows the
page already exposes, so adding search cannot quietly turn a preview into a full-text
index (non-negotiable 7).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from newsab_schema.models.corpus import Article

from ..evidence import QuestionRow
from .common import section_title
from .strings import e, s


def report_search_payload(
    articles: Iterable[Article],
    article_index: dict[str, dict],
    rows: Iterable[QuestionRow],
) -> list[dict]:
    """One compact **language-neutral** search document per article.

    Localized display strings (outlet name, group tag, origin label, question wording,
    category labels) are not baked in here any more: the document carries the stable ids
    and English-pivot text, and ``render.islands`` merges the per-language overlay back
    into the legacy shape — server-side for an inline render, in the page script for an
    externalized one.  Public page fields only; never an article's ``structured_text``.
    """
    annotations: dict[str, dict[str, list]] = defaultdict(
        lambda: {"question_ids": [], "answers": []}
    )
    for row in rows:
        for group in row.groups:
            for cluster in group.clusters:
                if not cluster.addressed:
                    continue
                bucket = annotations[cluster.cluster_id]
                bucket["question_ids"].append(row.question_id)
                bucket["answers"].append(
                    {
                        "category": cluster.category or None,
                        "texts": [
                            value
                            for value in (cluster.summary, cluster.notes)
                            if value
                        ],
                    }
                )

    documents: list[dict] = []
    for article in articles:
        card = article_index.get(article.article_id)
        if not card:
            continue
        ann = annotations.get(article.reporting_cluster_id) or {}
        documents.append(
            {
                "article": article.article_id,
                "title": card.get("title") or "",
                "source_id": card.get("source_id") or "",
                "date": card.get("date") or "",
                "fetched": card.get("fetched") or "",
                "group_id": article.article_id.split("_", 1)[0].lower(),
                "origin_code": card.get("origin") or "",
                "wire_source": card.get("wire_source"),
                "cluster": card.get("cluster") or "",
                "topics": [
                    {
                        "source_phrase": topic.get("source_phrase") or "",
                        "pivot_en": topic.get("pivot_en") or "",
                    }
                    for topic in card.get("topics") or []
                ],
                "question_ids": list(ann.get("question_ids") or []),
                "answers": list(ann.get("answers") or []),
            }
        )
    return documents


def report_search_section(lang: str) -> str:
    """The progressively enhanced search shell, directly below the concept cloud."""
    return (
        '<section class="report-search" id="report-search">'
        '<div class="search-head">'
        f'{section_title("i-search", s("search_title", lang), tag="h2")}'
        f'<span class="search-count" id="report-search-count" aria-live="polite"></span>'
        '</div>'
        f'<p class="lede" id="report-search-help">{e(s("search_lede", lang))}</p>'
        '<div class="search-field">'
        '<svg aria-hidden="true"><use href="#i-search-plain"></use></svg>'
        f'<input type="search" id="report-search-input" autocomplete="off" '
        f'spellcheck="false" enterkeyhint="search" aria-describedby="report-search-help" '
        f'aria-controls="report-search-results" placeholder="{e(s("search_placeholder", lang))}" '
        'data-search-delay="80">'
        f'<button class="search-clear" type="button" id="report-search-clear" hidden '
        f'aria-label="{e(s("search_clear", lang))}" title="{e(s("search_clear", lang))}">'
        '<svg aria-hidden="true"><use href="#i-close"></use></svg></button>'
        '</div>'
        '<p class="search-status" id="report-search-status"></p>'
        '<ol class="search-results" id="report-search-results" hidden></ol>'
        '</section>'
    )
