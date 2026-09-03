"""Product 3 — the statistics behind every comparison (§3.3 A1).

The centrepiece is :func:`signed_difference_interval`: **one** stratified bootstrap over
clusters whose resamples yield everything the pipeline reads — the prevalence pair
``(p_a, p_b)``, the signed difference Δ with its percentile interval, the direction
stability, the conservative effect size, and (computed alongside, never gated on) the
newsroom concentration behind each side.  The earlier five metric families were readings
of this same resampling distribution implemented as if they were independent facts;
R-1/R-2 has the evidence and G-6 the standing conclusion.

The prevalence pair is a first-class citizen (R-2.1): Δ alone cannot distinguish
"both sides talk about it constantly" from "both sides barely mention it", so no artifact
field may carry Δ without ``(p_a, p_b)`` beside it.

The divergence/diversity registries remain for the calibration harness; every
implementation is registered under the ``method`` string that goes into the artifact
(``A1-0.3.0/prevalence_diff``), so a stored number always names the code that produced it.

Two rules hold across all of it:

* **No p-values** (D16).  The corpus is not a probability sample; a p-value would
  manufacture an inferential claim we cannot make.  The interval is a resampling
  robustness statement about *this sample* — "would this difference survive had we been
  handed a different batch of clusters" — never an inference about a population.
* **Clusters are the unit** (D7).  Nothing here counts articles.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from .features import FeatureKey, FeatureMatrix

PACKAGE_VERSION = "A1-0.3.0"

DivergenceFn = Callable[[FeatureMatrix, FeatureKey, str, str], Optional[float]]
DiversityFn = Callable[[FeatureMatrix, FeatureKey, str], Optional[float]]

_DIVERGENCE: dict[str, DivergenceFn] = {}
_DIVERSITY: dict[str, DiversityFn] = {}


def method_name(family: str, name: str) -> str:
    return f"{PACKAGE_VERSION}/{name}"


def register_divergence(name: str) -> Callable[[DivergenceFn], DivergenceFn]:
    def wrap(fn: DivergenceFn) -> DivergenceFn:
        _DIVERGENCE[name] = fn
        return fn

    return wrap


def register_diversity(name: str) -> Callable[[DiversityFn], DiversityFn]:
    def wrap(fn: DiversityFn) -> DiversityFn:
        _DIVERSITY[name] = fn
        return fn

    return wrap


def divergence_methods() -> list[str]:
    return sorted(_DIVERGENCE)


def diversity_methods() -> list[str]:
    return sorted(_DIVERSITY)


# --------------------------------------------------------------------------------------
# Divergence — how far apart the two sides are on one feature
# --------------------------------------------------------------------------------------


@register_divergence("prevalence_diff")
def prevalence_diff(
    matrix: FeatureMatrix, feature: FeatureKey, group_a: str, group_b: str
) -> Optional[float]:
    """Absolute difference in cluster prevalence.  The default: it is the quantity the page
    actually describes ("17 of 26 clusters vs 4 of 21"), so the number and the sentence
    cannot drift apart."""
    pa = matrix.prevalence(feature, group_a)
    pb = matrix.prevalence(feature, group_b)
    if pa is None or pb is None:
        return None
    return abs(pa - pb)


@register_divergence("log_odds_ratio")
def log_odds_ratio(
    matrix: FeatureMatrix, feature: FeatureKey, group_a: str, group_b: str
) -> Optional[float]:
    """Smoothed |log odds ratio|, squashed into [0, 1].

    More sensitive than a raw difference at the extremes — 2% vs 12% is a large editorial
    difference that ``prevalence_diff`` scores as 0.10, the same as 45% vs 55%.  Candidate
    for calibration.
    """
    pa = matrix.prevalence(feature, group_a)
    pb = matrix.prevalence(feature, group_b)
    if pa is None or pb is None:
        return None
    na = len(matrix.clusters_in(group_a))
    nb = len(matrix.clusters_in(group_b))
    # Haldane–Anscombe correction, so a 0-of-n cell does not produce an infinity.
    sa = (pa * na + 0.5) / (na + 1)
    sb = (pb * nb + 0.5) / (nb + 1)
    odds = abs(math.log((sa / (1 - sa)) / (sb / (1 - sb))))
    return odds / (1.0 + odds)


@register_divergence("jensen_shannon_within_dimension")
def jensen_shannon_within_dimension(
    matrix: FeatureMatrix, feature: FeatureKey, group_a: str, group_b: str
) -> Optional[float]:
    """Jensen–Shannon divergence between the two sides' *distributions* over the sibling
    features of the same dimension.

    Answers a different question from the others: not "do they mention X at different
    rates" but "is the whole shape of what they emphasise different".  Returns the same
    value for every sibling feature, which is exactly right for a salience-type angle and
    wrong for a single-concept one — calibration decides where it earns its place.
    """
    dimension = feature[0]
    siblings = [k for k in matrix.features if k[0] == dimension and k[1:] != (None, None, None)]
    if not siblings:
        return None

    def distribution(group: str) -> Optional[list[float]]:
        counts = [len(matrix.supporting(k, group)) for k in siblings]
        total = sum(counts)
        if total == 0:
            return None
        return [c / total for c in counts]

    da, db = distribution(group_a), distribution(group_b)
    if da is None or db is None:
        return None

    def kl(p: Sequence[float], q: Sequence[float]) -> float:
        return sum(pi * math.log2(pi / qi) for pi, qi in zip(p, q) if pi > 0 and qi > 0)

    m = [(x + y) / 2 for x, y in zip(da, db)]
    return 0.5 * kl(da, m) + 0.5 * kl(db, m)


def divergence(
    matrix: FeatureMatrix,
    feature: FeatureKey,
    group_a: str,
    group_b: str,
    method: str = "prevalence_diff",
) -> Optional[float]:
    return _DIVERGENCE[method](matrix, feature, group_a, group_b)


def direction(
    matrix: FeatureMatrix, feature: FeatureKey, group_a: str, group_b: str
) -> Optional[int]:
    """Sign of ``p(a) - p(b)``: which side talks about it more.  ``0`` for an exact tie."""
    pa = matrix.prevalence(feature, group_a)
    pb = matrix.prevalence(feature, group_b)
    if pa is None or pb is None:
        return None
    if pa == pb:
        return 0
    return 1 if pa > pb else -1


# --------------------------------------------------------------------------------------
# Source diversity — is this many newsrooms, or one voice amplified?
# --------------------------------------------------------------------------------------


def _shannon_effective(counts: Sequence[int]) -> float:
    """``exp(H)`` — the "effective number" of sources, in source units rather than nats."""
    total = sum(counts)
    if total == 0:
        return 0.0
    entropy = -sum((c / total) * math.log(c / total) for c in counts if c > 0)
    return math.exp(entropy)


@register_diversity("eff_publishers")
def eff_publishers(matrix: FeatureMatrix, feature: FeatureKey, group_id: str) -> Optional[float]:
    """Effective number of distinct publishers behind the supporting clusters, normalised
    by how many publishers that group's corpus contains at all.

    This is the metric §3.3 A1 says the layer exists for: "10 outlets / 8 independent
    clusters" and "2 outlets / 1 wire cluster" must not score alike.  Normalising by the
    group's publisher count is what separates them — the second case scores low because
    almost none of the available newsrooms are behind the claim, not merely because there
    are few clusters.
    """
    sources = matrix.source_ids_supporting(feature, group_id)
    if not sources:
        return None
    available = matrix.group_source_count(group_id)
    if available == 0:
        return None
    counts: dict[str, int] = {}
    for source in sources:
        counts[source] = counts.get(source, 0) + 1
    return min(1.0, _shannon_effective(list(counts.values())) / available)


@register_diversity("distinct_source_share")
def distinct_source_share(
    matrix: FeatureMatrix, feature: FeatureKey, group_id: str
) -> Optional[float]:
    """Distinct supporting publishers / publishers available.  Simpler baseline; ignores
    how lopsided the distribution is.  Kept as the comparison arm for calibration."""
    sources = matrix.source_ids_supporting(feature, group_id)
    available = matrix.group_source_count(group_id)
    if not sources or available == 0:
        return None
    return min(1.0, len(set(sources)) / available)


def source_diversity(
    matrix: FeatureMatrix, feature: FeatureKey, group_id: str, method: str = "eff_publishers"
) -> Optional[float]:
    return _DIVERSITY[method](matrix, feature, group_id)


# --------------------------------------------------------------------------------------
# Bootstrap stability — does the direction survive resampling?
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BootstrapResult:
    direction_stability: float
    n_resamples: int
    scheme: str
    seed: int
    observed_direction: Optional[int]
    #: Percentile interval on the **signed** difference ``p_a − p_b``, for display.  Not a
    #: confidence interval — the corpus is not a probability sample (D16) — it is a
    #: resampling spread.  Signed on purpose: the earlier implementation took ``abs()``
    #: before the percentiles, which produced an interval that could never cover 0 and was
    #: therefore unusable for any equivalence reading (G-6).
    signed_diff_p05: Optional[float] = None
    signed_diff_p95: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "direction_stability": self.direction_stability,
            "n_resamples": self.n_resamples,
            "scheme": self.scheme,
            "seed": self.seed,
        }


def _resample_clusters(
    matrix: FeatureMatrix, group_id: str, rng: random.Random, stratified: bool
) -> list[str]:
    """Draw a cluster sample with replacement — clusters, never articles (D7)."""
    if not stratified:
        pool = matrix.clusters_in(group_id)
        return [rng.choice(pool) for _ in pool] if pool else []
    out: list[str] = []
    for category in matrix.categories(group_id):
        pool = matrix.clusters_in(group_id, category)
        out.extend(rng.choice(pool) for _ in pool)
    return out


def bootstrap_stability(
    matrix: FeatureMatrix,
    feature: FeatureKey,
    group_a: str,
    group_b: str,
    *,
    n_resamples: int = 1000,
    seed: int = 20260817,
    stratified: bool = True,
    divergence_method: str = "prevalence_diff",
) -> BootstrapResult:
    """Fraction of resamples in which the observed direction still holds.

    Deterministic given ``seed``: reproducibility is the whole point, and a stability
    figure a reviewer cannot re-derive is worse than none.  Uses ``random.Random`` from the
    standard library rather than NumPy so the stream does not depend on a library version.
    """
    scheme = "stratified_by_category_over_clusters" if stratified else "simple_over_clusters"
    observed = direction(matrix, feature, group_a, group_b)
    rng = random.Random(seed)

    if observed is None or observed == 0:
        return BootstrapResult(0.0, n_resamples, scheme, seed, observed)

    supporting_a = set(matrix.supporting(feature, group_a))
    supporting_b = set(matrix.supporting(feature, group_b))
    agree = 0
    divergences: list[float] = []

    for _ in range(n_resamples):
        sample_a = _resample_clusters(matrix, group_a, rng, stratified)
        sample_b = _resample_clusters(matrix, group_b, rng, stratified)
        if not sample_a or not sample_b:
            continue
        pa = sum(c in supporting_a for c in sample_a) / len(sample_a)
        pb = sum(c in supporting_b for c in sample_b) / len(sample_b)
        if divergence_method == "prevalence_diff":
            divergences.append(pa - pb)
        sign = 0 if pa == pb else (1 if pa > pb else -1)
        if sign == observed:
            agree += 1

    stability = agree / n_resamples if n_resamples else 0.0
    lo = hi = None
    if divergences:
        divergences.sort()
        lo = divergences[int(0.05 * (len(divergences) - 1))]
        hi = divergences[int(0.95 * (len(divergences) - 1))]
    return BootstrapResult(stability, n_resamples, scheme, seed, observed, lo, hi)


# --------------------------------------------------------------------------------------
# The signed-difference interval — one resampling, every reading (R-2)
# --------------------------------------------------------------------------------------


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Nearest-rank quantile over an already-sorted list, matching the percentile scheme
    the rest of this module has always used."""
    return sorted_values[int(q * (len(sorted_values) - 1))]


