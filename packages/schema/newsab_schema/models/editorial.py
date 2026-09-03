"""S5 angle cards and the S7 page container (§2.4, §3.3 S5/S7).

Blueprint §4 defines the *claim* (§4.5) but left the containers around it in the pending
list (§4.6).  They are defined here because S5 and S7 cannot emit anything without them,
and because the page's three-layer structure (§2.4) is a promise about provenance, not
about CSS: the overview layer is what a reader sees before clicking, so it is exactly the
layer where an unsupported sentence does the most damage.  Making "which claims are in the
overview" a field, rather than a rendering decision, is what lets S8 check the promise.

Two rules that shape everything here:

* **Strict RAG (§3.3 S5).**  An angle card may only say what its anchors support, so
  ``evidence`` is required and non-empty even for a silence card — a silence card's
  anchors are the sentences that show the side discussing the topic *without* the thing
  that is absent.
* **One master, many localisations (D6).**  S5 writes in the source's own language;
  S7 writes the English pivot.  Neither may be re-researched per reader language; S9
  translates the master.
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field, field_validator, model_validator

from ..common import LangText, MultiLangText, Provenance, Record
from ..enums import AngleType
from ..ids import is_sentence_id, parse_prefixed_id, validate_topic_id


class NotablePhrase(Record):
    """A wording worth showing the reader, anchored to where it was used."""

    phrase: str = Field(min_length=1)
    sentence_id: str
    gloss: Optional[LangText] = None

    @field_validator("sentence_id")
    @classmethod
    def _anchor(cls, v: str) -> str:
        if not is_sentence_id(v):
            raise ValueError(f"notable phrase anchor must be a sentence ID, got {v!r}")
        return v


class AngleCard(Record):
    """One side's reading of one angle, in that side's own language (§3.3 S5).

    Deliberately *not* comparative: the card says what the sampled coverage on this side
    does, and nothing about the other side.  The comparison happens once, in S7, in the
    pivot language — that is what D6 buys, and writing "unlike the Chinese coverage…" here
    would smuggle the comparison into a stage that never read the other side.
    """

    card_id: str = Field(pattern=r"^CARD-[a-z0-9-]+-\d{4}-[a-z]{2,5}$")
    topic_id: str
    angle_id: str
    group_id: str = Field(pattern=r"^[a-z]{2,5}$")
    #: The source's own language (§1.6 L1).  S9 localises; S5 never does.
    lang: str = Field(min_length=2)

    #: Overview layer (§2.4): one sentence a reader sees without clicking.
    stance_summary: LangText
    #: Expand layer (§2.4): who speaks on this side, how, and with what wording.
    structured_summary: LangText
    notable_language: list[NotablePhrase] = Field(default_factory=list)

    #: True when this side is the quiet one.  A silence card still carries anchors: it has
    #: to show the side covering the topic while not doing the thing (D5 — silence is data,
    #: and "we did not annotate it" is a different statement from "the text lacks it").
    is_silence_card: bool = False
    #: What the reader must know before believing the card: thin denominator, one outlet
    #: dominating this side, an annotation-layer rather than text-layer absence.
    caveat: Optional[LangText] = None

    #: Every sentence this card is allowed to rest on (§3.3 S5 strict RAG).
    evidence: list[str] = Field(min_length=1)
    #: Copied from the angle's own comparison so the card and the page cannot disagree;
    #: recomputable from ``angle_id`` + the A1 run, and S8 recomputes them.
    clusters_supporting: int = Field(ge=0)
    clusters_total: int = Field(ge=0)

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
                    f"angle card evidence must be sentence IDs, got {sid!r} "
                    "(free-form URL citation is forbidden, §3.2)"
                )
        if len(set(v)) != len(v):
            raise ValueError(f"duplicate sentence IDs in evidence: {v}")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "AngleCard":
        parse_prefixed_id(self.angle_id, "ANG")
        if self.clusters_supporting > self.clusters_total:
            raise ValueError(
                f"{self.card_id}: {self.clusters_supporting} supporting clusters out of "
                f"{self.clusters_total} total"
            )
        if not self.card_id.endswith(f"-{self.group_id}"):
            raise ValueError(f"{self.card_id} does not end in its group_id {self.group_id!r}")
        # Every anchor must belong to an article of this side.  Article IDs are
        # ``{GROUP}_{key}`` (§ids), so this is checkable without opening the corpus, and it
        # is the invariant that keeps a one-side card from quoting the other side.
        prefix = f"{self.group_id.upper()}_"
        foreign = sorted({s for s in self.evidence if not s.startswith(prefix)})
        if foreign:
            raise ValueError(
                f"{self.card_id} is a {self.group_id} card but cites {foreign}; the "
                "comparison belongs to S7, not to a side card"
            )
        return self


class PageNote(Record):
    """A caveat that must reach the reader, and where the obligation came from.

    ``source`` is load-bearing: ``founder_annotation`` is something a human wrote at a
    gate, ``dossier_caveat`` is something an agent carried forward on its own authority,
    and ``sampling`` is derived from the corpus.  Collapsing them would let an agent's
    self-assessment acquire a human's authority (AGENTS.md §8).
    """

    note_id: str = Field(min_length=1)
    source: str = Field(pattern=r"^(founder_annotation|dossier_caveat|sampling)$")
    text: MultiLangText
    #: ``page`` shows it site-wide for the topic; an ``ANG-…`` id pins it to one card.
    scope: str = Field(min_length=1)


class AngleSection(Record):
    """One angle card's worth of page (§2.4's three layers), as claim references.

    Layers are stored as claim ID lists rather than as prose, so "what does the reader see
    before clicking" is a machine-checkable question.  S8 uses it: an overview layer
    holding a claim with no evidence is the single most damaging defect this format has.
    """

    angle_id: str
    rank: int = Field(ge=1)
    angle_type: AngleType
    headline: MultiLangText
    #: Overview layer — visible without interaction.
    overview_claims: list[str] = Field(min_length=1)
    #: Expand layer — shown on click.
    detail_claims: list[str] = Field(default_factory=list)
    #: The side cards this section renders, by ``card_id``.
    cards: list[str] = Field(default_factory=list)
    #: Set when the angle's own gate reading no longer holds but D21 keeps it published.
    gate_status: Optional[str] = None

    @model_validator(mode="after")
    def _ids(self) -> "AngleSection":
        parse_prefixed_id(self.angle_id, "ANG")
        for claim_id in [*self.overview_claims, *self.detail_claims]:
            parse_prefixed_id(claim_id, "CLM")
        if set(self.overview_claims) & set(self.detail_claims):
            raise ValueError(
                f"{self.angle_id}: a claim appears in both the overview and detail layers; "
                "a reader would see it twice and S8 would check it twice"
            )
        return self


class EditorialPage(Record):
    """The whole comparison page for one topic, before localisation (§3.3 S7).

    It holds structure and references only.  The sentences live in ``Claim`` records and
    the side prose in ``AngleCard`` records, because those are the units that carry
    provenance — a container that also held text would be a place for an unanchored
    sentence to hide.
    """

    topic_id: str
    #: The G2 ruling this page implements.  Without it there is no answer to "who approved
    #: publishing these questions", which is the first thing an auditor asks.
    g2_run_id: str = Field(min_length=1)
    s6_run_id: str = Field(min_length=1)
    a1_run_id: str = Field(min_length=1)
    corpus_run_id: str = Field(min_length=1)

    title: MultiLangText
    #: The one paragraph that frames what the reader is looking at, as claim references.
    standfirst_claims: list[str] = Field(default_factory=list)
    sections: list[AngleSection] = Field(min_length=1)
    notes: list[PageNote] = Field(default_factory=list)
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @model_validator(mode="after")
    def _sections(self) -> "EditorialPage":
        ranks = [s.rank for s in self.sections]
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise ValueError(f"section ranks must be 1..n with no gaps or ties, got {ranks}")
        angles = [s.angle_id for s in self.sections]
        if len(set(angles)) != len(angles):
            raise ValueError(f"an angle has two sections: {angles}")
        return self
