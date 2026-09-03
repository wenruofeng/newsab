"""The R-gate: deterministic statistical filtering, before any editorial judgement (D8).

The gate is a **reader of one interval**, not six independent thresholds.
The old six-threshold design was five readings of the same resampling distribution
implemented as separate facts; on real data four of the six never independently rejected
anything (G-6).  What remains:

* :func:`classify` — the five readings of a signed-difference interval (R-2.2):
  divergence / small-stable-difference / consensus / co-silence / insufficient.
  "Insufficient" is a first-class outcome: it must never be conflated with "we checked
  and the two sides agree" (G-5).
* two sample floors that are *not* readings of the distribution and therefore survive:
  ``min_clusters_total`` (an all-empty cell resamples to a degenerate [0, 0] interval no
  matter how thin the corpus, so equivalence readings need a floor under them) and
  ``min_clusters_supporting`` (a divergence carried by one newsroom is a source claim,
  not a corpus claim).
* ranking by **conservative effect** — the interval endpoint nearer zero — which is what
  replaces `min_divergence` as the ordering the editorial layer sees (R-2.2, R-6).

Under R-8 the full candidate list ships as the data layer regardless of the gate;
``passed`` now means "eligible to become an angle", not "visible to readers".

Two design choices remain load-bearing and should not be "simplified" later:

**The gate cannot see `origin`.** D9 says a prior hypothesis and a data-discovered finding
compete on identical terms, and the way to guarantee that is not a code comment — it is
that :func:`evaluate` takes a :class:`~newsab_a1.scan.Candidate`, which has no ``origin``
field at all.  Origin is attached afterwards, by S6, for the audit trail only.
``packages/a1/tests/test_d9_origin_blindness.py`` scans this module's source to keep it
that way.

**The gate runs before the E-score, and nothing can reverse that order.** Editorial scoring
can only remove candidates from the shortlist; there is no code path by which an
interesting story lowers an evidence threshold.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from newsab_schema.io import load_yaml_text

from newsab_schema.enums import AngleType, IntervalReading

from .metrics import SignedDifferenceInterval
from .scan import Candidate

DEFAULT_CONFIG = Path(__file__).parent / "configs" / "rgate-0.2.yaml"


class UncalibratedGateError(RuntimeError):
    """Raised when a not-yet-calibrated threshold set is used where that matters."""


@dataclass
class RGateThresholds:
    thresholds_version: str
    calibrated: bool
    default: dict[str, Any]
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[Path | str] = None) -> "RGateThresholds":
        raw = load_yaml_text(Path(path or DEFAULT_CONFIG).read_text(encoding="utf-8"))
        return cls(
            thresholds_version=raw["thresholds_version"],
            calibrated=bool(raw.get("calibrated", False)),
            default=raw["default"],
            overrides=raw.get("overrides") or {},
        )

    def for_angle_type(self, angle_type: str) -> dict[str, Any]:
        merged = dict(self.default)
        merged.update(self.overrides.get(angle_type, {}))
        return {k: v for k, v in merged.items() if v is not None}


@dataclass
class RGateResult:
    candidate_id: str
    passed: bool
    #: Which of the five R-2.2 readings the interval supports.
    reading: str
    thresholds_version: str
    #: The interval endpoint nearer zero (0.0 unless the interval excludes zero) — the
    #: number divergence-type candidates are ranked by.
    conservative_effect: float
    failed_checks: list[str] = field(default_factory=list)
    #: Every check with the value it saw, so a near-miss is inspectable rather than a
    #: bare "rejected" — calibration tunes thresholds off exactly this.
    measured: dict[str, Optional[float]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def classify(
    interval: SignedDifferenceInterval,
    *,
    controlled_vocabulary: bool,
    delta_consensus: float,
    delta_silence: float,
    high_prevalence: float,
    low_prevalence: float,
) -> IntervalReading:
    """The five readings of one interval (R-2.2).

    The equivalence band is ``delta_silence`` in the silence regime (both prevalences at
    or below ``low_prevalence`` on a controlled-vocabulary cell) and ``delta_consensus``
    otherwise — two different δ because Var ∝ p(1−p) makes one δ strict at one end of the
    distribution and vacuous at the other.  Co-silence is only readable on
    controlled-vocabulary cells: a free-text feature exists *because* someone said it, so
    its empty cell is circular, not silent (R-2.3).
    """
    p_a, p_b = interval.p_a, interval.p_b
    if p_a is None or p_b is None or interval.lo is None or interval.hi is None:
        return IntervalReading.INSUFFICIENT

    silence_regime = controlled_vocabulary and max(p_a, p_b) <= low_prevalence
    band = delta_silence if silence_regime else delta_consensus

    if interval.excludes_zero():
        if interval.within(band):
            return IntervalReading.SMALL_STABLE_DIFFERENCE
        return IntervalReading.DIVERGENCE
    if silence_regime and interval.within(delta_silence):
        return IntervalReading.CO_SILENCE
    if min(p_a, p_b) >= high_prevalence and interval.within(delta_consensus):
        return IntervalReading.CONSENSUS
    return IntervalReading.INSUFFICIENT


def evaluate(candidate: Candidate, thresholds: RGateThresholds) -> RGateResult:
    """Read the candidate's interval and decide angle eligibility.

    Eligible readings are divergence (with a support floor on the higher side), consensus,
    and co-silence — the three that carry a publishable statement.  A small-stable
    difference is real but reader-ignorable, and "insufficient" is exactly what it says;
    both stay in the published data layer (R-8) without becoming angles.
    """
    rules = thresholds.for_angle_type(candidate.angle_type)
    interval = candidate.interval
    failed: list[str] = []
    measured: dict[str, Optional[float]] = {
        "p_a": interval.p_a,
        "p_b": interval.p_b,
        "delta": interval.delta,
        "delta_lo": interval.lo,
        "delta_hi": interval.hi,
        "conservative_effect": interval.conservative_effect,
        "direction_stability": interval.direction_stability,
    }

    reading = classify(
        interval,
        controlled_vocabulary=candidate.controlled_vocabulary,
        delta_consensus=rules["delta_consensus"],
        delta_silence=rules["delta_silence"],
        high_prevalence=rules["high_prevalence"],
        low_prevalence=rules["low_prevalence"],
    )

    totals = [g.clusters_total for g in candidate.groups]
    measured["min_clusters_total"] = float(min(totals)) if totals else None
    if "min_clusters_total" in rules and (not totals or min(totals) < rules["min_clusters_total"]):
        failed.append(
            f"min_clusters_total: smallest group has {min(totals) if totals else 0} clusters, "
            f"needs {rules['min_clusters_total']} — below this every reading degenerates"
        )

    if reading == IntervalReading.DIVERGENCE:
        high = candidate.high_group
        supporting = next(
            (g.clusters_supporting for g in candidate.groups if g.group_id == high), 0
        )
        measured["min_clusters_supporting"] = float(supporting)
        if "min_clusters_supporting" in rules and supporting < rules["min_clusters_supporting"]:
            failed.append(
                f"min_clusters_supporting: {supporting} supporting clusters on the higher "
                f"side, needs {rules['min_clusters_supporting']}"
            )
    elif reading == IntervalReading.SMALL_STABLE_DIFFERENCE:
        failed.append(
            "reading=small_stable_difference: real but inside the equivalence band — "
            "data layer only, not an angle"
        )
    elif reading == IntervalReading.INSUFFICIENT:
        failed.append(
            "reading=insufficient: the interval neither excludes zero nor fits an "
            "equivalence band — the honest label is 'the sample cannot tell' (G-5)"
        )

    # The blind-spot variant carries a strictly higher bar (§3.3 S6): the statistical half
    # is a divergence whose low side is genuinely silent, on top of stricter floors.
    if candidate.angle_type == AngleType.BLIND_SPOT.value and not failed:
        low_prev = min(p for p in candidate.prevalence.values() if p is not None)
        measured["blind_spot_low_side_prevalence"] = low_prev
        if reading != IntervalReading.DIVERGENCE:
            failed.append(
                f"blind_spot: requires a divergence reading, got {reading.value}"
            )
        elif low_prev > rules["low_prevalence"]:
            failed.append(
                f"blind_spot: low side prevalence {low_prev:.2f} exceeds "
                f"{rules['low_prevalence']} — the low side is not silent, just quieter"
            )

    return RGateResult(
        candidate_id=candidate.candidate_id,
        passed=not failed,
        reading=reading.value,
        thresholds_version=thresholds.thresholds_version,
        conservative_effect=interval.conservative_effect,
        failed_checks=failed,
        measured=measured,
    )


def evaluate_all(
    candidates: Sequence[Candidate],
    thresholds: Optional[RGateThresholds] = None,
    *,
    require_calibrated: bool = False,
) -> list[RGateResult]:
    """Gate a whole candidate set.

    ``require_calibrated=True`` refuses to run against a threshold file still marked
    ``calibrated: false``.  Use it for anything heading for publication: shipping a page
    whose evidence bar was never calibrated is precisely the failure D8 exists to prevent.
    """
    thresholds = thresholds or RGateThresholds.load()
    if require_calibrated and not thresholds.calibrated:
        raise UncalibratedGateError(
            f"threshold set {thresholds.thresholds_version!r} is still marked "
            "calibrated: false — calibrate the thresholds before gating anything for publication"
        )
    return [evaluate(candidate, thresholds) for candidate in candidates]


def rank_passed(results: Sequence[RGateResult]) -> list[RGateResult]:
    """Passed results, divergences ordered by conservative effect (largest first), then
    the equivalence readings.  This is the order the editorial layer receives — the
    replacement for ranking by raw divergence (R-2.2)."""
    passed = [r for r in results if r.passed]
    return sorted(
        passed,
        key=lambda r: (r.reading != IntervalReading.DIVERGENCE.value, -r.conservative_effect, r.candidate_id),
    )


def summarise(results: Sequence[RGateResult]) -> dict:
    """Pass/fail counts, the readings histogram, and the most common rejection reasons."""
    reasons: dict[str, int] = {}
    readings: dict[str, int] = {}
    for result in results:
        readings[result.reading] = readings.get(result.reading, 0) + 1
        for check in result.failed_checks:
            name = check.split(":", 1)[0]
            reasons[name] = reasons.get(name, 0) + 1
    return {
        "candidates": len(results),
        "passed": sum(1 for r in results if r.passed),
        "rejected": sum(1 for r in results if not r.passed),
        "readings": dict(sorted(readings.items())),
        "rejection_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
    }
