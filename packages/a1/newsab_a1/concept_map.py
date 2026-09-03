"""The concept map — the descriptive concept layer, outside the Δ pipeline (R-4).

The ontology's concepts carried two identities jammed into one field: a statistical
feature ("what share of clusters mention X") and a descriptive vocabulary ("what words
does each side use for this").  The first needs multi-cluster support that 94% of
concepts never have; the second is informative at a single mention.  The old pipeline
served the first identity and silently discarded the second through its support floor.

This module serves the second identity, whole: **every** concept is kept, tagged, and
made filterable.  No intervals, no thresholds — "the same claim appears on both sides"
is established by exhibiting the sentences, not by estimating a rate (G-5: with ten
clusters the statistics cannot see what two articles can show).  This is where the
``shared_ground`` reading gets its default evidence (R-5): the ``side == "both"``
concepts, each with sentence-level anchors on both sides.

Every tag is derived from existing annotations — nothing here requires re-annotation or
a model call.  ``is_quoted`` and ``speaker_categories`` come from sentence-anchor
overlap with ``quoted_voice`` observations: a concept whose evidence sentences also
carry a quoted voice was (at least partly) said by a source, not by the newsroom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from newsab_schema.enums import CreditBlame, Dimension, StancePolarity, Valence, coerce_valence
from newsab_schema.models.annotation import ConceptOntology, Observation
from newsab_schema.models.corpus import Article, SourceRegistry

from .features import build_cluster_meta
from .metrics import PACKAGE_VERSION

#: How many example observation IDs to carry per concept per side.
MAX_EXAMPLES = 3


def _valence_of(obs: Observation) -> Optional[str]:
    """Fold the three polarity-ish attrs into one positive/negative/mixed reading."""
    if obs.dimension == Dimension.CONSEQUENCE:
        v = coerce_valence(obs.attrs["valence"])
        return {Valence.POSITIVE: "positive", Valence.NEGATIVE: "negative", Valence.MIXED: "mixed"}[v]
    if obs.dimension == Dimension.STANCE:
        p = StancePolarity(obs.attrs["polarity"])
        if p == StancePolarity.SUPPORT:
            return "positive"
        if p == StancePolarity.OPPOSE:
            return "negative"
        if p == StancePolarity.AMBIVALENT:
            return "mixed"
        return None  # neutral carries no valence
    if obs.dimension == Dimension.RESPONSIBILITY:
        return "positive" if CreditBlame(obs.attrs["polarity"]) == CreditBlame.CREDIT else "negative"
    return None


def _fold_valences(values: set[str]) -> Optional[str]:
    if not values:
        return None
    if "mixed" in values or {"positive", "negative"} <= values:
        return "mixed"
    return next(iter(values))


@dataclass
class ConceptEntry:
    concept_id: str
    label: dict
    #: ``both`` or the single group id that mentions it — the map's core geometry.
    side: str
    dimensions: list[str]
    #: ``article_voice`` / ``quoted`` / ``both`` — whether the newsroom said it, a
    #: quoted source said it, or both.
    is_quoted: Optional[str]
    speaker_categories: list[str]
    valence: Optional[str]
    #: group -> {source_category: supporting cluster count} — same-side contrast.
    source_categories: dict[str, dict[str, int]]
    #: group -> supporting cluster count.  ``1`` marks a single newsroom's own wording —
    #: a tag, never a threshold (the old pipeline's support floor is exactly what R-4
    #: removed).
    cluster_count: dict[str, int]
    #: group -> supporting/total share.  Word-cloud sizing MUST use this, not the raw
    #: count: with cn 10 / us 24 clusters the same single mention is 10% vs 4%, and raw
    #: counts would make the larger corpus look louder across the board.
    cluster_share: dict[str, float]
    #: group -> earliest publish date (ISO) — the longitudinal hook (D17).
    first_seen: dict[str, Optional[str]]
    surfaces: list[dict] = field(default_factory=list)
    #: group -> representative observation IDs (sentence anchors travel with them).
    examples: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "concept_id": self.concept_id,
            "label": self.label,
            "side": self.side,
            "dimensions": self.dimensions,
            "is_quoted": self.is_quoted,
            "speaker_categories": self.speaker_categories,
            "valence": self.valence,
            "source_categories": self.source_categories,
            "cluster_count": self.cluster_count,
            "cluster_share": self.cluster_share,
            "first_seen": self.first_seen,
            "surfaces": self.surfaces,
            "examples": self.examples,
        }


def build_concept_map(
    observations: Sequence[Observation],
    articles: Sequence[Article],
    sources: SourceRegistry,
    ontology: ConceptOntology,
    *,
    topic_id: Optional[str] = None,
    groups: Optional[Iterable[str]] = None,
) -> dict:
    """Aggregate every concept to topic level, across dimensions, with its nine tags.

    Concept identity is ``concept_id`` alone — the ontology was always cross-dimensional
    (its keys are ``(surface, lang)``); it was the old feature matrix that sliced
    concepts by dimension, and that slicing ends here (R-4).
    """
    by_article = {a.article_id: a for a in articles}
    clusters = build_cluster_meta(articles, sources)
    surface_map = ontology.surface_map()

    group_ids = sorted(groups) if groups else sorted({m.group_id for m in clusters.values()})
    totals = {
        g: sum(1 for m in clusters.values() if m.group_id == g) for g in group_ids
    }

    #: sentence id -> speaker categories quoted there (from quoted_voice observations).
    quoted_sentences: dict[str, set[str]] = {}
    for obs in observations:
        if obs.dimension == Dimension.QUOTED_VOICE:
            category = str(obs.attrs.get("speaker_category", ""))
            for sid in obs.evidence:
                quoted_sentences.setdefault(sid, set()).add(category)

    @dataclass
    class _Acc:
        dimensions: set = field(default_factory=set)
        quoted: bool = False
        article_voice: bool = False
        speakers: set = field(default_factory=set)
        valences: set = field(default_factory=set)
        clusters: dict = field(default_factory=dict)  # group -> set of cluster ids
        categories: dict = field(default_factory=dict)  # group -> {category: cluster set}
        first_seen: dict = field(default_factory=dict)  # group -> date
        examples: dict = field(default_factory=dict)  # group -> [obs ids]

    accs: dict[str, _Acc] = {}

    for obs in observations:
        concept_id = surface_map.get((obs.concept_surface, obs.proposition.lang))
        if concept_id is None:
            continue
        article = by_article.get(obs.article_id)
        if article is None:
            continue
        meta = clusters[article.reporting_cluster_id]
        acc = accs.setdefault(concept_id, _Acc())
        acc.dimensions.add(obs.dimension.value)
        in_quote = obs.dimension == Dimension.QUOTED_VOICE or any(
            sid in quoted_sentences for sid in obs.evidence
        )
        if in_quote:
            acc.quoted = True
            if obs.dimension == Dimension.QUOTED_VOICE:
                acc.speakers.add(str(obs.attrs.get("speaker_category", "")))
            for sid in obs.evidence:
                acc.speakers.update(quoted_sentences.get(sid, set()))
        else:
            acc.article_voice = True
        valence = _valence_of(obs)
        if valence:
            acc.valences.add(valence)
        group = meta.group_id
        acc.clusters.setdefault(group, set()).add(meta.cluster_id)
        acc.categories.setdefault(group, {}).setdefault(meta.category, set()).add(
            meta.cluster_id
        )
        seen = acc.first_seen.get(group)
        date = str(article.publish_date)
        if seen is None or date < seen:
            acc.first_seen[group] = date
        examples = acc.examples.setdefault(group, [])
        if len(examples) < MAX_EXAMPLES:
            examples.append(obs.observation_id)

    entries: list[ConceptEntry] = []
    for concept in ontology.concepts:
        acc = accs.get(concept.concept_id)
        if acc is None:
            # In the ontology but not in this observation set (e.g. a different corpus
            # run).  Skipped rather than shown as universal silence.
            continue
        mentioned = sorted(g for g in acc.clusters if acc.clusters[g])
        side = "both" if len(mentioned) > 1 else mentioned[0]
        if acc.quoted and acc.article_voice:
            is_quoted = "both"
        elif acc.quoted:
            is_quoted = "quoted"
        else:
            is_quoted = "article_voice"
        entries.append(
            ConceptEntry(
                concept_id=concept.concept_id,
                label=concept.label.model_dump(mode="json"),
                side=side,
                dimensions=sorted(acc.dimensions),
                is_quoted=is_quoted,
                speaker_categories=sorted(s for s in acc.speakers if s),
                valence=_fold_valences(acc.valences),
                source_categories={
                    g: {c: len(ids) for c, ids in sorted(cats.items())}
                    for g, cats in sorted(acc.categories.items())
                },
                cluster_count={g: len(acc.clusters.get(g, ())) for g in group_ids},
                cluster_share={
                    g: (len(acc.clusters.get(g, ())) / totals[g]) if totals[g] else 0.0
                    for g in group_ids
                },
                first_seen={g: acc.first_seen.get(g) for g in group_ids},
                surfaces=[
                    {"text": s.text, "lang": s.lang, "example_obs": s.example_obs}
                    for s in concept.surfaces
                ],
                examples={g: list(v) for g, v in sorted(acc.examples.items())},
            )
        )

    entries.sort(key=lambda e: (e.side != "both", -max(e.cluster_share.values()), e.concept_id))
    return {
        "topic_id": topic_id or ontology.topic_id,
        "ontology_version": ontology.ontology_version,
        "package_version": PACKAGE_VERSION,
        "groups": group_ids,
        "clusters_total": totals,
        "concepts": [e.to_dict() for e in entries],
        "summary": {
            "concepts": len(entries),
            "both_sides": sum(1 for e in entries if e.side == "both"),
            "single_newsroom": sum(
                1 for e in entries if max(e.cluster_count.values()) == 1
            ),
        },
    }
