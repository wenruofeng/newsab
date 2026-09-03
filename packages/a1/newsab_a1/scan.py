"""Product 2 — the exhaustive Δ scan over the bare/attr feature universe (§3.3 A1, R-3).

Every feature gets the same treatment: one signed-difference interval
(:func:`newsab_a1.metrics.signed_difference_interval`).  Discovery is exhaustive and dumb
on purpose: reading the interval is the R-gate's job (S6, code) and interestingness is the
E-score's (S6, LLM).  Keeping discovery judgement-free is what makes D8's ordering
meaningful — the editorial layer can only ever remove candidates, never resurrect one.

Three things the old scan did that this one deliberately does not:

* **No per-angle-type scan domains.** The old ``SCAN_SHAPES`` table decided which features
  each angle family was allowed to see.  It had no blueprint basis — §3.3 A1 defines eight
  angle *types*, not eight scan domains — and it was the direct cause of G-4
  (``shared_ground`` candidates were structurally impossible).  Angle types are now labels
  derived from the feature (:func:`structural_angle_type`); ``shared_ground`` and
  ``co_silence`` are not scan families but *readings* of the same interval, attached by
  the R-gate; ``blind_spot`` keeps its special-cased four-condition path in S6.
* **No concept-level features.** 94% of them were single-cluster singletons — they
  produce no statistics and they drowned the artifact (R-4).  Concepts feed the concept
  map instead, which is where "are the two sides saying the same thing" gets its
  evidence (G-5).
* **No support floor.** The full data layer is published (R-8), so a one-cluster attribute
  feature is a data row, not noise to suppress.  The scan also *enumerates* the controlled
  vocabularies rather than only observed features (R-2.3): a ``speaker_category`` cell
  that no observation filled is a real measurement — "neither side quotes
  foreign-government voices" — and co-silence is only a finding when the opportunity (the
  vocabulary cell) existed independently of the corpus.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from newsab_schema.enums import AngleType, Dimension
from newsab_schema.models.analysis import Feature

from .features import (
    FeatureKey,
    FeatureMatrix,
    controlled_feature_universe,
    is_controlled,
    shape_of,
    sort_key,
)
from .metrics import (
    PACKAGE_VERSION,
    SignedDifferenceInterval,
    signed_difference_interval,
)

#: How many representative observation IDs to carry per candidate.  S7's writer needs
#: examples, not the whole support set; the full set stays derivable from the matrix.
MAX_EXAMPLES = 8

#: The method string stored beside every Δ (§4.4: a number always names its code).
DELTA_METHOD = f"{PACKAGE_VERSION}/signed_prevalence_diff"
PREVALENCE_METHOD = f"{PACKAGE_VERSION}/cluster_prevalence"

#: Structural angle type of an attribute feature, by dimension.
_ATTR_ANGLE_TYPES: dict[Dimension, AngleType] = {
    Dimension.QUOTED_VOICE: AngleType.VOICE_STRUCTURE,
    Dimension.ACTOR_ROLE: AngleType.ACTOR_ROLE,
    Dimension.RESPONSIBILITY: AngleType.ACTOR_ROLE,
    Dimension.STANCE: AngleType.STANCE,
}


def structural_angle_type(key: FeatureKey) -> AngleType:
    """The label a feature carries by construction — which §3.3 A1 family it belongs to.

    This replaces the old scan-domain table: the label no longer decides what gets
    computed, only what the comparison is called.  ``shared_ground`` / ``co_silence`` are
    never assigned here — they are readings of the interval, not shapes of the feature —
    and ``blind_spot`` never exists before S6's four-condition check.
    """
    if shape_of(key) == "bare":
        return AngleType.SALIENCE
    return _ATTR_ANGLE_TYPES.get(Dimension(key[0]), AngleType.SALIENCE)


@dataclass
class GroupCounts:
    group_id: str
    clusters_supporting: int
    clusters_total: int
    by_category: dict[str, Optional[str]] = field(default_factory=dict)

    @property
    def prevalence(self) -> Optional[float]:
        return None if self.clusters_total == 0 else self.clusters_supporting / self.clusters_total

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Candidate:
    """One statistical comparison, before any gate has looked at it.

    Carries the full triple ``(p_a, p_b, Δ interval)`` — never Δ alone (R-2.1) — plus the
    counts behind it and representative evidence.  No reading, no verdict: those are the
    R-gate's to attach.
    """

    candidate_id: str
    topic_id: str
    #: Structural label (see :func:`structural_angle_type`).  The published angle type may
    #: differ when the R-gate's reading says consensus or co-silence.
    angle_type: str
    feature: Feature
    groups: list[GroupCounts]
    interval: SignedDifferenceInterval
    #: Whether this feature is a controlled-vocabulary cell — the precondition for the
    #: co-silence reading (R-2.3).
    controlled_vocabulary: bool
    #: Representative supporting observations from the higher-prevalence side.
    supporting_observations: list[str] = field(default_factory=list)
    #: Counter-examples: supporting observations from the *lower*-prevalence side.
    #: §4.4.1 invariant 4 requires these travel with the angle to the writer, so they are
    #: computed here rather than left for someone to remember later.
    exceptions: list[str] = field(default_factory=list)
    a1_run_id: Optional[str] = None

    @property
    def prevalence(self) -> dict[str, Optional[float]]:
        return {self.interval.group_a: self.interval.p_a, self.interval.group_b: self.interval.p_b}

    @property
    def high_group(self) -> Optional[str]:
        pa, pb = self.interval.p_a, self.interval.p_b
        if pa is None or pb is None:
            return None
        return self.interval.group_a if pa >= pb else self.interval.group_b

    @property
    def low_group(self) -> Optional[str]:
        pa, pb = self.interval.p_a, self.interval.p_b
        if pa is None or pb is None:
            return None
        return self.interval.group_a if pa <= pb else self.interval.group_b

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "topic_id": self.topic_id,
            "angle_type": self.angle_type,
            "feature": self.feature.model_dump(mode="json"),
            "groups": [g.to_dict() for g in self.groups],
            "metrics": {
                "prevalence": {"by_group": self.prevalence, "method": PREVALENCE_METHOD},
                "delta": {
                    "group_a": self.interval.group_a,
                    "group_b": self.interval.group_b,
                    "value": self.interval.delta,
                    "lo": self.interval.lo,
                    "hi": self.interval.hi,
                    "level": self.interval.level,
                    "method": DELTA_METHOD,
                },
                "direction_stability": self.interval.direction_stability,
                "conservative_effect": self.interval.conservative_effect,
                "log_odds": self.interval.log_odds,
                "concentration": {
                    "by_group": dict(self.interval.concentration),
                    "method": f"{PACKAGE_VERSION}/eff_publishers",
                },
                "resampling": {
                    "n_resamples": self.interval.n_resamples,
                    "seed": self.interval.seed,
                    "scheme": self.interval.scheme,
                },
                "a1_run_id": self.a1_run_id,
            },
            "controlled_vocabulary": self.controlled_vocabulary,
            "supporting_observations": self.supporting_observations,
            "exceptions": self.exceptions,
        }


@dataclass
class ScanConfig:
    """Resampling configuration.  There are no discovery thresholds any more (R-8): the
    scan emits every bare/attr feature, and the evidence bar lives entirely in the R-gate
    (`rgate.py`) where D8 says it belongs."""

    diversity_method: str = "eff_publishers"
    n_resamples: int = 2000
    seed: int = 20260817
    stratified: bool = True
    interval_level: float = 0.95

    def to_dict(self) -> dict:
        return asdict(self)


def _group_counts(
    matrix: FeatureMatrix, key: FeatureKey, group_id: str, categories: list[str]
) -> GroupCounts:
    by_category: dict[str, Optional[str]] = {}
    for category in categories:
        total = len(matrix.clusters_in(group_id, category))
        if total == 0:
            # The category exists in the topic but not in this group's corpus.  Recorded as
            # null rather than "0/0" so the page says "not present", not "never mentions it".
            by_category[category] = None
            continue
        supporting = len(matrix.supporting(key, group_id, category))
        by_category[category] = f"{supporting}/{total}"
    return GroupCounts(
        group_id=group_id,
        clusters_supporting=len(matrix.supporting(key, group_id)),
        clusters_total=len(matrix.clusters_in(group_id)),
        by_category=by_category,
    )


def build_candidate(
    matrix: FeatureMatrix,
    feature: Feature,
    group_a: str,
    group_b: str,
    config: ScanConfig,
    serial: int,
) -> Candidate:
    key = feature.key
    categories = matrix.categories()
    interval = signed_difference_interval(
        matrix,
        key,
        group_a,
        group_b,
        n_resamples=config.n_resamples,
        seed=config.seed,
        level=config.interval_level,
        stratified=config.stratified,
        diversity_method=config.diversity_method,
    )
    candidate = Candidate(
        candidate_id=f"CAND-{matrix.topic_id}-{serial:04d}",
        topic_id=matrix.topic_id,
        angle_type=structural_angle_type(key).value,
        feature=feature,
        groups=[
            _group_counts(matrix, key, group_a, categories),
            _group_counts(matrix, key, group_b, categories),
        ],
        interval=interval,
        controlled_vocabulary=is_controlled(key),
    )
    high, low = candidate.high_group, candidate.low_group
    if high is not None:
        candidate.supporting_observations = matrix.observation_ids(key, high)[:MAX_EXAMPLES]
    if low is not None and low != high:
        candidate.exceptions = matrix.observation_ids(key, low)[:MAX_EXAMPLES]
    return candidate


def scan_all(
    matrix: FeatureMatrix,
    group_a: str,
    group_b: str,
    config: Optional[ScanConfig] = None,
) -> list[Candidate]:
    """One candidate per feature in the universe: controlled-vocabulary cells (observed or
    not) plus every observed free-text attribute feature.  Concept-level features are
    skipped even when an older stored matrix contains them (R-4)."""
    config = config or ScanConfig()
    universe: dict[FeatureKey, Feature] = {f.key: f for f in controlled_feature_universe()}
    for key, feature in matrix.features.items():
        if shape_of(key) == "concept":
            continue
        universe.setdefault(key, feature)

    return [
        build_candidate(matrix, universe[key], group_a, group_b, config, serial)
        for serial, key in enumerate(sorted(universe, key=sort_key), start=1)
    ]


def load_candidates(path) -> list[Candidate]:
    """Read back a ``candidates.jsonl`` written by :func:`newsab_a1.run.write_run`.

    Lives here rather than in the CLI because S6's scripts need it too, and a second
    hand-rolled parser is a second chance for the two to disagree about what a candidate is.
    """
    import json
    from pathlib import Path

    candidates: list[Candidate] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        metrics = raw["metrics"]
        delta = metrics["delta"]
        interval = SignedDifferenceInterval(
            group_a=delta["group_a"],
            group_b=delta["group_b"],
            p_a=metrics["prevalence"]["by_group"][delta["group_a"]],
            p_b=metrics["prevalence"]["by_group"][delta["group_b"]],
            delta=delta["value"],
            lo=delta["lo"],
            hi=delta["hi"],
            level=delta["level"],
            direction_stability=metrics["direction_stability"],
            conservative_effect=metrics["conservative_effect"],
            log_odds=metrics["log_odds"],
            concentration=dict(metrics["concentration"]["by_group"]),
            n_resamples=metrics["resampling"]["n_resamples"],
            seed=metrics["resampling"]["seed"],
            scheme=metrics["resampling"]["scheme"],
        )
        candidates.append(
            Candidate(
                candidate_id=raw["candidate_id"],
                topic_id=raw["topic_id"],
                angle_type=raw["angle_type"],
                feature=Feature.model_validate(raw["feature"]),
                groups=[GroupCounts(**g) for g in raw["groups"]],
                interval=interval,
                controlled_vocabulary=raw["controlled_vocabulary"],
                supporting_observations=raw["supporting_observations"],
                exceptions=raw["exceptions"],
                a1_run_id=metrics["a1_run_id"],
            )
        )
    return candidates
