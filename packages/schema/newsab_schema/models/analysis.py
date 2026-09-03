"""Analysis-side records: candidate angles (§4.4) and claim objects (§4.5).

These carry the numbers that reach the reader, so the schema's job is to make every one of
them *re-derivable*: ``a1_run_id`` plus a ``method`` string on each metric is what lets a
reviewer with only the artifacts recompute the page (§7 of AGENTS.md, §4.4.1 invariant 1).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import Field, field_validator, model_serializer, model_validator

from ..common import LangText, MultiLangText, Provenance, Record
from ..enums import (
    E_SCORE_AXES,
    AngleOrigin,
    AngleStatus,
    AngleType,
    ClaimType,
    Dimension,
    IntervalReading,
    LintVerdict,
    RecommendedVisual,
)
from ..ids import (
    SEMANTIC_CLUSTER_ID_RE,
    SentenceId,
    is_sentence_id,
    parse_prefixed_id,
    topic_slug_matches,
    validate_concept_id,
    validate_run_id,
    validate_topic_id,
)

#: ``{package}-{version}/{metric_name}``, e.g. ``A1-0.2.0/prevalence_diff`` (§4.4 example).
METHOD_RE = re.compile(r"^[A-Za-z0-9]+-\d+\.\d+(?:\.\d+)?/[a-z][a-z0-9_]*$")

_SUPPORT_RE = re.compile(r"^(\d+)/(\d+)$")


def _validate_method(v: str) -> str:
    if not METHOD_RE.match(v):
        raise ValueError(
            f"metric method {v!r} must be '{{package}}-{{version}}/{{metric}}' "
            "so the implementation that produced the number can be found"
        )
    return v


# --------------------------------------------------------------------------------------
# §4.4 comparison block
# --------------------------------------------------------------------------------------


class SupportCount(Record):
    """``supporting/total`` independent reporting clusters (D7 denominator).

    Serialises back to the blueprint's ``"11/16"`` string so artifacts stay readable, but
    is a real pair in memory so the constraint and gate checks can do arithmetic.
    """

    supporting: int = Field(ge=0)
    total: int = Field(ge=0)

    @model_validator(mode="before")
    @classmethod
    def _from_string(cls, v: Any) -> Any:
        if isinstance(v, str):
            m = _SUPPORT_RE.match(v.strip())
            if not m:
                raise ValueError(f"support count must look like '11/16', got {v!r}")
            return {"supporting": int(m.group(1)), "total": int(m.group(2))}
        return v

    @model_validator(mode="after")
    def _bounds(self) -> "SupportCount":
        if self.supporting > self.total:
            raise ValueError(f"supporting {self.supporting} exceeds total {self.total}")
        return self

    @model_serializer
    def _to_string(self) -> str:
        return f"{self.supporting}/{self.total}"

    @property
    def share(self) -> Optional[float]:
        """Prevalence, or ``None`` when there is nothing to divide by.

        Zero clusters is not zero prevalence — it is an absent denominator, and the page
        has to say "sample too small" rather than "0%" (§1.5).
        """
        return None if self.total == 0 else self.supporting / self.total


class Feature(Record):
    """What the angle compares: one dimension, narrowed by a concept or by an attribute.

    ``concept_id`` is absent for ``salience`` angles, which compare how much a dimension is
    talked about at all rather than any single concept within it.

    ``attr_key`` / ``attr_value`` extend §4.4's example, which shows only
    ``{dimension, concept_id}``.  Two of the eight A1 scans are not concept comparisons at
    all: voice structure compares ``speaker_category`` and actor role compares ``actor``,
    both of which live in an observation's ``attrs`` (§4.2.1).  Without this pair those
    scans would have to smuggle an attribute value into ``concept_id``, which would break
    the ontology join.  The addition is optional and additive: a feature that omits it
    serialises exactly as the blueprint writes it.
    """

    dimension: Dimension
    concept_id: Optional[str] = None
    #: Which key of ``observation.attrs`` this feature compares, e.g. ``speaker_category``.
    attr_key: Optional[str] = None
    #: The value of that key, e.g. ``government_official``.
    attr_value: Optional[str] = None

    @field_validator("concept_id")
    @classmethod
    def _cid(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else validate_concept_id(v)

    @model_validator(mode="after")
    def _attr_pair(self) -> "Feature":
        if (self.attr_key is None) != (self.attr_value is None):
            raise ValueError("attr_key and attr_value must be given together or not at all")
        return self

    @property
    def key(self) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
        """Stable identity, used as the feature-matrix row key."""
        return (self.dimension.value, self.concept_id, self.attr_key, self.attr_value)

    def label(self) -> str:
        parts = [self.dimension.value]
        if self.concept_id:
            parts.append(self.concept_id)
        if self.attr_key:
            parts.append(f"{self.attr_key}={self.attr_value}")
        return "/".join(parts)


class GroupComparison(Record):
    """One side's counts for the feature, overall and split by source category.

    ``by_category`` may hold ``None`` for a category that exists in the source registry but
    has too few clusters to compare — §1.5 requires that to be *stated*, not silently
    folded into another category.
    """

    group_id: str = Field(pattern=r"^[a-z]{2,5}$")
    clusters_supporting: int = Field(ge=0)
    clusters_total: int = Field(ge=0)
    by_category: dict[str, Optional[SupportCount]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bounds(self) -> "GroupComparison":
        if self.clusters_supporting > self.clusters_total:
            raise ValueError(
                f"group {self.group_id}: clusters_supporting {self.clusters_supporting} "
                f"exceeds clusters_total {self.clusters_total}"
            )
        counted = [c for c in self.by_category.values() if c is not None]
        if counted:
            if sum(c.total for c in counted) > self.clusters_total:
                raise ValueError(
                    f"group {self.group_id}: per-category totals exceed clusters_total"
                )
            if sum(c.supporting for c in counted) > self.clusters_supporting:
                raise ValueError(
                    f"group {self.group_id}: per-category supporting counts exceed the total"
                )
        return self

    @property
    def prevalence(self) -> Optional[float]:
        return None if self.clusters_total == 0 else self.clusters_supporting / self.clusters_total


class Comparison(Record):
    feature: Feature
    groups: list[GroupComparison] = Field(min_length=2)

    @model_validator(mode="after")
    def _unique_groups(self) -> "Comparison":
        ids = [g.group_id for g in self.groups]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate group_id in comparison: {ids}")
        return self

    def group(self, group_id: str) -> GroupComparison:
        for g in self.groups:
            if g.group_id == group_id:
                return g
        raise KeyError(f"no group {group_id!r} in this comparison")


# --------------------------------------------------------------------------------------
# §4.4 metrics block
# --------------------------------------------------------------------------------------


class ScalarMetric(Record):
    value: float
    method: str

    @field_validator("method")
    @classmethod
    def _method(cls, v: str) -> str:
        return _validate_method(v)


class GroupMetric(Record):
    """A metric with one value per group (source diversity).

    The blueprint's example writes this flat (``{us: 0.81, cn: 0.64, method: ...}``); we
    store it nested so a group can never collide with the reserved ``method`` key, and
    accept the flat form on input so blueprint-shaped YAML still loads.
    """

    #: ``None`` is an absent denominator, not zero. This is expected on the low side of a
    #: genuine blind spot and must survive into the artifact without inventing diversity.
    by_group: dict[str, Optional[float]]
    method: str

    @model_validator(mode="before")
    @classmethod
    def _accept_flat(cls, v: Any) -> Any:
        if isinstance(v, dict) and "by_group" not in v and "method" in v:
            method = v["method"]
            return {
                "method": method,
                "by_group": {k: val for k, val in v.items() if k != "method"},
            }
        return v

    @field_validator("method")
    @classmethod
    def _method(cls, v: str) -> str:
        return _validate_method(v)


class DeltaInterval(Record):
    """The signed prevalence difference ``p(group_a) − p(group_b)`` with its resampling
    percentile interval (R-2).

    No p-values anywhere (D16): the interval is a robustness statement about the sample —
    "would this difference survive had we been handed a different batch of clusters" —
    never an inference about a population.  ``group_a``/``group_b`` make the sign
    convention explicit in the artifact rather than implied by list order.
    """

    group_a: str
    group_b: str
    value: float = Field(ge=-1.0, le=1.0)
    lo: float = Field(ge=-1.0, le=1.0)
    hi: float = Field(ge=-1.0, le=1.0)
    #: Central interval mass, e.g. ``0.95``.
    level: float = Field(gt=0.0, lt=1.0)
    method: str

    @field_validator("method")
    @classmethod
    def _method(cls, v: str) -> str:
        return _validate_method(v)

    @model_validator(mode="after")
    def _ordered(self) -> "DeltaInterval":
        if self.lo > self.hi:
            raise ValueError(f"interval lo {self.lo} exceeds hi {self.hi}")
        return self


class ResamplingSpec(Record):
    """How the interval was produced — enough to re-run it exactly."""

    n_resamples: int = Field(ge=1)
    #: e.g. ``stratified_by_category_over_clusters`` — resampling clusters, never articles,
    #: because clusters are the unit (D7).
    scheme: str = Field(min_length=1)
    seed: Optional[int] = None


class AngleMetrics(Record):
    """The statistics block of an angle: the triple ``(p_a, p_b, Δ interval)`` and its
    readings (R-2.1).

    ``prevalence`` is required — Δ alone cannot distinguish consensus from co-silence, so
    an artifact carrying only the difference is a design error by definition.
    ``concentration`` (the old source diversity) is displayed, never gated.
    """

    prevalence: GroupMetric
    delta: DeltaInterval
    #: Share of resamples agreeing with the observed sign — a display reading of the
    #: same distribution, not an independent metric (G-6).
    direction_stability: float = Field(ge=0.0, le=1.0)
    #: The interval endpoint nearer zero when the interval excludes zero, else 0.0.
    conservative_effect: float = Field(ge=0.0, le=2.0)
    #: Signed smoothed log-odds companion for low-baseline narration (R-2.1).
    log_odds: Optional[float] = None
    concentration: GroupMetric
    resampling: ResamplingSpec
    #: Every number above must be reproducible from this run (§4.4.1 invariant 1).
    a1_run_id: str

    @field_validator("a1_run_id")
    @classmethod
    def _run(cls, v: str) -> str:
        return validate_run_id(v)


# --------------------------------------------------------------------------------------
# §4.4 gates
# --------------------------------------------------------------------------------------


class RGate(Record):
    """Deterministic statistical gate (§3.3 S6).  Runs before any editorial agent sees the
    candidate, which is the structural half of D8.

    The gate is a reader of the signed-difference interval; ``reading`` says
    which of the five R-2.2 readings the interval supported.  It lives here rather than in
    ``metrics`` because it depends on the thresholds version, not only on the data.
    """

    passed: bool
    thresholds_version: str = Field(min_length=1)
    reading: Optional[IntervalReading] = None
    failed_checks: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> "RGate":
        if self.passed and self.failed_checks:
            raise ValueError(f"r_gate.passed=true but failed_checks={self.failed_checks}")
        if not self.passed and not self.failed_checks:
            raise ValueError("r_gate.passed=false must name the checks that failed")
        return self


class BlindSpotCondition(Record):
    passed: bool
    note: LangText
    #: Optional supporting anchors — e.g. the adjacent-context sentences that show the
    #: opportunity to cover existed.
    evidence: list[str] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def _anchors(cls, v: list[str]) -> list[str]:
        for sid in v:
            SentenceId.parse(sid)
        return v


class BlindSpotCheck(Record):
    """The four opportunity-to-cover conditions (§3.3 S6), each answered explicitly.

    Named rather than lettered so a failure message says which check failed instead of
    "(b)".  All four must pass before a blind-spot angle may be shortlisted (§4.4.1
    invariant 2) — blind spots carry a higher bar than every other angle type.
    """

    same_event_stage: BlindSpotCondition
    opportunity_to_cover: BlindSpotCondition
    category_composition: BlindSpotCondition
    not_single_wire_amplified: BlindSpotCondition

    @property
    def conditions(self) -> dict[str, BlindSpotCondition]:
        return {
            "same_event_stage": self.same_event_stage,
            "opportunity_to_cover": self.opportunity_to_cover,
            "category_composition": self.category_composition,
            "not_single_wire_amplified": self.not_single_wire_amplified,
        }

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.conditions.values())

    def failed(self) -> list[str]:
        return [name for name, c in self.conditions.items() if not c.passed]


# --------------------------------------------------------------------------------------
# §4.4 editorial block
# --------------------------------------------------------------------------------------


class EScore(Record):
    """Editorial score, one 0–2 per axis against a published rubric (§3.3 S6, four axes
    since R-7 — see ``E_SCORE_AXES`` for what was cut and why).

    Editorial scoring happens strictly after the R-gate and can only ever *remove*
    candidates — there is no field here that can raise a candidate past a failed gate (D8).
    Its two remaining uses: the audit trail of the subjective selection, and the
    regression signal for R-6's δ calibration.
    """

    surprise: int = Field(ge=0, le=2)
    relevance: int = Field(ge=0, le=2)
    non_redundancy: int = Field(ge=0, le=2)
    story_potential: int = Field(ge=0, le=2)
    rubric_version: str = Field(min_length=1)

    @property
    def total(self) -> int:
        return sum(getattr(self, axis) for axis in E_SCORE_AXES)


class Editorial(Record):
    """The reader-facing question this angle becomes (§3.3 S6's highest-value LLM step)."""

    question: MultiLangText
    e_score: Optional[EScore] = None
    recommended_visual: Optional[RecommendedVisual] = None

    @model_validator(mode="after")
    def _pivot_present(self) -> "Editorial":
        if "en" not in self.question.values:
            raise ValueError(
                "editorial.question must include the English pivot master (D6/§1.6 L2)"
            )
        return self


class Selection(Record):
    status: AngleStatus
    #: S6 shortlist order. It is not an E-score and must not be reconstructed from one;
    #: Phase 0 uses the first five when the constrained set contains 6–8 angles.
    rank: Optional[int] = Field(default=None, ge=1)
    #: Which selection constraints this angle is carrying, e.g. ``covers_type:shared_ground``.
    constraint_roles: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# §4.4 the angle itself
# --------------------------------------------------------------------------------------


class CandidateAngle(Record):
    """A candidate angle across its whole life: A1 output -> R-gate -> S6 -> G2."""

    angle_id: str
    topic_id: str
    #: Recorded for audit only.  D9 forbids this from entering any threshold branch;
    #: ``tests/test_d9_origin_blindness.py`` enforces that at the source level.
    origin: AngleOrigin
    angle_type: AngleType
    comparison: Comparison
    metrics: AngleMetrics
    r_gate: RGate
    blind_spot_check: Optional[BlindSpotCheck] = None
    semantic_cluster_id: Optional[str] = None
    merged_into: Optional[str] = None
    editorial: Optional[Editorial] = None
    supporting_observations: list[str] = Field(default_factory=list)
    #: Counter-examples.  ``[]`` means "we looked and found none" and is subject to judge
    #: spot-check; a placeholder string is a §4.4.1 invariant 4 failure.
    exceptions: list[str] = Field(default_factory=list)
    selection: Selection
    #: Set when an approved angle is carried into a later corpus run that it no longer
    #: clears the R-gate on (R-5).  Format ``failed_in_run_<corpus_run_id>``.  Under the
    #: default ``angle_carryover: inherit`` this does **not** block publication — G2
    #: approved the *question*, and the numbers behind it are expected to move as the
    #: corpus grows — but it puts the angle in front of the next G2 and into the QA report.
    gate_status: Optional[str] = None
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @field_validator("gate_status")
    @classmethod
    def _gate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith("failed_in_run_"):
            raise ValueError(
                f"gate_status must be 'failed_in_run_<run_id>', got {v!r}; an angle that "
                "still passes carries no gate_status at all"
            )
        return v

    @field_validator("semantic_cluster_id")
    @classmethod
    def _sc(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not SEMANTIC_CLUSTER_ID_RE.match(v):
            raise ValueError(f"not a semantic_cluster_id: {v!r} (expected SC-nn)")
        return v

    @field_validator("supporting_observations", "exceptions")
    @classmethod
    def _obs_refs(cls, v: list[str]) -> list[str]:
        for oid in v:
            if not str(oid).strip():
                raise ValueError(
                    "empty string placeholder is not allowed; use an empty list to mean "
                    "'no exceptions found' (§4.4.1 invariant 4)"
                )
            parse_prefixed_id(oid, "OBS")
        return v

    @model_validator(mode="after")
    def _invariants(self) -> "CandidateAngle":
        parsed = parse_prefixed_id(self.angle_id, "ANG")
        if not topic_slug_matches(parsed.topic_slug, self.topic_id):
            raise ValueError(
                f"angle_id topic slug {parsed.topic_slug!r} does not match topic_id {self.topic_id!r}"
            )
        if self.merged_into is not None:
            parse_prefixed_id(self.merged_into, "ANG")
            if self.selection.status != AngleStatus.MERGED:
                raise ValueError(
                    "merged_into is set but selection.status is "
                    f"{self.selection.status.value!r}; expected 'merged'"
                )
        if self.selection.status == AngleStatus.MERGED and self.merged_into is None:
            raise ValueError("status='merged' must name the surviving angle in merged_into")

        # §4.4.1 invariant 2 — blind spots need all four conditions before shortlisting.
        past_gate = self.selection.status in {
            AngleStatus.SHORTLISTED,
            AngleStatus.G2_APPROVED,
        }
        if self.angle_type == AngleType.BLIND_SPOT:
            if self.blind_spot_check is None and past_gate:
                raise ValueError(
                    "a shortlisted blind_spot angle must carry blind_spot_check "
                    "(§4.4.1 invariant 2)"
                )
            if past_gate and self.blind_spot_check is not None and not self.blind_spot_check.all_passed:
                raise ValueError(
                    "blind_spot angle cannot be shortlisted with failed conditions: "
                    f"{self.blind_spot_check.failed()}"
                )
        elif self.blind_spot_check is not None:
            raise ValueError(
                f"blind_spot_check is only meaningful for angle_type=blind_spot, "
                f"got {self.angle_type.value}"
            )

        # An angle can only be past the editorial stage if it was actually scored.
        if past_gate and (self.editorial is None or self.editorial.e_score is None):
            raise ValueError(
                f"status={self.selection.status.value} requires editorial.e_score "
                "(the E-score is what shortlisting is based on)"
            )
        if past_gate and not self.r_gate.passed:
            raise ValueError(
                "an angle that failed the R-gate can never be shortlisted — editorial "
                "judgement may not lower the evidence bar (D8)"
            )
        return self

    @property
    def group_ids(self) -> list[str]:
        return [g.group_id for g in self.comparison.groups]


# --------------------------------------------------------------------------------------
# §4.5 claim object
# --------------------------------------------------------------------------------------


class QuantifierCheck(Record):
    """The record that a quantifier in the claim text was bound to a number (§4.5)."""

    phrase: str = Field(min_length=1)
    #: What the phrase was bound to, e.g. ``divergence=0.46`` or ``prevalence=0.65``.
    bound_to: str = Field(pattern=r"^[a-z_]+=-?\d+(\.\d+)?$")
    lint: LintVerdict


class Claim(Record):
    """One reader-facing sentence, with its provenance path (§4.5).

    The three ``claim_type`` values are different kinds of promise: ``source_claim`` says
    someone said this and points at the sentence where they said it; ``corpus_aggregate``
    says our sample looks like this and points at the A1 metric plus illustrative
    sentences; ``corpus_reading`` says *we read the source text and this is what the two
    sides' answers are* — evidence-bound, but measured by nobody.  Conflating the first two
    is how "reported parity" gets mistaken for "real parity" — the failure mode §0.2 names
    in the competitor review.  Conflating the third with either is how an editorial
    judgement acquires the authority of a statistic.
    """

    claim_id: str
    angle_id: str
    topic_id: str
    text: MultiLangText
    claim_type: ClaimType
    #: Required for aggregates: where the number came from, e.g. ``ANG-...-0007.metrics``.
    computed_from: Optional[str] = None
    evidence: list[str] = Field(min_length=1)
    quantifier_check: Optional[QuantifierCheck] = None
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @field_validator("evidence")
    @classmethod
    def _anchors(cls, v: list[str]) -> list[str]:
        for sid in v:
            if not is_sentence_id(sid):
                raise ValueError(
                    f"claim evidence must be sentence IDs, got {sid!r} "
                    "(free-form URL citation is forbidden, §3.2)"
                )
        return v

    @model_validator(mode="after")
    def _provenance_path(self) -> "Claim":
        parse_prefixed_id(self.claim_id, "CLM")
        parse_prefixed_id(self.angle_id, "ANG")
        if "en" not in self.text.values:
            raise ValueError("claim text must include the English pivot master (D6)")
        if self.claim_type == ClaimType.CORPUS_AGGREGATE and not self.computed_from:
            raise ValueError(
                "corpus_aggregate claims must carry computed_from — the metric they "
                "recompute against (§4.5 invariant)"
            )
        if self.claim_type == ClaimType.SOURCE_CLAIM and self.computed_from:
            raise ValueError(
                "source_claim evidence is the whole basis; computed_from would imply a "
                "statistical path this claim does not have (§4.5 invariant)"
            )
        if self.claim_type == ClaimType.CORPUS_READING:
            if self.computed_from:
                raise ValueError(
                    "corpus_reading is what the source text says, not what a metric "
                    "measured; computed_from would claim a statistical path it does not "
                    "have (§4.5 invariant)"
                )
            if self.quantifier_check is not None:
                raise ValueError(
                    "corpus_reading has no magnitude to bind a quantifier to; say what the "
                    "sides answer, never how much (§4.5 invariant)"
                )
            if len(self.evidence) < 2:
                raise ValueError(
                    "corpus_reading characterises a body of coverage and needs at least "
                    "two sentence anchors; one sentence is a source_claim"
                )
        return self
