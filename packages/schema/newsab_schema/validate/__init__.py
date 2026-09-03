"""Cross-record invariant checks — what S8 L0 re-runs on any submission (§3.3 S8)."""

from .angles import (
    MAX_PER_SEMANTIC_CLUSTER,
    MIN_DISTINCT_TYPES,
    SELECTION_SIZE,
    ConstraintReport,
    ConstraintResult,
    check_selection_constraints,
    validate_angles,
)
from .claims import validate_claims, verify_quote
from .observations import (
    EXPECTED_OBS_PER_ARTICLE,
    validate_article_annotations,
    validate_observations,
    validate_ontology_against,
)
from .qa import validate_answers
from .report import Finding, ValidationReport

__all__ = [
    "ConstraintReport",
    "ConstraintResult",
    "EXPECTED_OBS_PER_ARTICLE",
    "Finding",
    "MAX_PER_SEMANTIC_CLUSTER",
    "MIN_DISTINCT_TYPES",
    "SELECTION_SIZE",
    "ValidationReport",
    "check_selection_constraints",
    "validate_angles",
    "validate_answers",
    "validate_article_annotations",
    "validate_claims",
    "validate_observations",
    "validate_ontology_against",
    "verify_quote",
]
