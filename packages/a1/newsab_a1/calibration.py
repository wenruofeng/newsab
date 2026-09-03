"""The calibration harness: calibrating the δ thresholds and effect ordering from real data.

Blueprint ⑤ fixes the selection criterion and it is not a mathematical one — a signal is
better if it **correlates with the user's "Defensible" scores** (and, per R-6, with the
LLM's four-axis interest scores over **all** candidates — a truncated set gives the
regression selection bias).  Everything here therefore takes human scores as the target
variable and treats the interval's readings as candidate predictors.

Known limitation (R-6): with current corpora only the divergence side has signal to
regress on; the consensus bucket is structurally empty (G-5), so ``delta_consensus``
cannot be back-fitted until the smaller side's cluster count grows.

Nothing in this module can run without a scored corpus.  That is the honest state of
calibration: the machinery is here, the numbers are not, and `configs/rgate-0.2.yaml` stays
marked ``calibrated: false`` until someone runs :func:`calibration_report` on the Phase 0
gold set and writes the result back.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Sequence

from .features import FeatureMatrix
from .rgate import RGateThresholds, evaluate
from .scan import Candidate, ScanConfig, scan_all


# --------------------------------------------------------------------------------------
# small statistics, kept dependency-free so calibration runs anywhere the pipeline does
# --------------------------------------------------------------------------------------


def _rank(values: Sequence[float]) -> list[float]:
    """Average ranks, so ties do not distort the correlation."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Spearman rank correlation.  ``None`` when there is not enough spread to speak."""
    if len(xs) != len(ys):
        raise ValueError("spearman needs equal-length sequences")
    if len(xs) < 3:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return None if den == 0 else num / den


@dataclass
class ThresholdPoint:
    threshold: float
    kept: int
    precision: Optional[float]
    recall: Optional[float]
    f1: Optional[float]

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "kept": self.kept,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


def threshold_sweep(
    values: Mapping[str, Optional[float]],
    defensible: Mapping[str, float],
    *,
    positive_at: float = 4.0,
    steps: Sequence[float] = tuple(i / 20 for i in range(21)),
) -> list[ThresholdPoint]:
    """How a single-metric cut-off trades off against the human "Defensible" judgement.

    "Positive" means the user scored the candidate ≥ ``positive_at`` on Defensible.
    Recall is the number that matters most here: a threshold that quietly discards findings
    the user considers well-evidenced is worse than one that lets a few weak ones
    through to the E-score, because the E-score can still drop those.
    """
    shared = [cid for cid in values if cid in defensible and values[cid] is not None]
    positives = {cid for cid in shared if defensible[cid] >= positive_at}
    out: list[ThresholdPoint] = []
    for threshold in steps:
        kept = {cid for cid in shared if values[cid] >= threshold}
        tp = len(kept & positives)
        precision = tp / len(kept) if kept else None
        recall = tp / len(positives) if positives else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision and recall and (precision + recall) > 0
            else None
        )
        out.append(ThresholdPoint(threshold, len(kept), precision, recall, f1))
    return out


@dataclass
class SignalScore:
    """How well one reading of the interval predicts the human judgement."""

    signal: str
    n_resamples: int
    stratified: bool
    correlation: Optional[float]
    n_scored: int

    def to_dict(self) -> dict:
        return {
            "signal": self.signal,
            "n_resamples": self.n_resamples,
            "stratified": self.stratified,
            "spearman_vs_defensible": self.correlation,
            "n_scored": self.n_scored,
        }


#: The interval readings offered as predictors of the human judgement (R-6).
_SIGNALS: dict[str, Callable[[Candidate], Optional[float]]] = {
    "conservative_effect": lambda c: c.interval.conservative_effect,
    "abs_delta": lambda c: None if c.interval.delta is None else abs(c.interval.delta),
    "abs_log_odds": lambda c: None if c.interval.log_odds is None else abs(c.interval.log_odds),
    "direction_stability": lambda c: c.interval.direction_stability,
    "concentration_high_side": lambda c: (
        c.interval.concentration.get(c.high_group) if c.high_group else None
    ),
}


