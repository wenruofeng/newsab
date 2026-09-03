"""Product 1 — the feature matrix: independent reporting cluster × feature (§3.3 A1).

The whole point of this layer is the denominator.  A framing supported by ten articles is
a completely different fact depending on whether those are ten independent newsrooms or
one wire story reprinted ten times (D7), and the matrix is where that distinction is made
once, correctly, before any statistic is computed.

A **cell** is "this cluster's coverage carries this feature", not "how many times".  Counts
are kept alongside for diagnostics, but every prevalence figure the site publishes is a
share of clusters, so the cell is boolean by design.

Since the R-4 refactor the matrix holds **bare and attribute features only** —
the statistical pipeline.  Concept-level features contributed 92% of the old matrix and
almost nothing statistical (94% were single-cluster singletons); concepts now feed the
concept map (`newsab_a1.concept_map`), which answers "are the two sides saying the same
thing" without needing any interval.  The surface→concept mapping is still validated here
(§4.3 requires it be total), it just no longer mints features.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional, Sequence

from newsab_schema.enums import ATTR_ENUMS, Dimension
from newsab_schema.ids import group_id_of
from newsab_schema.models.analysis import Feature
from newsab_schema.models.annotation import ConceptOntology, Observation
from newsab_schema.models.corpus import Article, SourceRegistry

#: ``attrs`` keys promoted to features, per dimension.  These are the comparisons over an
#: attribute rather than a concept (§3.3 A1: "声音结构(谁被引)" and "行动者角色").
ATTR_FEATURES: dict[Dimension, str] = {
    Dimension.QUOTED_VOICE: "speaker_category",
    Dimension.ACTOR_ROLE: "actor",
    Dimension.RESPONSIBILITY: "polarity",
    Dimension.STANCE: "polarity",
}

FeatureKey = tuple[str, Optional[str], Optional[str], Optional[str]]


def shape_of(key: FeatureKey) -> str:
    """``bare`` (the dimension itself), ``attr``, or ``concept``."""
    _, concept_id, attr_key, _ = key
    if attr_key is not None:
        return "attr"
    if concept_id is not None:
        return "concept"
    return "bare"


def is_controlled(key: FeatureKey) -> bool:
    """Whether the feature is a cell of a controlled vocabulary.

    Bare dimensions and enum-valued attributes exist independently of the corpus, so
    "neither side fills this cell" is a real observation.  Free-text attributes (an
    ``actor`` name) and concepts exist *because* someone said them — reading their empty
    cells as co-silence would be circular (R-2.3).
    """
    dimension, concept_id, attr_key, _ = key
    if concept_id is not None:
        return False
    if attr_key is None:
        return True
    return (Dimension(dimension), attr_key) in ATTR_ENUMS


def controlled_feature_universe() -> list[Feature]:
    """Every feature the controlled vocabularies define, whether or not anyone filled it.

    This is the formalisation of "opportunity" behind the co-silence reading (R-2.3): the
    scan must see the empty cells, so the universe cannot be derived from the corpus.
    Deliberately excludes free-text attributes — those exist only where observed.
    """
    features = [Feature(dimension=dimension) for dimension in Dimension]
    for dimension, attr_key in ATTR_FEATURES.items():
        enum_cls = ATTR_ENUMS.get((dimension, attr_key))
        if enum_cls is None:
            continue
        features.extend(
            Feature(dimension=dimension, attr_key=attr_key, attr_value=member.value)
            for member in enum_cls
        )
    return features


def sort_key(key: FeatureKey) -> tuple[str, str, str, str]:
    """Total order over feature keys.

    Feature keys carry ``None`` in the slots that do not apply, and Python refuses to
    compare ``None`` with ``str``.  Every place that needs a deterministic feature order —
    scanning, serialisation, hashing — goes through here, because a run whose feature order
    wobbles produces a different ``a1_run_id`` for identical data.
    """
    return tuple("" if part is None else str(part) for part in key)  # type: ignore[return-value]


@dataclass(frozen=True)
class ClusterMeta:
    """What A1 needs to know about one independent reporting cluster."""

    cluster_id: str
    group_id: str
    category: str
    #: True when the cluster's publication instances span more than one source category —
    #: stratified resampling needs to know the assignment was a judgement call.
    category_mixed: bool
    source_ids: tuple[str, ...]
    article_ids: tuple[str, ...]
    #: The article whose category was adopted for the cluster (see `_representative`).
    representative_article_id: str
    #: The matching source.  This must not be reconstructed as the alphabetically first
    #: source in a syndicated cluster: source diversity uses the reporting representative,
    #: not an arbitrary publication instance.
    representative_source_id: str

    def to_dict(self) -> dict:
        return asdict(self)


def _representative(articles: Sequence[Article]) -> Article:
    """Which article speaks for a cluster when its members disagree.

    Rule, in order: the single article declared ``origin=original`` if there is exactly
    one; otherwise the earliest published; ties broken by article_id.  Deterministic and
    boring on purpose — a cluster's category decides which stratum it lands in, and a
    stratum assignment that shifts between runs would make ``bootstrap_stability``
    meaningless.
    """
    originals = [a for a in articles if a.is_independent]
    if len(originals) == 1:
        return originals[0]
    return sorted(articles, key=lambda a: (a.publish_date, a.article_id))[0]


def build_cluster_meta(
    articles: Iterable[Article], sources: SourceRegistry
) -> dict[str, ClusterMeta]:
    grouped: dict[str, list[Article]] = {}
    for article in articles:
        grouped.setdefault(article.reporting_cluster_id, []).append(article)

    meta: dict[str, ClusterMeta] = {}
    for cluster_id, members in sorted(grouped.items()):
        members = sorted(members, key=lambda a: a.article_id)
        rep = _representative(members)
        categories = {sources.by_id(a.source_id).category.value for a in members}
        meta[cluster_id] = ClusterMeta(
            cluster_id=cluster_id,
            group_id=group_id_of(rep.article_id),
            category=sources.by_id(rep.source_id).category.value,
            category_mixed=len(categories) > 1,
            source_ids=tuple(sorted({a.source_id for a in members})),
            article_ids=tuple(a.article_id for a in members),
            representative_article_id=rep.article_id,
            representative_source_id=rep.source_id,
        )
    return meta


def observation_features(obs: Observation, concept_id: Optional[str]) -> list[Feature]:
    """Every feature one observation contributes to.

    An observation always contributes to its dimension's salience feature (concept-free)
    and to an attribute feature when its dimension has one worth comparing.  It does
    **not** contribute a concept feature any more (R-4): concepts are aggregated by the
    concept map, at topic level, outside the Δ pipeline.  ``concept_id`` stays in the
    signature because the caller has already resolved it and a future diagnostic may want
    it; it is deliberately unused here.
    """
    del concept_id
    features = [Feature(dimension=obs.dimension)]
    attr_key = ATTR_FEATURES.get(obs.dimension)
    if attr_key:
        value = obs.attrs.get(attr_key)
        if value not in (None, ""):
            features.append(
                Feature(dimension=obs.dimension, attr_key=attr_key, attr_value=str(value))
            )
    return features


@dataclass
class FeatureMatrix:
    """Cluster × feature support, plus the cluster metadata every metric needs."""

    topic_id: str
    ontology_version: Optional[str]
    clusters: dict[str, ClusterMeta] = field(default_factory=dict)
    #: (feature_key, cluster_id) -> number of observations backing that cell.
    cells: dict[tuple[FeatureKey, str], int] = field(default_factory=dict)
    #: feature_key -> the Feature object, so callers never rebuild one from a tuple.
    features: dict[FeatureKey, Feature] = field(default_factory=dict)
    #: (feature_key, cluster_id) -> observation IDs, for evidence hand-off to S6/S7.
    support_observations: dict[tuple[FeatureKey, str], list[str]] = field(default_factory=dict)
    #: Observations that could not be placed, with the reason.
    skipped: list[tuple[str, str]] = field(default_factory=list)

    # -- construction ------------------------------------------------------------------

    def add(self, feature: Feature, cluster_id: str, observation_id: str) -> None:
        key = feature.key
        self.features.setdefault(key, feature)
        cell = (key, cluster_id)
        self.cells[cell] = self.cells.get(cell, 0) + 1
        self.support_observations.setdefault(cell, []).append(observation_id)

    # -- queries -----------------------------------------------------------------------

    def group_ids(self) -> list[str]:
        return sorted({c.group_id for c in self.clusters.values()})

    def clusters_in(self, group_id: str, category: Optional[str] = None) -> list[str]:
        return sorted(
            cid
            for cid, meta in self.clusters.items()
            if meta.group_id == group_id and (category is None or meta.category == category)
        )

    def supporting(
        self, feature_key: FeatureKey, group_id: str, category: Optional[str] = None
    ) -> list[str]:
        """Clusters in ``group_id`` whose coverage carries the feature."""
        return [
            cid
            for cid in self.clusters_in(group_id, category)
            if (feature_key, cid) in self.cells
        ]

    def prevalence(
        self, feature_key: FeatureKey, group_id: str, category: Optional[str] = None
    ) -> Optional[float]:
        """Share of clusters carrying the feature, or ``None`` when there is no denominator.

        ``None`` rather than ``0.0``: a group with no clusters in a category has an absent
        measurement, and §1.5 requires that be shown as "sample too small", never as zero.
        """
        total = len(self.clusters_in(group_id, category))
        if total == 0:
            return None
        return len(self.supporting(feature_key, group_id, category)) / total

    def categories(self, group_id: Optional[str] = None) -> list[str]:
        return sorted(
            {
                meta.category
                for meta in self.clusters.values()
                if group_id is None or meta.group_id == group_id
            }
        )

    def observation_ids(self, feature_key: FeatureKey, group_id: str) -> list[str]:
        out: list[str] = []
        for cid in self.supporting(feature_key, group_id):
            out.extend(self.support_observations.get((feature_key, cid), []))
        return sorted(out)

    def source_ids_supporting(self, feature_key: FeatureKey, group_id: str) -> list[str]:
        """The representative source of each supporting cluster — the input to diversity."""
        return [
            self.clusters[cid].source_ids[0]
            if len(self.clusters[cid].source_ids) == 1
            else self._representative_source(cid)
            for cid in self.supporting(feature_key, group_id)
        ]

    def _representative_source(self, cluster_id: str) -> str:
        return self.clusters[cluster_id].representative_source_id

    def group_source_count(self, group_id: str) -> int:
        """Distinct sources present in this group's corpus — the diversity normaliser."""
        return len(
            {
                source
                for meta in self.clusters.values()
                if meta.group_id == group_id
                for source in meta.source_ids
            }
        )

    # -- serialisation ------------------------------------------------------------------

    def rows(self) -> list[dict]:
        """Long-format rows: one per non-empty cell.  This is what gets persisted."""
        out: list[dict] = []
        for (feature_key, cluster_id), count in self.cells.items():
            feature = self.features[feature_key]
            meta = self.clusters[cluster_id]
            out.append(
                {
                    "group_id": meta.group_id,
                    "cluster_id": cluster_id,
                    "category": meta.category,
                    "category_mixed": meta.category_mixed,
                    "dimension": feature.dimension.value,
                    "concept_id": feature.concept_id,
                    "attr_key": feature.attr_key,
                    "attr_value": feature.attr_value,
                    "observations": count,
                    "articles": len(meta.article_ids),
                }
            )
        return sorted(
            out,
            key=lambda r: (
                r["group_id"],
                r["dimension"],
                r["concept_id"] or "",
                r["attr_key"] or "",
                r["attr_value"] or "",
                r["cluster_id"],
            ),
        )

    def summary(self) -> dict:
        counts = Counter(meta.group_id for meta in self.clusters.values())
        return {
            "topic_id": self.topic_id,
            "ontology_version": self.ontology_version,
            "clusters": dict(sorted(counts.items())),
            "features": len(self.features),
            "cells": len(self.cells),
            "skipped_observations": len(self.skipped),
        }


