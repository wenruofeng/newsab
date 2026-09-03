"""The Q×A annotation model (value_chain.md "The Q×A model", decision V-1).

The unit of comparison is a **question × answer** pair, not a topic mention:

* a :class:`Question` is something a reader would ask of both sides — template tier
  (comparative-journalism standards, asked of every topic) or reader tier
  (topic-specific, generated from the scope brief and the corpus);
* a :class:`QuestionSet` is the versioned artifact holding one topic's questions.
  Questions can be added mid-run — analysis discovers a pattern, a new question enters
  the set, and incremental re-annotation answers it — so the set is versioned like
  everything else and answers pin the version they answered;
* a :class:`ClusterAnswer` records, per reporting cluster per question, whether the
  cluster addresses the question and — if it does — a short answer summary in the
  source's own language, a normalized answer category countable across clusters and
  across sides, and the anchoring sentence IDs (non-negotiable 2).

Findings (consensus / divergence / blindspot) are *computed* from these records by the
analyze stage; nothing here stores a verdict.  Silence is representable only as
``addressed=false`` — a statement about the annotation layer, never about the world
(non-negotiable 5).
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import Field, field_validator, model_validator

from ..common import LangText, MultiLangText, Provenance, Record, PIVOT_LANG
from ..enums import QuestionStatus, QuestionTier, TemplateQuestionKey
from ..ids import (
    CLUSTER_ID_RE,
    SentenceId,
    parse_prefixed_id,
    topic_slug_matches,
    validate_cluster_id,
    validate_topic_id,
)

#: Grammar for ``answer_category``: snake_case English, same shape as a concept_id.
#: Categories are the countable layer — "who is blamed" answers become
#: ``us_government`` / ``chinese_students`` / ``both_governments`` — so they must be
#: joinable across clusters and across sides, which free-form source-language text is not.
ANSWER_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

#: Reserved category for an addressed question whose answer resists bucketing.  It is a
#: real category (countable, honest) but the analyze stage treats it as uncomparable —
#: two ``unclear`` answers are not an agreement.
ANSWER_CATEGORY_UNCLEAR = "unclear"


def validate_answer_category(raw: str) -> str:
    value = str(raw).strip()
    if not ANSWER_CATEGORY_RE.match(value):
        raise ValueError(
            f"not an answer_category: {raw!r} (expected snake_case English, e.g. "
            "'us_government', 'no_position')"
        )
    return value


class Question(Record):
    """One question asked of every reporting cluster on both sides.

    ``text`` carries at least the English pivot wording (the comparison layer's master
    language); per-side wordings may be added for annotator convenience but the English
    wording is canonical.  ``category_guidance`` tells annotators how to bucket answers
    into categories so two annotation passes produce joinable vocabularies; it guides,
    it does not enumerate — a genuinely new answer mints a new category.
    """

    question_id: str
    topic_id: str
    tier: QuestionTier
    #: Which standing template-tier standard this instantiates.  Required for template
    #: tier (that is what makes template questions comparable across topics), forbidden
    #: for reader tier.
    template_key: Optional[TemplateQuestionKey] = None
    text: MultiLangText
    #: Why this question is worth asking of this topic — audit trail for the reader-tier
    #: generation step, one sentence for template instantiations.
    rationale: LangText
    category_guidance: Optional[LangText] = None
    status: QuestionStatus = QuestionStatus.ACTIVE
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @model_validator(mode="after")
    def _consistency(self) -> "Question":
        parsed = parse_prefixed_id(self.question_id, "QST")
        if not topic_slug_matches(parsed.topic_slug, self.topic_id):
            raise ValueError(
                f"question_id topic slug {parsed.topic_slug!r} does not match "
                f"topic_id {self.topic_id!r}"
            )
        if self.text.get(PIVOT_LANG) is None:
            raise ValueError(
                f"{self.question_id}: text must carry the English pivot wording "
                f"(lang={PIVOT_LANG!r}) — it is the canonical form the comparison layer uses"
            )
        if self.tier == QuestionTier.TEMPLATE and self.template_key is None:
            raise ValueError(
                f"{self.question_id}: a template-tier question must name its template_key"
            )
        if self.tier == QuestionTier.READER and self.template_key is not None:
            raise ValueError(
                f"{self.question_id}: a reader-tier question must not carry a template_key"
            )
        return self


class QuestionSet(Record):
    """One topic's versioned question set — the ``questions`` stage artifact.

    ``question_set_version`` is the run ID that produced this set; answers and analysis
    join on it, so re-generating questions produces a new version and new downstream
    runs rather than silently changing what yesterday's answers meant.
    """

    topic_id: str
    question_set_version: str = Field(min_length=1)
    questions: list[Question] = Field(min_length=1)
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @model_validator(mode="after")
    def _unique(self) -> "QuestionSet":
        ids = [q.question_id for q in self.questions]
        if len(set(ids)) != len(ids):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate question_id: {dupes}")
        wrong_topic = [q.question_id for q in self.questions if q.topic_id != self.topic_id]
        if wrong_topic:
            raise ValueError(f"questions belong to another topic: {wrong_topic}")
        active_keys = [
            q.template_key
            for q in self.questions
            if q.template_key is not None and q.status == QuestionStatus.ACTIVE
        ]
        if len(set(active_keys)) != len(active_keys):
            dupes = sorted({k.value for k in active_keys if active_keys.count(k) > 1})
            raise ValueError(f"template_key instantiated twice among active questions: {dupes}")
        return self

    @property
    def active(self) -> list[Question]:
        return [q for q in self.questions if q.status == QuestionStatus.ACTIVE]

    def by_id(self, question_id: str) -> Optional[Question]:
        return next((q for q in self.questions if q.question_id == question_id), None)


class ClusterAnswer(Record):
    """One reporting cluster's answer to one question — the annotation atom (V-1).

    ``addressed=false`` states that this annotation pass found no place in the cluster
    that answers the question.  It is annotation-layer silence — "we found no cluster
    that…", never "the words don't exist somewhere" (non-negotiable 5) — and therefore
    carries no summary, no category and no anchors.  ``addressed=true`` requires all
    three at construction time: there is no code path that records an answer and
    attaches its evidence later (non-negotiable 2).
    """

    answer_id: str
    topic_id: str
    question_id: str
    question_set_version: str = Field(min_length=1)
    reporting_cluster_id: str
    #: Lower-case side, redundant with the cluster ID's group on purpose: analysis
    #: artifacts key on ``group_id`` and the model check keeps the two consistent.
    group_id: str = Field(pattern=r"^[a-z]{2,5}$")
    addressed: bool
    #: One or two sentences saying what THIS cluster's answer is, in **English pivot**
    #: (AGENTS.md §4: verbatim evidence keeps the source's language, Q×A summaries do
    #: not).  A statement about the text, never about the world, and never a count.
    answer_summary: Optional[LangText] = None
    #: Normalized snake_case English category, countable across clusters and sides.
    answer_category: Optional[str] = None
    #: Sentence anchors supporting the answer.  May span several member articles of the
    #: same cluster; every anchor's article group must match ``group_id`` (whether the
    #: article is truly a member of the cluster needs the corpus run and is checked at
    #: the set level by ``validate_answers``).
    evidence: list[str] = Field(default_factory=list)
    #: Retired (analyze refactor D-b): the 0–1 scale was never calibrated
    #: across topics and no computation may read it.  "Addressed but the answer resists
    #: bucketing" is expressed as ``answer_category="unclear"`` instead.  Optional so
    #: pre-retirement answer files still deserialize; new annotation passes do not write it.
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    #: Free note for judgement calls a reviewer should see — e.g. entity normalisation
    #: ("范塔·欧 and 范塔·阿夫 are both Fanta Aw, counted as one voice").
    notes: Optional[LangText] = None
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @field_validator("reporting_cluster_id")
    @classmethod
    def _cluster(cls, v: str) -> str:
        return validate_cluster_id(v)

    @field_validator("answer_category")
    @classmethod
    def _category(cls, v: Optional[str]) -> Optional[str]:
        return validate_answer_category(v) if v is not None else None

    @field_validator("evidence")
    @classmethod
    def _evidence_grammar(cls, v: list[str]) -> list[str]:
        for sid in v:
            SentenceId.parse(sid)
        if len(set(v)) != len(v):
            raise ValueError(f"duplicate sentence IDs in evidence: {v}")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> "ClusterAnswer":
        parsed = parse_prefixed_id(self.answer_id, "ANS")
        if not topic_slug_matches(parsed.topic_slug, self.topic_id):
            raise ValueError(
                f"answer_id topic slug {parsed.topic_slug!r} does not match "
                f"topic_id {self.topic_id!r}"
            )
        parse_prefixed_id(self.question_id, "QST")
        cluster_group = CLUSTER_ID_RE.match(self.reporting_cluster_id).group("group")
        if cluster_group.lower() != self.group_id:
            raise ValueError(
                f"{self.answer_id}: group_id {self.group_id!r} does not match cluster "
                f"{self.reporting_cluster_id!r}"
            )
        foreign = sorted(
            {
                sid
                for sid in self.evidence
                if SentenceId.parse(sid).group != cluster_group
            }
        )
        if foreign:
            raise ValueError(
                f"{self.answer_id}: evidence must come from group {cluster_group}; "
                f"foreign anchors: {foreign}"
            )
        if self.addressed:
            missing = [
                name
                for name, value in (
                    ("answer_summary", self.answer_summary),
                    ("answer_category", self.answer_category),
                    ("evidence", self.evidence or None),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    f"{self.answer_id}: addressed=true requires {missing} — an answer "
                    "without its summary, category and anchors is not an answer "
                    "(non-negotiable 2)"
                )
        else:
            present = [
                name
                for name, value in (
                    ("answer_summary", self.answer_summary),
                    ("answer_category", self.answer_category),
                    ("evidence", self.evidence or None),
                )
                if value is not None
            ]
            if present:
                raise ValueError(
                    f"{self.answer_id}: addressed=false must not carry {present} — "
                    "silence has no answer content; if there is evidence, the question "
                    "is addressed"
                )
        return self

    @property
    def evidence_ids(self) -> list[SentenceId]:
        return sorted(SentenceId.parse(s) for s in self.evidence)

    @property
    def is_comparable(self) -> bool:
        """Whether this answer can enter a cross-side category comparison."""
        return self.addressed and self.answer_category != ANSWER_CATEGORY_UNCLEAR