@dataclass
class CalibrationReport:
    """Everything calibration needs to write back into the config files."""

    signal_scores: list[SignalScore] = field(default_factory=list)
    sweeps: dict[str, list[ThresholdPoint]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def best_signal(self) -> Optional[SignalScore]:
        scored = [m for m in self.signal_scores if m.correlation is not None]
        return max(scored, key=lambda m: m.correlation) if scored else None

    def to_dict(self) -> dict:
        best = self.best_signal()
        return {
            "signal_scores": [m.to_dict() for m in self.signal_scores],
            "best_signal": best.to_dict() if best else None,
            "sweeps": {k: [p.to_dict() for p in v] for k, v in self.sweeps.items()},
            "notes": self.notes,
        }


def calibration_report(
    matrix: FeatureMatrix,
    group_a: str,
    group_b: str,
    defensible: Mapping[str, float],
    *,
    key_for: Callable[[Candidate], str] = lambda c: c.candidate_id,
    base_config: Optional[ScanConfig] = None,
    n_resample_options: Sequence[int] = (2000,),
    stratification_options: Sequence[bool] = (True,),
) -> CalibrationReport:
    """Score each interval reading against the human judgements, over ALL candidates.

    ``defensible`` maps a candidate key (by default ``candidate_id``; pass ``key_for`` to
    key on the angle IDs S6 assigned instead) to the user's 1–5 Defensible score.
    R-6's rule applies to whoever assembles that mapping: score every candidate, not just
    the ones that passed the gate, or the regression inherits the gate's selection bias.
    """
    base = base_config or ScanConfig()
    report = CalibrationReport()

    if len(defensible) < 5:
        report.notes.append(
            f"only {len(defensible)} scored candidates — treat every number below as "
            "indicative at best; blueprint ⑤ sizes the gold set at 200–400 observations "
            "and all candidate angles for a reason"
        )

    for n_resamples, stratified in itertools.product(
        n_resample_options, stratification_options
    ):
        config = ScanConfig(
            **{**base.to_dict(), "n_resamples": n_resamples, "stratified": stratified}
        )
        candidates = scan_all(matrix, group_a, group_b, config)
        for signal, read in _SIGNALS.items():
            pairs = [
                (read(c), defensible[key_for(c)])
                for c in candidates
                if key_for(c) in defensible and read(c) is not None
            ]
            report.signal_scores.append(
                SignalScore(
                    signal=signal,
                    n_resamples=n_resamples,
                    stratified=stratified,
                    correlation=spearman([p[0] for p in pairs], [p[1] for p in pairs])
                    if pairs
                    else None,
                    n_scored=len(pairs),
                )
            )

    # Threshold sweeps use the base configuration, so the numbers are readable against the
    # config that is actually in the file.
    candidates = scan_all(matrix, group_a, group_b, base)
    for signal in ("conservative_effect", "abs_delta", "direction_stability"):
        read = _SIGNALS[signal]
        report.sweeps[signal] = threshold_sweep(
            {key_for(c): read(c) for c in candidates}, defensible
        )
    return report


def gate_agreement(
    candidates: Sequence[Candidate],
    thresholds: RGateThresholds,
    defensible: Mapping[str, float],
    *,
    key_for: Callable[[Candidate], str] = lambda c: c.candidate_id,
    positive_at: float = 4.0,
) -> dict:
    """How the current gate as a whole agrees with the user.

    The asymmetry to watch is ``rejected_but_defensible``: those are findings the user
    considers well-evidenced that the gate threw away before anyone could read them. Every
    one of them is a threshold that is too tight, and they are invisible unless counted.
    """
    scored = [c for c in candidates if key_for(c) in defensible]
    rows = [(c, evaluate(c, thresholds), defensible[key_for(c)]) for c in scored]
    return {
        "thresholds_version": thresholds.thresholds_version,
        "scored_candidates": len(rows),
        "passed_and_defensible": sum(1 for _, r, s in rows if r.passed and s >= positive_at),
        "passed_but_weak": sum(1 for _, r, s in rows if r.passed and s < positive_at),
        "rejected_but_defensible": sum(
            1 for _, r, s in rows if not r.passed and s >= positive_at
        ),
        "rejected_and_weak": sum(1 for _, r, s in rows if not r.passed and s < positive_at),
        "false_rejections": [
            {
                "candidate_id": c.candidate_id,
                "defensible": s,
                "failed_checks": r.failed_checks,
            }
            for c, r, s in rows
            if not r.passed and s >= positive_at
        ],
    }
