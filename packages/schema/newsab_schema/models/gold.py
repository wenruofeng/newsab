"""Gold-standard annotation format (blueprint ⑤; §4.6 lists it as still-to-define).

Two things the user produces by hand and nothing else can substitute for:

* hand-annotated observations, used as the S4 quality baseline and the judge-calibration
  set;
* four-axis human scores on candidate angles, which are simultaneously the Phase 0
  acceptance gate (⑥) and the target variable A1 metrics are selected against (⑤).

The one design decision worth flagging: ``fully_annotated_articles``.  Precision can be
measured against any sample of gold labels, but **recall cannot** — a machine observation
with no gold counterpart is only a false positive if the human was labelling exhaustively.
Recording which articles were done exhaustively is what makes recall an honest number
rather than a flattering one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import Field, field_validator, model_validator

from ..common import LangText, Record
from ..enums import HUMAN_SCORE_AXES, Dimension
from ..ids import (
    SentenceId,
    parse_prefixed_id,
    validate_article_id,
    validate_topic_id,
)
from .annotation import _validate_attrs


class Annotator(Record):
    """Who produced a gold label.  ``is_founder`` matters because ⑤ reserves certain
    judgements (the acceptance scoring) to the user specifically."""

    annotator_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    is_founder: bool = False
    #: Languages this annotator can verify first-hand.  The user can verify zh+en only
    #: (§0.1); a label outside an annotator's languages is a judge-extrapolation, not a
    #: gold label, and the eval report has to say so.
    verifiable_langs: list[str] = Field(default_factory=list)


class GoldObservation(Record):
    """A human-authored observation, shaped to compare 1:1 with S4 output (§4.2)."""

    gold_id: str = Field(pattern=r"^GOLD-OBS-\d{6}$")
    topic_id: str
    article_id: str
    dimension: Dimension
    subject: str = Field(min_length=1, max_length=120)
    concept_surface: str = Field(min_length=1)
    proposition: LangText
    attrs: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(min_length=1)
    #: Human confidence, kept optional: forcing a number where the annotator has none
    #: manufactures precision.
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    annotator_id: str
    annotated_at: datetime
    note: Optional[LangText] = None

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @field_validator("article_id")
    @classmethod
    def _article(cls, v: str) -> str:
        return validate_article_id(v)

    @field_validator("annotated_at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _consistency(self) -> "GoldObservation":
        foreign = sorted(
            {s for s in self.evidence if SentenceId.parse(s).article_id != self.article_id}
        )
        if foreign:
            raise ValueError(f"evidence must all belong to {self.article_id}; got {foreign}")
        _validate_attrs(self.dimension, self.attrs)
        return self


class HumanAngleScore(Record):
    """The four-axis score from blueprint ⑤, 1–5 per axis."""

    interesting: int = Field(ge=1, le=5)
    clear: int = Field(ge=1, le=5)
    defensible: int = Field(ge=1, le=5)
    distinct: int = Field(ge=1, le=5)

    @property
    def as_dict(self) -> dict[str, int]:
        return {axis: getattr(self, axis) for axis in HUMAN_SCORE_AXES}


class GoldAngleScore(Record):
    """One annotator's verdict on one candidate angle.

    ``previously_aware`` is the operational form of ⑥'s acceptance criterion "the user
    was not already aware of most of them" — it has to be asked *per angle*, before the
    angle set is seen as a whole, or the answer is hindsight.
    """

    topic_id: str
    angle_id: str
    annotator_id: str
    scores: HumanAngleScore
    #: Did the annotator already believe this before seeing the pipeline output?
    previously_aware: bool
    #: Spot-check result: did the cited evidence actually support the angle?
    evidence_spot_check: Optional[bool] = None
    note: Optional[LangText] = None
    scored_at: datetime

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @field_validator("angle_id")
    @classmethod
    def _angle(cls, v: str) -> str:
        parse_prefixed_id(v, "ANG")
        return v

    @field_validator("scored_at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)


class GoldStandardSet(Record):
    """The whole gold set for one topic, at one protocol version."""

    topic_id: str
    set_version: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    annotators: list[Annotator] = Field(min_length=1)
    observations: list[GoldObservation] = Field(default_factory=list)
    #: Articles annotated exhaustively.  Recall is computed only over these (see module
    #: docstring); everything else contributes to precision only.
    fully_annotated_articles: list[str] = Field(default_factory=list)
    angle_scores: list[GoldAngleScore] = Field(default_factory=list)
    #: Articles double-annotated for inter-annotator agreement.
    double_annotated_articles: list[str] = Field(default_factory=list)

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @field_validator("fully_annotated_articles", "double_annotated_articles")
    @classmethod
    def _articles(cls, v: list[str]) -> list[str]:
        return [validate_article_id(a) for a in v]

    @model_validator(mode="after")
    def _refs(self) -> "GoldStandardSet":
        known = {a.annotator_id for a in self.annotators}
        unknown = sorted(
            {o.annotator_id for o in self.observations if o.annotator_id not in known}
            | {s.annotator_id for s in self.angle_scores if s.annotator_id not in known}
        )
        if unknown:
            raise ValueError(f"labels reference undeclared annotators: {unknown}")
        for scope in (self.observations, self.angle_scores):
            wrong = sorted({r.topic_id for r in scope if r.topic_id != self.topic_id})
            if wrong:
                raise ValueError(f"records from other topics in this set: {wrong}")
        gold_ids = [o.gold_id for o in self.observations]
        if len(set(gold_ids)) != len(gold_ids):
            raise ValueError("duplicate gold_id in observations")
        annotated = {o.article_id for o in self.observations}
        missing = sorted(set(self.fully_annotated_articles) - annotated)
        if missing:
            raise ValueError(
                "articles declared fully annotated but carrying no observations: "
                f"{missing} — if an article genuinely has none, say so in the run log "
                "rather than leaving it silently empty (D5)"
            )
        return self

    def by_article(self, article_id: str) -> list[GoldObservation]:
        return [o for o in self.observations if o.article_id == article_id]
