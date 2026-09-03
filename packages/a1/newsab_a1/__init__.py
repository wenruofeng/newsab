"""``newsab_a1`` — the deterministic statistics layer (blueprint §3.3 A1).

**Not a skill, on purpose (D10).** Counting, weighting, divergence, stability, ranking and
threshold checks are plain Python here so that a stranger auditing a submission can re-run
them without a model, and get the same numbers. LLMs re-enter the pipeline afterwards, at
S6's semantic clustering — never before the feature matrix is built.

Pipeline through this package::

    observations + corpus + ontology
        -> build_feature_matrix()      cluster × bare/attr feature support   (product 1)
        -> scan_all()                  one candidate per feature in the
                                       controlled universe (R-3, R-8)        (product 2)
        -> signed_difference_interval  (p_a, p_b, Δ interval) per candidate  (product 3)
        -> rgate.evaluate_all()        the interval readings, before any
                                       editorial step (D8)
        -> build_concept_map()         the descriptive concept layer,
                                       outside the Δ pipeline (R-4)

Two invariants worth restating because they are easy to erode:

* every prevalence figure divides by **independent reporting clusters** (D7), never by
  articles or publication instances;
* there are **no p-values** (D16) — the corpus is not a probability sample, so the layer
  reports effect size plus robustness and phrases everything as a fact about the sample.
"""

from __future__ import annotations

__version__ = "0.3.0"

from .calibration import CalibrationReport, calibration_report, gate_agreement, spearman
from .concept_map import ConceptEntry, build_concept_map
from .features import (
    ATTR_FEATURES,
    ClusterMeta,
    FeatureMatrix,
    build_cluster_meta,
    build_feature_matrix,
    controlled_feature_universe,
    is_controlled,
    shape_of,
    sort_key,
)
from .metrics import (
    PACKAGE_VERSION,
    BootstrapResult,
    CrossStratumResult,
    SignedDifferenceInterval,
    bootstrap_stability,
    cross_stratum_consistency,
    direction,
    divergence,
    divergence_methods,
    diversity_methods,
    signed_difference_interval,
    signed_log_odds,
    source_diversity,
)
from .rgate import (
    RGateResult,
    RGateThresholds,
    UncalibratedGateError,
    classify,
    evaluate,
    evaluate_all,
    rank_passed,
    summarise,
)
from .run import (
    A1Run,
    Recomputer,
    analyse,
    compute_analysis_digest,
    compute_run_id,
    recompute_metrics,
    write_run,
)
from .scan import (
    DELTA_METHOD,
    Candidate,
    GroupCounts,
    ScanConfig,
    load_candidates,
    scan_all,
    structural_angle_type,
)
from .storage import read_matrix, rows_digest, write_matrix

__all__ = [
    "A1Run",
    "ATTR_FEATURES",
    "BootstrapResult",
    "CalibrationReport",
    "Candidate",
    "ClusterMeta",
    "CrossStratumResult",
    "DELTA_METHOD",
    "FeatureMatrix",
    "GroupCounts",
    "PACKAGE_VERSION",
    "RGateResult",
    "RGateThresholds",
    "Recomputer",
    "ScanConfig",
    "SignedDifferenceInterval",
    "UncalibratedGateError",
    "analyse",
    "bootstrap_stability",
    "build_cluster_meta",
    "build_concept_map",
    "build_feature_matrix",
    "calibration_report",
    "ConceptEntry",
    "classify",
    "compute_run_id",
    "compute_analysis_digest",
    "controlled_feature_universe",
    "cross_stratum_consistency",
    "direction",
    "divergence",
    "divergence_methods",
    "diversity_methods",
    "evaluate",
    "evaluate_all",
    "gate_agreement",
    "is_controlled",
    "load_candidates",
    "rank_passed",
    "read_matrix",
    "recompute_metrics",
    "rows_digest",
    "scan_all",
    "shape_of",
    "signed_difference_interval",
    "signed_log_odds",
    "sort_key",
    "source_diversity",
    "spearman",
    "structural_angle_type",
    "summarise",
    "write_matrix",
    "write_run",
]