def build_feature_matrix(
    observations: Sequence[Observation],
    articles: Sequence[Article],
    sources: SourceRegistry,
    ontology: Optional[ConceptOntology] = None,
    *,
    topic_id: Optional[str] = None,
) -> FeatureMatrix:
    """Fold observations up to the cluster level (§3.3 A1, product 1)."""
    by_article = {a.article_id: a for a in articles}
    clusters = build_cluster_meta(articles, sources)
    matrix = FeatureMatrix(
        topic_id=topic_id or (articles[0].topic_id if articles else ""),
        ontology_version=ontology.ontology_version if ontology else None,
        clusters=clusters,
    )

    surface_map = ontology.surface_map() if ontology else {}

    for obs in observations:
        article = by_article.get(obs.article_id)
        if article is None:
            matrix.skipped.append((obs.observation_id, "article not in corpus"))
            continue
        concept_id = surface_map.get((obs.concept_surface, obs.proposition.lang))
        if ontology is not None and concept_id is None:
            # A surface with no concept cannot be compared across sides; §4.3 requires the
            # mapping to be total, so this is a data error rather than something to guess.
            matrix.skipped.append(
                (obs.observation_id, f"concept_surface {obs.concept_surface!r} unmapped")
            )
            continue
        for feature in observation_features(obs, concept_id):
            matrix.add(feature, article.reporting_cluster_id, obs.observation_id)

    return matrix
