"""The modal layer: the sentence card, the outlet card, the cluster list, and the four
standing panels a reader can open from the page (scope, methodology, disclosure).

Three levels of "what is this?" now exist and connect to each other:
sentence → article → **reporting cluster**.  The middle level was already there; the
cluster was the one every count on the page is made of and the one a reader could not
open.  Every place a cluster id appears is now a way in.
"""

from __future__ import annotations
from datetime import timezone

from typing import Iterable, Optional

from newsab_schema.models.corpus import TopicManifest
from ..provenance import Contribution, PageComponent

from .common import short
from .strings import LANG_LABEL, METHOD_SECTIONS, PROVENANCE_COUNTS, e, pick, rich, s, t


def _shell(modal_id: str, lang: str, body: str, *, wide: bool = False) -> str:
    return (
        f'<div class="modal" id="{modal_id}" hidden>'
        '<div class="modal-backdrop" data-close></div>'
        f'<div class="modal-card{" wide" if wide else ""}" role="dialog" aria-modal="true">'
        f'<button class="modal-x" type="button" data-close '
        f'aria-label="{e(s("modal_close", lang))}">&times;</button>'
        f"{body}</div></div>"
    )


def source_modal(lang: str) -> str:
    return (
        '<div class="modal" id="srcmodal" hidden>'
        '<div class="modal-backdrop" data-close></div>'
        '<div class="modal-card" role="dialog" aria-modal="true" '
        'aria-labelledby="srcmodal-title">'
        f'<button class="modal-x" type="button" data-close '
        f'aria-label="{e(s("modal_close", lang))}">&times;</button>'
        '<div class="modal-meta"></div><h4 id="srcmodal-title"></h4>'
        '<blockquote class="modal-quote"></blockquote><p class="modal-tr" hidden></p>'
        '<dl class="modal-dl"></dl>'
        '<a class="modal-out" target="_blank" rel="noopener"></a>'
        f'<p class="modal-fine">{e(s("modal_note", lang))}</p></div></div>'
    )


def media_modal(lang: str) -> str:
    return _shell(
        "mediamodal",
        lang,
        '<h4></h4><p class="modal-lede"></p><dl class="modal-dl"></dl>'
        '<a class="modal-out" target="_blank" rel="noopener"></a>',
    )


def cluster_modal(lang: str) -> str:
    header = (
        f"<tr><th>{e(s('cluster_col_outlet', lang))}</th>"
        f"<th>{e(s('cluster_col_date', lang))}</th>"
        f"<th>{e(s('cluster_col_title', lang))}</th></tr>"
    )
    return _shell(
        "clustermodal",
        lang,
        f'<h4></h4><p class="modal-lede">{e(s("cluster_lede", lang))}</p>'
        f'<table class="clist"><thead>{header}</thead><tbody></tbody></table>',
    )


def scope_modal(
    page, manifest: TopicManifest, groups: dict, collected: Optional[str], lang: str
) -> str:
    """What we said we would collect, before we collected any of it.

    Touchpoint one's own words, in the reader's language — a reader judging what is
    missing from this page needs to see what was deliberately left out.  An open-ended
    window now says the day collection actually stopped rather than "still open", which
    told a reader nothing they could use.
    """
    from .common import scope_text

    if manifest.period.end:
        end = e(manifest.period.end.isoformat())
    elif collected:
        end = e(s("scope_collected_end", lang).format(date=collected))
    else:
        end = "—"
    rows = [
        f"<dt>{e(s('scope_period', lang))}</dt>"
        f"<dd>{e(manifest.period.start.isoformat())} – {end}</dd>"
    ]
    if manifest.target_clusters_per_group:
        targets = " · ".join(
            f"{short(gid, groups)} {n}"
            for gid, n in sorted(manifest.target_clusters_per_group.items())
        )
        rows.append(f"<dt>{e(s('scope_target', lang))}</dt><dd>{e(targets)}</dd>")

    def bullets(title: str, items: list[str]) -> str:
        if not items:
            return ""
        body = "".join(f"<li>{e(scope_text(page, item, lang))}</li>" for item in items)
        return f'<h5>{e(title)}</h5><ul class="modal-list">{body}</ul>'

    return _shell(
        "scopemodal",
        lang,
        f"<h4>{e(s('scope_title', lang))}</h4>"
        f'<p class="modal-lede">{e(s("scope_note", lang))}</p>'
        f'<dl class="modal-dl">{"".join(rows)}</dl>'
        f"{bullets(s('scope_include', lang), list(manifest.include))}"
        f"{bullets(s('scope_exclude', lang), list(manifest.exclude))}",
    )