def signed_log_odds(
    matrix: FeatureMatrix, feature: FeatureKey, group_a: str, group_b: str
) -> Optional[float]:
    """Signed, Haldane–Anscombe-smoothed log odds ratio of ``p_a`` vs ``p_b``.

    The companion scale for low baselines (R-2.1): Δ = 0.10 on top of (0.05, 0.15) is a
    threefold gap, on top of (0.85, 0.95) a small relative change, and ``prevalence_diff``
    cannot tell them apart.  The page's headline number stays the prevalence difference —
    the sentence and the number must be isomorphic — but the writing layer switches to
    this scale when narrating a low-baseline comparison.
    """
    pa = matrix.prevalence(feature, group_a)
    pb = matrix.prevalence(feature, group_b)
    if pa is None or pb is None:
        return None
    na = len(matrix.clusters_in(group_a))
    nb = len(matrix.clusters_in(group_b))
    sa = (pa * na + 0.5) / (na + 1)
    sb = (pb * nb + 0.5) / (nb + 1)
    return math.log((sa / (1 - sa)) / (sb / (1 - sb)))


@dataclass(frozen=True)
class SignedDifferenceInterval:
    """One stratified resampling of ``p_a − p_b``, and every reading taken from it.

    The prevalence pair travels with the difference (R-2.1): no consumer may store or show
    ``delta`` without ``(p_a, p_b)``.  The interval is a percentile spread of the signed
    difference under resampling clusters within source-category strata — a robustness
    statement about this sample, not an inference about any population (D16).
    """

    group_a: str
    group_b: str
    p_a: Optional[float]
    p_b: Optional[float]
    #: Observed signed difference ``p_a − p_b``.
    delta: Optional[float]
    lo: Optional[float]
    hi: Optional[float]
    #: Central interval mass, e.g. ``0.95`` → percentiles 2.5 and 97.5.
    level: float
    #: Share of resamples whose sign agrees with the observed sign (ties count half).
    #: A *reading* of the same distribution — kept for display, not a separate metric.
    direction_stability: float
    #: The interval endpoint nearer zero when the interval excludes zero, else 0.0.
    #: This is the number divergence candidates are ranked by (R-2.2).
    conservative_effect: float
    #: Signed smoothed log odds ratio — the low-baseline companion scale (R-2.1).
    log_odds: Optional[float]
    #: Newsroom concentration behind each side's supporting clusters (effective
    #: publishers / publishers available).  Computed alongside, shown with the result,
    #: never thresholded (R-2.3): clusters already de-duplicate wire copy, so this is a
    #: second line of defence that has never fired in real data.
    concentration: dict[str, Optional[float]] = field(default_factory=dict)
    n_resamples: int = 0
    seed: int = 0
    scheme: str = ""

    def excludes_zero(self) -> bool:
        if self.lo is None or self.hi is None:
            return False
        return self.lo > 0.0 or self.hi < 0.0

    def within(self, half_width: float) -> bool:
        """Whether the whole interval sits inside ``[-half_width, +half_width]`` — the
        equivalence question.  An interval merely *covering* zero is evidence of nothing
        (G-5): with few clusters almost every interval covers zero."""
        if self.lo is None or self.hi is None:
            return False
        return self.lo >= -half_width and self.hi <= half_width

    def to_dict(self) -> dict:
        return {
            "group_a": self.group_a,
            "group_b": self.group_b,
            "p_a": self.p_a,
            "p_b": self.p_b,
            "delta": self.delta,
            "lo": self.lo,
            "hi": self.hi,
            "level": self.level,
            "direction_stability": self.direction_stability,
            "conservative_effect": self.conservative_effect,
            "log_odds": self.log_odds,
            "concentration": dict(self.concentration),
            "n_resamples": self.n_resamples,
            "seed": self.seed,
            "scheme": self.scheme,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "SignedDifferenceInterval":
        return cls(**{**raw, "concentration": dict(raw.get("concentration") or {})})


def signed_difference_interval(
    matrix: FeatureMatrix,
    feature: FeatureKey,
    group_a: str,
    group_b: str,
    *,
    n_resamples: int = 2000,
    seed: int = 20260817,
    level: float = 0.95,
    stratified: bool = True,
    diversity_method: str = "eff_publishers",
) -> SignedDifferenceInterval:
    """One stratified over-clusters bootstrap; Δ and the concentration read from it.

    Works for features that have no support anywhere — a controlled-vocabulary cell
    nobody filled is a real observation ("neither side quotes foreign-government voices"),
    so ``prevalence`` of an unknown feature is 0/total, not an error.  Deterministic given
    ``seed``; ``random.Random`` so the stream does not depend on a library version.
    """
    scheme = "stratified_by_category_over_clusters" if stratified else "simple_over_clusters"
    p_a = matrix.prevalence(feature, group_a)
    p_b = matrix.prevalence(feature, group_b)
    concentration = {
        group_a: source_diversity(matrix, feature, group_a, diversity_method),
        group_b: source_diversity(matrix, feature, group_b, diversity_method),
    }
    log_odds = signed_log_odds(matrix, feature, group_a, group_b)

    if p_a is None or p_b is None:
        return SignedDifferenceInterval(
            group_a, group_b, p_a, p_b, None, None, None, level, 0.0, 0.0,
            log_odds, concentration, n_resamples, seed, scheme,
        )

    delta = p_a - p_b
    supporting_a = set(matrix.supporting(feature, group_a))
    supporting_b = set(matrix.supporting(feature, group_b))
    rng = random.Random(seed)
    deltas: list[float] = []
    same_sign = 0.0
    observed_sign = 0 if delta == 0 else (1 if delta > 0 else -1)

    for _ in range(n_resamples):
        sample_a = _resample_clusters(matrix, group_a, rng, stratified)
        sample_b = _resample_clusters(matrix, group_b, rng, stratified)
        if not sample_a or not sample_b:
            continue
        pa = sum(c in supporting_a for c in sample_a) / len(sample_a)
        pb = sum(c in supporting_b for c in sample_b) / len(sample_b)
        d = pa - pb
        deltas.append(d)
        sign = 0 if d == 0 else (1 if d > 0 else -1)
        if sign == observed_sign:
            same_sign += 1.0
        elif sign == 0 or observed_sign == 0:
            same_sign += 0.5

    if not deltas:
        return SignedDifferenceInterval(
            group_a, group_b, p_a, p_b, delta, None, None, level, 0.0, 0.0,
            log_odds, concentration, n_resamples, seed, scheme,
        )

    deltas.sort()
    tail = (1.0 - level) / 2.0
    lo = _quantile(deltas, tail)
    hi = _quantile(deltas, 1.0 - tail)
    stability = same_sign / len(deltas)
    if lo > 0.0:
        conservative = lo
    elif hi < 0.0:
        conservative = -hi
    else:
        conservative = 0.0

    return SignedDifferenceInterval(
        group_a, group_b, p_a, p_b, delta, lo, hi, level, stability, conservative,
        log_odds, concentration, n_resamples, seed, scheme,
    )


# --------------------------------------------------------------------------------------
# Cross-stratum consistency — is this one category's doing?
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossStratumResult:
    value: float
    note: str
    #: category -> direction inside that category (``None`` when too thin to judge).
    by_category: dict[str, Optional[int]]

    def to_dict(self) -> dict:
        return {"value": self.value, "note": self.note}


def cross_stratum_consistency(
    matrix: FeatureMatrix,
    feature: FeatureKey,
    group_a: str,
    group_b: str,
    *,
    min_clusters_per_stratum: int = 3,
) -> CrossStratumResult:
    """Share of comparable source categories in which the overall direction still holds.

    A difference that appears only in the magazines and portals of `other` is a different,
    smaller story than one that holds in the serious press too — §3.3 A1 asks for this
    exactly so the second is not published as if it were the first.  Categories too thin on either
    side are excluded from the denominator rather than counted as disagreement, and the
    note says how many were skipped.
    """
    overall = direction(matrix, feature, group_a, group_b)
    by_category: dict[str, Optional[int]] = {}
    comparable = 0
    agreeing = 0
    skipped: list[str] = []

    for category in sorted(set(matrix.categories(group_a)) & set(matrix.categories(group_b))):
        na = len(matrix.clusters_in(group_a, category))
        nb = len(matrix.clusters_in(group_b, category))
        if na < min_clusters_per_stratum or nb < min_clusters_per_stratum:
            by_category[category] = None
            skipped.append(f"{category}({na}/{nb})")
            continue
        pa = matrix.prevalence(feature, group_a, category)
        pb = matrix.prevalence(feature, group_b, category)
        sign = 0 if pa == pb else (1 if pa > pb else -1)
        by_category[category] = sign
        comparable += 1
        if overall is not None and sign == overall:
            agreeing += 1

    if comparable == 0:
        note = "no source category has enough clusters on both sides to check consistency"
        if skipped:
            note += "; too thin: " + ", ".join(skipped)
        return CrossStratumResult(0.0, note, by_category)

    holding = [c for c, s in by_category.items() if s is not None and s == overall]
    note = f"direction holds in {len(holding)}/{comparable} comparable categories"
    if holding:
        note += " (" + ", ".join(sorted(holding)) + ")"
    if skipped:
        note += "; too thin to judge: " + ", ".join(skipped)
    return CrossStratumResult(agreeing / comparable, note, by_category)
