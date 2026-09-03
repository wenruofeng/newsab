"""Orchestration: observations in, a reproducible analysis run out.

``a1_run_id`` is the promise the whole submission model rests on (AGENTS.md §7): every
number on a page must be recomputable from it.  So it is derived from the things that can
change a number — the feature matrix contents, the configuration, and the package version —
and nothing else.  Two runs on identical inputs produce the same digest suffix and the same
numbers, while their timestamp components keep the immutable run directories distinct.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

from newsab_schema.ids import group_id_of
from newsab_schema.models.analysis import CandidateAngle, Feature
from newsab_schema.models.annotation import ConceptOntology, Observation
from newsab_schema.models.corpus import Article, SourceRegistry
from newsab_schema.validate import validate_observations

from .concept_map import build_concept_map
from .features import FeatureMatrix, build_feature_matrix
from .metrics import PACKAGE_VERSION, signed_difference_interval
from .scan import DELTA_METHOD, Candidate, ScanConfig, scan_all
from .storage import read_matrix, rows_digest, write_matrix


@dataclass
class A1Run:
    """A completed analysis run and its artifacts."""

    a1_run_id: str
    topic_id: str
    matrix: FeatureMatrix
    candidates: list[Candidate]
    config: ScanConfig
    groups: tuple[str, str]
    #: The descriptive concept layer (R-4), built alongside when an ontology exists.
    #: Not part of the run digest: it is derived from the same pinned observations but
    #: carries no gated number.
    concept_map: Optional[dict] = None
    storage: dict = field(default_factory=dict)
    created_at: Optional[str] = None

    def run_record(self) -> dict:
        return {
            "a1_run_id": self.a1_run_id,
            "topic_id": self.topic_id,
            "package_version": PACKAGE_VERSION,
            "ontology_version": self.matrix.ontology_version,
            "groups": list(self.groups),
            "config": self.config.to_dict(),
            "matrix": self.matrix.summary(),
            "storage": self.storage,
            "candidates": len(self.candidates),
            "concept_map": (self.concept_map or {}).get("summary"),
            "created_at": self.created_at,
            "skipped_observations": self.matrix.skipped,
        }


def compute_run_id(matrix: FeatureMatrix, config: ScanConfig, groups: Sequence[str]) -> str:
    """``a1-{yyyymmddHHMMssffffff}-{8 hex}``.

    The hex digest covers the matrix rows, the cluster metadata, the configuration, the
    group pair and the package version — i.e. everything a metric depends on.  The
    timestamp makes runs sortable but takes no part in the digest, so a re-run on identical
    inputs is *recognisably* the same analysis even though its id differs.
    """
    digest = compute_analysis_digest(matrix, config, groups)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"a1-{stamp}-{digest}"


def compute_analysis_digest(
    matrix: FeatureMatrix, config: ScanConfig, groups: Sequence[str]
) -> str:
    """Input/config digest embedded in an A1 run id, independent of its timestamp."""
    payload = json.dumps(
        {
            "rows": matrix.rows(),
            "clusters": {cid: meta.to_dict() for cid, meta in sorted(matrix.clusters.items())},
            "config": config.to_dict(),
            "groups": list(groups),
            "package_version": PACKAGE_VERSION,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


def analyse(
    observations: Sequence[Observation],
    articles: Sequence[Article],
    sources: SourceRegistry,
    ontology: Optional[ConceptOntology] = None,
    *,
    topic_id: Optional[str] = None,
    groups: Optional[tuple[str, str]] = None,
    config: Optional[ScanConfig] = None,
) -> A1Run:
    """Build the matrix, scan for candidates, attach the run id."""
    config = config or ScanConfig()
    effective_topic = topic_id or (articles[0].topic_id if articles else "")
    # The source registry is cross-topic (R-3), so there is no topic to check it against;
    # what still has to hold is that every article's source is in it and lands on the side
    # its group says it does, which is checked per article below.
    if ontology is not None and ontology.topic_id != effective_topic:
        raise ValueError(f"ontology belongs to {ontology.topic_id}, not {effective_topic}")
    source_by_id = {source.id: source for source in sources.sources}
    for article in articles:
        if article.topic_id != effective_topic:
            raise ValueError(
                f"article {article.article_id} belongs to {article.topic_id}, not {effective_topic}"
            )
        source = source_by_id.get(article.source_id)
        if source is None:
            raise ValueError(
                f"article {article.article_id} references unknown source {article.source_id}"
            )
        if article.lang != source.lang:
            raise ValueError(
                f"article {article.article_id} group/language does not match source "
                f"{source.id} ({source.country}/{source.lang})"
            )
    validation = validate_observations(observations, articles, ontology)
    if validation.errors:
        details = "; ".join(
            f"{finding.code}:{finding.target}" for finding in validation.errors[:10]
        )
        raise ValueError(
            "A1 refuses observations that fail S4 invariants; fix them before computing "
            f"statistics ({details})"
        )
    matrix = build_feature_matrix(observations, articles, sources, ontology, topic_id=topic_id)

    available = matrix.group_ids()
    if groups is None:
        if len(available) != 2:
            raise ValueError(
                f"expected exactly two groups in the corpus, found {available}; pass "
                "groups=(a, b) explicitly for a multi-group topic"
            )
        groups = (available[0], available[1])
    for group in groups:
        if group not in available:
            raise ValueError(f"group {group!r} has no clusters in this corpus (have {available})")

    candidates = scan_all(matrix, groups[0], groups[1], config)
    run_id = compute_run_id(matrix, config, groups)
    for candidate in candidates:
        candidate.a1_run_id = run_id

    concept_map = (
        build_concept_map(
            observations,
            articles,
            sources,
            ontology,
            topic_id=matrix.topic_id,
            groups=groups,
        )
        if ontology is not None
        else None
    )

    return A1Run(
        a1_run_id=run_id,
        topic_id=matrix.topic_id,
        matrix=matrix,
        candidates=candidates,
        config=config,
        groups=groups,
        concept_map=concept_map,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def write_run(run: A1Run, analysis_dir: Path) -> Path:
    """Write the run's artifacts into ``analysis/<a1_run_id>/`` and return that directory."""
    run_dir = Path(analysis_dir) / run.a1_run_id
    analysis_dir = Path(analysis_dir)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)

    # run.json first without storage, so read_matrix can find topic_id if anything fails
    # midway; then rewritten with the storage record.
    (run_dir / "run.json").write_text(
        json.dumps(run.run_record(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    run.storage = write_matrix(run.matrix, run_dir)
    (run_dir / "run.json").write_text(
        json.dumps(run.run_record(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with open(run_dir / "candidates.jsonl", "w", encoding="utf-8") as fh:
        for candidate in run.candidates:
            fh.write(
                json.dumps(candidate.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
            )
    if run.concept_map is not None:
        (run_dir / "concept_map.json").write_text(
            json.dumps(run.concept_map, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return run_dir


# --------------------------------------------------------------------------------------
# Recomputation — §4.4.1 invariant 1
# --------------------------------------------------------------------------------------


class Recomputer:
    """Re-derives an angle's metrics from a stored A1 run.

    This is the hook ``newsab_schema.validate.validate_angles`` asks for.  Without it that
    validator only checks that a number is *present*; with it, every published figure is
    re-derived from the matrix, which is what makes a submission reviewable by someone who
    trusts nothing in it (AGENTS.md §7).
    """

    def __init__(self, run_dir: Path | str) -> None:
        self.run_dir = Path(run_dir)
        self.record = json.loads((self.run_dir / "run.json").read_text(encoding="utf-8"))
        self.matrix = read_matrix(self.run_dir)
        self.config = ScanConfig(**self.record["config"])
        self.groups = tuple(self.record["groups"])

    def matrix_is_intact(self) -> bool:
        """Whether rows *and cluster metadata* still match the run id's input digest."""
        rows_ok = rows_digest(self.matrix.rows()) == self.record["storage"]["rows_digest"]
        digest = compute_analysis_digest(self.matrix, self.config, self.groups)
        return rows_ok and self.record["a1_run_id"].rsplit("-", 1)[-1] == digest

    def for_feature(
        self, feature: Feature, group_a: str, group_b: str
    ) -> dict[str, Optional[float]]:
        if not self.matrix_is_intact():
            raise ValueError(
                f"stored A1 run {self.run_dir} fails its input digest; refusing to "
                "recompute from mutated artifacts"
            )
        key = feature.key
        from .features import is_controlled

        if key not in self.matrix.features and not is_controlled(key):
            raise KeyError(
                f"feature {feature.label()} is not in run {self.record['a1_run_id']} and "
                "is not a controlled-vocabulary cell; the angle references an analysis "
                "this directory did not produce"
            )
        interval = signed_difference_interval(
            self.matrix,
            key,
            group_a,
            group_b,
            n_resamples=self.config.n_resamples,
            seed=self.config.seed,
            level=self.config.interval_level,
            stratified=self.config.stratified,
            diversity_method=self.config.diversity_method,
        )
        out: dict[str, Optional[float]] = {
            "delta": interval.delta,
            "delta_lo": interval.lo,
            "delta_hi": interval.hi,
            "direction_stability": interval.direction_stability,
            "conservative_effect": interval.conservative_effect,
            "log_odds": interval.log_odds,
            f"prevalence.{group_a}": interval.p_a,
            f"prevalence.{group_b}": interval.p_b,
        }
        for group in (group_a, group_b):
            out[f"clusters_supporting.{group}"] = float(
                len(self.matrix.supporting(key, group))
            )
            out[f"clusters_total.{group}"] = float(len(self.matrix.clusters_in(group)))
            for category in self.matrix.categories():
                category_total = len(self.matrix.clusters_in(group, category))
                if category_total == 0:
                    continue
                out[f"by_category_supporting.{group}.{category}"] = float(
                    len(self.matrix.supporting(key, group, category))
                )
                out[f"by_category_total.{group}.{category}"] = float(
                    category_total
                )
            out[f"concentration.{group}"] = interval.concentration.get(group)
        return out

    def __call__(self, angle: CandidateAngle) -> dict[str, Optional[float]]:
        group_ids = angle.group_ids
        if angle.metrics.a1_run_id != self.record["a1_run_id"]:
            raise ValueError(
                f"angle names a1_run_id={angle.metrics.a1_run_id}, but recomputation uses "
                f"{self.record['a1_run_id']}"
            )
        if tuple(group_ids) != self.groups:
            raise ValueError(
                f"angle compares {group_ids}, but run compares {list(self.groups)}"
            )
        expected_diversity = f"{PACKAGE_VERSION}/{self.config.diversity_method}"
        if angle.metrics.delta.method != DELTA_METHOD:
            raise ValueError(
                f"angle delta method is {angle.metrics.delta.method}, run uses {DELTA_METHOD}"
            )
        if angle.metrics.concentration.method != expected_diversity:
            raise ValueError(
                f"angle concentration method is {angle.metrics.concentration.method}, "
                f"run uses {expected_diversity}"
            )
        resampling = angle.metrics.resampling
        expected_scheme = (
            "stratified_by_category_over_clusters"
            if self.config.stratified
            else "simple_over_clusters"
        )
        if (resampling.n_resamples, resampling.seed, resampling.scheme) != (
            self.config.n_resamples,
            self.config.seed,
            expected_scheme,
        ):
            raise ValueError(
                "angle resampling configuration does not match the stored A1 run"
            )
        if angle.metrics.delta.level != self.config.interval_level:
            raise ValueError(
                f"angle interval level {angle.metrics.delta.level} does not match the "
                f"stored A1 run's {self.config.interval_level}"
            )
        return self.for_feature(angle.comparison.feature, group_ids[0], group_ids[1])


def recompute_metrics(
    run_dir: Path | str,
) -> Callable[[CandidateAngle], dict[str, Optional[float]]]:
    """Convenience: ``validate_angles(..., recompute=recompute_metrics(run_dir))``."""
    return Recomputer(run_dir)
