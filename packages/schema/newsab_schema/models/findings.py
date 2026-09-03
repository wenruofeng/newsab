"""Analyze-stage output: computed Q×A findings (value_chain stage 4).

The analyze stage is code only (non-negotiable 4): every field here is derived from
answer records by ``newsab_a1.qa_analyze`` — no LLM writes a finding.  Findings are what
the write stage works from; the strength mark disciplines the writer (V-3: an
``unsupported`` contrast may not be asserted in prose or charts, magnitudes are shown
with their intervals).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import Field, field_validator, model_validator

from ..common import LangText, Provenance, Record
from ..enums import FindingKind, FindingStrength
from ..ids import SentenceId, parse_prefixed_id, topic_slug_matches, validate_topic_id


class GroupAnswerStats(Record):
    """One side's answers to one question, in countable form.

    ``clusters_total`` is the side's independent-cluster denominator (non-negotiable 3);
    every rate a page shows is ``clusters_addressed / clusters_total`` or a category
    count over ``clusters_addressed``, both recomputable from the answer records.
    """

    group_id: str = Field(pattern=r"^[a-z]{2,5}$")
    clusters_total: int = Field(ge=0)
    clusters_addressed: int = Field(ge=0)
    #: ``category -> cluster count`` over the addressed clusters (``unclear`` included —
    #: shown, but excluded from cross-side comparisons).
    category_counts: dict[str, int] = Field(default_factory=dict)
    #: Modal category among comparable (non-``unclear``) answers; ``None`` when silent.
    #: Kept as the lexical first category for backwards compatibility; consumers must
    #: inspect ``top_category_tied`` before presenting it as a unique leader.
    top_category: Optional[str] = None
    #: Every category tied for the highest comparable count, in lexical order.
    top_categories: list[str] = Field(default_factory=list)
    #: True when there is no unique modal answer category.
    top_category_tied: bool = False
    #: A few anchor sentences illustrating this side's answers (modal category first,
    #: then answers with more evidence sentences).  For a silent side this list is
    #: empty — silence has no anchors; the speaking side's anchors are the finding's
    #: contrast anchors.
    sample_evidence: list[str] = Field(default_factory=list)

    @field_validator("sample_evidence")
    @classmethod
    def _anchors(cls, v: list[str]) -> list[str]:
        for sid in v:
            SentenceId.parse(sid)
        return v

    @model_validator(mode="before")
    @classmethod
    def _derive_modal_metadata(cls, data: Any) -> Any:
        """Upgrade older findings in memory without rewriting immutable runs."""
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        counts = payload.get("category_counts")
        if isinstance(counts, dict) and all(isinstance(v, int) for v in counts.values()):
            comparable = {str(k): v for k, v in counts.items() if k != "unclear"}
            maximum = max(comparable.values(), default=0)
            modes = sorted(k for k, v in comparable.items() if v == maximum and maximum > 0)
            payload.setdefault("top_categories", modes)
            payload.setdefault("top_category_tied", len(modes) > 1)
            payload.setdefault("top_category", modes[0] if modes else None)
        return payload

    @model_validator(mode="after")
    def _consistent(self) -> "GroupAnswerStats":
        if self.clusters_addressed > self.clusters_total:
            raise ValueError("clusters_addressed exceeds clusters_total")
        if sum(self.category_counts.values()) > self.clusters_addressed:
            raise ValueError("category counts exceed addressed clusters")
        comparable = {k: v for k, v in self.category_counts.items() if k != "unclear"}
        maximum = max(comparable.values(), default=0)
        modes = sorted(k for k, v in comparable.items() if v == maximum and maximum > 0)
        if self.top_categories != modes:
            raise ValueError(f"top_categories must equal the modal categories {modes}")
        expected_top = modes[0] if modes else None
        if self.top_category != expected_top:
            raise ValueError(f"top_category must be the lexical first modal category {expected_top!r}")
        if self.top_category_tied != (len(modes) > 1):
            raise ValueError("top_category_tied must state whether multiple modal categories tie")
        return self


class FindingDelta(Record):
    """The effect size a finding asserts, with its posterior interval.

    Since the analyze refactor: ``value`` is the observed quantity and
    ``[lo, hi]`` its posterior interval under the pseudo-count prior, both anchored to
    the finding's asserted top categories.  Quantities: ``consensus_dominance`` (mean of
    both sides' shares of the common top answer), ``divergence_share_gap`` (mean absolute
    own-minus-other share gap over the two sides' top answers), ``addressed_rate_diff``
    (attention gaps).  Pre-refactor runs carry ``top_category_share_diff`` bootstrap
    spreads.  Shown to readers as ``value [lo, hi]`` — never the conservative end alone.
    """

    quantity: str = Field(min_length=1)  # e.g. "addressed_rate_diff", "consensus_dominance"
    group_a: str
    group_b: str
    value: float = Field(ge=-1.0, le=1.0)
    lo: float = Field(ge=-1.0, le=1.0)
    hi: float = Field(ge=-1.0, le=1.0)
    level: float = Field(gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> "FindingDelta":
        if self.lo > self.hi:
            raise ValueError(f"interval lo {self.lo} exceeds hi {self.hi}")
        return self


class QAFinding(Record):
    """One computed comparison outcome for one question.

    ``summary`` is a deterministic English-pivot sentence assembled from the counts by
    code — the write stage restates it for readers but may not change what it claims.
    A silence finding (``blindspot``, or ``attention_gap`` with ``total_silence``) must
    carry the speaking side's anchors (silence needs contrast anchors), and its summary
    states annotation-layer silence ("no cluster was annotated as addressing…"), never
    absence from the world.
    """

    finding_id: str
    topic_id: str
    question_id: str
    kind: FindingKind
    strength: FindingStrength
    #: Retired (analyze refactor D-g): attention gaps are first-class findings,
    #: so nothing is secondary any more.  Kept append-only; always False on new runs.
    secondary: bool = False
    #: Position in the writer's candidate pool (1 = first candidate).  A mechanical
    #: ordering — significance gate, then kind rotation, then effect size — never an
    #: editorial verdict; page order and selection belong to the write stage.
    rank: int = Field(ge=1)
    #: Retired (analyze refactor D-e): "interest" is an editorial judgement,
    #: not a formula.  Optional so historical runs deserialize; new runs do not write it.
    interest: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    groups: list[GroupAnswerStats] = Field(min_length=2, max_length=2)
    delta: Optional[FindingDelta] = None
    #: Posterior probability that this finding's assertion is true, under the
    #: pseudo-count prior (analyze refactor D-d).  On pre-refactor runs: the fraction of
    #: naive resamples in which the defining relation held.
    stability: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    #: True when re-computing this finding's kind or either side's top category from the
    #: raw (un-normalized) category counts changes the outcome — the writer must inspect
    #: both tallies before using it (analyze refactor D-c).
    merge_sensitive: bool = False
    #: attention_gap only: the quiet side has zero addressed clusters.  Display-wording
    #: switch — the renderer words such a finding as annotation-layer silence
    #: (non-negotiable 5); it never changes the statistics.
    total_silence: bool = False
    summary: LangText
    thresholds_version: str = Field(min_length=1)
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @model_validator(mode="after")
    def _consistency(self) -> "QAFinding":
        parsed = parse_prefixed_id(self.finding_id, "FND")
        if not topic_slug_matches(parsed.topic_slug, self.topic_id):
            raise ValueError(
                f"finding_id topic slug {parsed.topic_slug!r} does not match "
                f"topic_id {self.topic_id!r}"
            )
        parse_prefixed_id(self.question_id, "QST")
        if self.summary.lang != "en":
            raise ValueError("finding summaries are written in the English pivot")
        if self.total_silence and self.kind != FindingKind.ATTENTION_GAP:
            raise ValueError("total_silence is an attention_gap wording switch only")
        silence = self.kind == FindingKind.BLINDSPOT or (
            self.kind == FindingKind.ATTENTION_GAP and self.total_silence
        )
        if silence:
            speaking = [g for g in self.groups if g.clusters_addressed > 0]
            if not speaking:
                raise ValueError("a silence finding needs a side that addressed the question")
            if not any(g.sample_evidence for g in speaking):
                raise ValueError(
                    "a silence finding must carry the speaking side's contrast anchors"
                )
        return self
