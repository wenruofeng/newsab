"""Content-addressed data islands and the per-language overlay.

More than half of a rendered page used to be inline JSON data islands, and measurement
showed the bulk of those bytes is language-neutral: the en and zh copies of a page's
``sentence-index`` differ only in the display fields (``source``, ``topics[].localized``,
``translation``) that a few-KB lookup table can supply.  So the four heavy islands are
split in two:

* a **language-neutral base** — the same bytes for every locale of a page, serialized
  canonically and named by its own content hash (``sentence-index.<sha16>.json``), so the
  same content gets the same filename across locales *and* across page versions;
* a **per-language overlay** — small lookup maps (outlet names, topic phrases, question
  wording, category labels, group tags, our translations) that stay inline in the page.

A page rendered in *external* mode carries only a reference per island
(``<script type="application/json" id="…" data-src="…"></script>``) plus the overlay; the
behaviour script fetches each base and **hydrates** it with the overlay back into exactly
the structures the rest of the script has always consumed.  A page rendered *inline*
(tests, ad-hoc renders) merges base and overlay server-side with the same rules — the
``merge_*`` functions below are the reference implementation the JavaScript mirrors.

The base islands are content, not chrome: in a publication they enter the bundle's closed
file list, the bundle fingerprint, and the publication record's ``data_assets`` pins.  The
page's own bytes reference each asset by hash-name, so the human approval of the page
bytes transitively binds the asset bytes.
"""

from __future__ import annotations

import hashlib
import json

#: The islands worth externalizing, in emission order.  Everything else on the page
#: (timeline data, media cards, UI strings, the concept cloud) is small or inherently
#: per-language and stays inline.
EXTERNAL_ISLANDS = (
    "sentence-index",
    "article-index",
    "report-search-index",
    "cluster-index",
)

#: The inline island that carries the per-language lookup maps in external mode.
OVERLAY_ISLAND = "lang-overlay"


def canonical_asset_bytes(payload: object) -> bytes:
    """One canonical byte serialization per payload — the unit the content hash names."""
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def asset_name(island: str, payload_bytes: bytes) -> str:
    """``<island>.<first 16 hex of sha256>.json`` — same content, same name, anywhere.

    The name deliberately does not match the ``preview*.html`` pattern the preview
    dashboard globs, and carries its own integrity check: a verifier that hashes the file
    can compare against the name without any side record.
    """
    return f"{island}.{hashlib.sha256(payload_bytes).hexdigest()[:16]}.json"


# --------------------------------------------------------------------------------------
# server-side hydration — the reference the page script's ``hydrate()`` mirrors
# --------------------------------------------------------------------------------------


def _localized_topics(entries: list[dict], overlay: dict) -> list[dict]:
    topics_map = overlay.get("topics") or {}
    out = []
    for entry in entries or []:
        pivot = entry.get("pivot_en") or ""
        out.append(
            {
                **entry,
                "localized": topics_map.get(pivot)
                or pivot
                or entry.get("source_phrase")
                or "",
            }
        )
    return out


def _record_card(card: dict, overlay: dict) -> dict:
    sources = overlay.get("sources") or {}
    merged = {**card, "source": sources.get(card.get("source_id")) or card.get("source_id") or ""}
    if "topics" in merged:
        merged["topics"] = _localized_topics(merged["topics"], overlay)
    return merged


def merge_sentence_index(base: dict, overlay: dict) -> dict:
    """Base sentence cards + overlay → the legacy fully-localized ``sentence-index``."""
    translations = overlay.get("translations") or {}
    out = {}
    for sid, card in base.items():
        merged = _record_card(card, overlay)
        if sid in translations:
            merged["translation"] = translations[sid]
        out[sid] = merged
    return out


def merge_article_index(base: dict, overlay: dict) -> dict:
    return {article_id: _record_card(card, overlay) for article_id, card in base.items()}


def _unique(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def merge_search_docs(base_docs: list[dict], overlay: dict) -> list[dict]:
    """Neutral search documents + overlay → the legacy search index shape."""
    sources = overlay.get("sources") or {}
    groups = overlay.get("groups") or {}
    origins = overlay.get("origins") or {}
    questions = overlay.get("questions") or {}
    categories = overlay.get("categories") or {}
    topics_map = overlay.get("topics") or {}
    out = []
    for doc in base_docs:
        source = sources.get(doc.get("source_id")) or ""
        group = groups.get(doc.get("group_id")) or {}
        origin_label = origins.get(doc.get("origin_code")) or doc.get("origin_code") or ""
        phrase_values: list[str] = []
        phrase_labels: list[str] = []
        for topic in doc.get("topics") or []:
            pivot = topic.get("pivot_en") or ""
            localized = topics_map.get(pivot) or ""
            phrase_labels.append(localized or pivot or topic.get("source_phrase") or "")
            phrase_values.extend((topic.get("source_phrase"), localized, pivot))
        answer_values: list[str] = []
        for row in doc.get("answers") or []:
            if row.get("category"):
                answer_values.append(categories.get(row["category"]) or row["category"])
            answer_values.extend(row.get("texts") or [])
        out.append(
            {
                "article": doc.get("article"),
                "title": doc.get("title") or "",
                "source": source,
                "date": doc.get("date") or "",
                "group": group.get("short") or group.get("label") or doc.get("group_id") or "",
                "origin": origin_label,
                "cluster": doc.get("cluster") or "",
                "phrases": _unique(phrase_values),
                "phrase_labels": _unique(phrase_labels),
                "questions": _unique(
                    questions.get(qid) or qid for qid in doc.get("question_ids") or []
                ),
                "answers": _unique(answer_values),
                "meta": _unique(
                    (
                        source,
                        doc.get("date"),
                        doc.get("fetched"),
                        group.get("short"),
                        group.get("label"),
                        group.get("definition"),
                        origin_label,
                        doc.get("wire_source"),
                        doc.get("cluster"),
                    )
                ),
            }
        )
    return out


def merge_island(island: str, base: object, overlay: dict) -> object:
    if island == "sentence-index":
        return merge_sentence_index(base, overlay)
    if island == "article-index":
        return merge_article_index(base, overlay)
    if island == "report-search-index":
        return merge_search_docs(base, overlay)
    return base