def method_modal(lang: str) -> str:
    """How this site counts — the same words on every topic page there will ever be.

    Deliberately renderer-owned template text: it is about the method, not
    about this topic, and when the site grows a standing methodology page it moves there
    unchanged.  Anything topic-specific belongs in the disclosure panel instead.
    """
    body = "".join(
        f'<h5>{e(t_(title, lang))}</h5><p class="modal-p">{rich(t_(text, lang))}</p>'
        for title, text in METHOD_SECTIONS
    )
    return _shell("methodmodal", lang, f"<h4>{e(s('method_title', lang))}</h4>{body}")


def t_(entry: dict, lang: str) -> str:
    return entry.get(lang, entry["en"])


def _utc(value) -> str:
    """Machine timestamp: full ISO-8601 UTC, for the ``datetime`` attribute."""
    if value is None:
        return ""
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _stamp(value) -> str:
    """The same instant as a reader reads it — no ``T``, no ``Z``."""
    if value is None:
        return "—"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _count_note(component: PageComponent, lang: str) -> str:
    """What this step produced, in words, from the run's own manifest counters."""
    parts = []
    for name, template in PROVENANCE_COUNTS.get(component.key, ()):
        if name not in component.counters:
            continue
        value = component.counters[name]
        number = int(value) if float(value).is_integer() else value
        parts.append(t_(template, lang).format(n=number))
    return " · ".join(parts)


def _actor_note(component: PageComponent, lang: str) -> str:
    """Who is accountable at this step — and, when it is a model, that it is one."""
    if not component.actor or component.key not in ("scope", "page"):
        return ""
    key = f"provenance_{component.key}_actor" + (
        "_ai" if component.actor_is_stand_in else ""
    )
    note = s(key, lang).format(who=component.actor)
    # A page review is of one rendering in one language; the record says which, whenever
    # the topic manifest knows.
    if component.key == "page" and component.actor_locale:
        note += s("provenance_review_lang", lang).format(
            lang=pick(LANG_LABEL, component.actor_locale, lang)
        )
    return note


def disclosure_modal(
    components: Iterable[PageComponent],
    contributions: Iterable[Contribution],
    lang: str,
) -> str:
    """Machine-render the exact artifact lineage of this page.

    No editorial field is read here. The signed scope, pinned run ids, timestamps,
    producer versions, models and output counts come from immutable artifacts and the
    manifest ledger assembled by :func:`newsab_editorial.provenance.build_page_components`;
    the contributors come from the topic manifest. The writer's legacy
    ``how_we_counted.notes`` are deliberately never consulted.

    Content hashes are not shown. A run id already identifies a step uniquely, and a
    fingerprint only becomes useful once a reader can re-verify the artifacts it names —
    until then it was a row of noise where the model belongs.
    """
    people = "".join(
        f'<span class="prov-person">'
        f'{e(person.name or s("provenance_anonymous", lang))}'
        f'{" | " + e(person.contact) if person.contact else ""}</span>'
        for person in contributions
    )
    rows = [
        '<div class="prov-item">'
        f'<dt>{e(s("provenance_contributor", lang))}</dt>'
        f"<dd>{people}</dd></div>"
    ]
    for component in components:
        producer = component.producer
        if component.version:
            producer += f" \u00b7 {component.version}"
        model = (
            f'<span class="prov-model">{e(component.model_id)}</span>'
            if component.model_id
            else ""
        )
        notes = "".join(
            f'<span class="prov-note">{e(note)}</span>'
            for note in (_count_note(component, lang), _actor_note(component, lang))
            if note
        )
        rows.append(
            '<div class="prov-item">'
            f"<dt>{e(s(f'provenance_{component.key}', lang))}</dt><dd>"
            f'<code class="prov-run">{e(component.run_id)}</code>'
            f'<span class="prov-meta">'
            f'<time datetime="{e(_utc(component.timestamp))}">'
            f"{e(_stamp(component.timestamp))}</time>"
            f"<span>{e(producer)}</span>{model}</span>{notes}</dd></div>"
        )
    return _shell(
        "disclosuremodal",
        lang,
        f"<h4>{e(s('disclosure_title', lang))}</h4>"
        f'<p class="modal-lede">{e(s("disclosure_lede", lang))}</p>'
        f'<dl class="prov-list">{"".join(rows)}</dl>',
        wide=True,
    )
