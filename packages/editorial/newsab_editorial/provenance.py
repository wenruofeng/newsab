"""Build the machine-owned provenance record shown for one rendered page."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Mapping, Optional

from newsab_schema.common import GateDecider
from newsab_schema.models.corpus import TopicManifest
from newsab_schema.models.manifest import ManifestEntry
from newsab_schema.models.page import ReaderPage


@dataclass(frozen=True)
class PageComponent:
    """One immutable input or page snapshot named by the page record."""

    key: str
    run_id: str
    timestamp: Optional[datetime]
    producer: str
    version: Optional[str] = None
    #: The model that did this step's judging, or ``None`` when the step did none.  A
    #: deterministic stage records ``model_id: null`` on purpose (D10); the renderer says
    #: nothing at all rather than claiming an absence the reader did not ask about.
    model_id: Optional[str] = None
    #: The step's own output counters, straight from the manifest entry.  What a reader
    #: can hold this run to: how many articles, questions, answers, findings it produced.
    counters: Mapping[str, float] = field(default_factory=dict)
    #: The person (or stand-in model) accountable at this step — signing scope, or taking
    #: the page review.  Empty for the machine steps in between.
    actor: Optional[str] = None
    #: True when ``actor`` is a model standing in for the user: the
    #: stand-in fact has to reach the published record, not only the manifest.
    actor_is_stand_in: bool = False
    #: The language the reviewer read this page in, when the topic manifest names one.
    actor_locale: Optional[str] = None


@dataclass(frozen=True)
class Contribution:
    """One human answerable for this topic, as the page record names them."""

    name: Optional[str] = None
    contact: Optional[str] = None


def page_contributions(manifest: TopicManifest) -> list[Contribution]:
    """The topic's contributors, or a single anonymous row when none is recorded."""
    if not manifest.contributors:
        return [Contribution()]
    return [Contribution(c.name, c.contact) for c in manifest.contributors]


def _human_actor(manifest: TopicManifest) -> Optional[str]:
    names = [c.name for c in page_contributions(manifest) if c.name]
    return " · ".join(names) if names else None


def build_page_components(
    page: ReaderPage,
    manifest: TopicManifest,
    entries: Iterable[ManifestEntry],
) -> list[PageComponent]:
    """Return the exact pinned lineage in display order.

    The page retains four legacy pointer fields because checks use them to prove that its
    numbers were recomputed from the run it names. Everything displayed here is derived
    from those pointers, the signed scope, and the append-only manifest ledger; the
    writer's legacy ``how_we_counted.notes`` are deliberately never consulted.
    """
    by_id = {entry.run_id: entry for entry in entries}
    qa_entry = by_id.get(page.how_we_counted.qa_run_id)

    def lineage_run(prefix: str, fallback: str) -> str:
        if qa_entry:
            pinned = next(
                (run_id for run_id in qa_entry.inputs if run_id.startswith(prefix)),
                None,
            )
            if pinned:
                return pinned
        return fallback

    def from_run(key: str, run_id: str, producer: str) -> PageComponent:
        entry = by_id.get(run_id)
        return PageComponent(
            key=key,
            run_id=run_id,
            timestamp=entry.timestamp if entry else None,
            producer=entry.skill_id if entry else producer,
            version=entry.skill_version if entry else None,
            model_id=entry.model_id if entry else None,
            counters=dict(entry.counters) if entry else {},
        )

    scope = manifest.scope_approval
    scope_timestamp = scope.approved_at if scope else manifest.provenance.timestamp
    scope_stand_in = bool(scope and scope.decided_by == GateDecider.LLM_STAND_IN)
    scope_actor = (
        scope.stand_in_model_id
        if scope_stand_in and scope
        else _human_actor(manifest) or (scope.approved_by if scope else None)
    )
    components = [
        PageComponent(
            key="scope",
            run_id=manifest.provenance.run_id,
            timestamp=scope_timestamp,
            producer="scope",
            version=manifest.provenance.skill_version,
            model_id=manifest.provenance.model_id,
            actor=scope_actor,
            actor_is_stand_in=scope_stand_in,
        ),
        from_run(
            "corpus", lineage_run("s2s-", page.how_we_counted.corpus_run_id), "collect"
        ),
        from_run(
            "questions",
            lineage_run("qst-", page.how_we_counted.questions_run_id),
            "annotate",
        ),
        from_run(
            "answers",
            lineage_run("ans-", page.how_we_counted.answers_run_id),
            "annotate",
        ),
    ]

    normalization_id = None
    if qa_entry:
        normalization_id = next(
            (
                run_id
                for run_id in qa_entry.inputs
                if (
                    (by_id.get(run_id) and by_id[run_id].skill_id == "normalize")
                    or run_id.startswith("nrm-")
                )
            ),
            None,
        )
        normalization_id = normalization_id or qa_entry.metadata.get(
            "category_map_run_id"
        )
    if normalization_id:
        components.append(from_run("normalization", normalization_id, "normalize"))

    components.append(from_run("analysis", page.how_we_counted.qa_run_id, "analyze"))

    # The run that wrote these sentences is not the run that rendered them: since the
    # write and render-localize stages split, ``page.provenance`` names the renderer, and
    # the model that did the writing was reachable only by walking the ledger.  A reader
    # asking "who wrote this" deserves an answer, so walk it.
    write_id = _first_ancestor(by_id, page.provenance.run_id, "write")
    if write_id and write_id != page.provenance.run_id:
        components.append(from_run("write", write_id, "write"))

    page_entry = by_id.get(page.provenance.run_id)
    review_stand_in = manifest.review_stand_in_model_id
    components.append(
        PageComponent(
            key="page",
            run_id=page.provenance.run_id,
            timestamp=page_entry.timestamp if page_entry else page.provenance.timestamp,
            producer=(
                page_entry.skill_id
                if page_entry
                else "render-localize"
                if page.provenance.run_id.startswith("rl-")
                else "write"
            ),
            version=page_entry.skill_version
            if page_entry
            else page.provenance.skill_version,
            model_id=page_entry.model_id if page_entry else page.provenance.model_id,
            counters=dict(page_entry.counters) if page_entry else {},
            actor=review_stand_in or _human_actor(manifest),
            actor_is_stand_in=bool(review_stand_in),
            actor_locale=manifest.review_locale,
        )
    )
    return components


def _first_ancestor(
    by_id: Mapping[str, ManifestEntry], start: str, skill_id: str
) -> Optional[str]:
    """Nearest run of ``skill_id`` reachable from ``start`` through ``inputs`` edges."""
    queue: deque[str] = deque([start])
    seen: set[str] = set()
    while queue:
        run_id = queue.popleft()
        if run_id in seen:
            continue
        seen.add(run_id)
        entry = by_id.get(run_id)
        if entry is None:
            continue
        if entry.skill_id == skill_id:
            return run_id
        queue.extend(entry.inputs)
    return None
