"""The reader page (value_chain.md "The product").

One topic = one page: intro → storyline angle blocks (question + both sides' answers +
verbatim quotes + count badges) → data visuals → the annotation data view → "How we
counted" appendix.
This container replaces the ANG/G2-era ``EditorialPage`` for value-chain pages; the old
model stays for reading Phase 0 artifacts.

Design rules carried over from the claim machinery (§4.5, non-negotiable 2):

* every reader-facing sentence is a :class:`PageClaim` — one claim type, one provenance
  path, bound at generation time;
* quote text is **never stored here** — a quote is a sentence ID (plus translations);
  the renderer pulls the verbatim text from the corpus, so a page cannot misquote
  without the mechanical checks noticing (and full text never ships, non-negotiable 7);
* every number is a :class:`CountBadge` naming what it recomputes from — no number in a
  generated document is ever retyped by hand;
* run IDs live in the ``how_we_counted`` appendix block, never in the reader flow.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import Field, field_validator, model_validator

from ..common import LangText, MultiLangText, Provenance, Record
from ..enums import ClaimType, FindingKind
from ..ids import is_sentence_id, parse_prefixed_id, validate_topic_id
from .qa import validate_answer_category


class PageClaim(Record):
    """One reader-facing sentence with its provenance path (§4.5, inline form).

    ``source_claim``: someone said this — anchors point at where.
    ``corpus_aggregate``: our sample counts like this — ``computed_from`` names the
    finding/stat path the number recomputes from, anchors illustrate.
    ``corpus_reading``: we read the coverage and this is what it says — ≥ 2 anchors,
    no number, no ``computed_from``.
    """

    text: MultiLangText
    claim_type: ClaimType
    evidence: list[str] = Field(default_factory=list)
    #: e.g. ``FND-aabb-river-light-001`` or ``QST-aabb-river-light-003:cn.clusters_addressed``.
    computed_from: Optional[str] = None

    @field_validator("evidence")
    @classmethod
    def _anchors(cls, v: list[str]) -> list[str]:
        for sid in v:
            if not is_sentence_id(sid):
                raise ValueError(f"claim evidence must be sentence IDs, got {sid!r}")
        if len(set(v)) != len(v):
            raise ValueError(f"duplicate sentence IDs in evidence: {v}")
        return v

    @model_validator(mode="after")
    def _typed(self) -> "PageClaim":
        if "en" not in self.text.values:
            raise ValueError("claim text must include the English pivot master (D6)")
        if self.claim_type == ClaimType.SOURCE_CLAIM:
            if not self.evidence:
                raise ValueError("source_claim needs at least one sentence anchor")
            if self.computed_from:
                raise ValueError("source_claim carries no computed_from (§4.5)")
        elif self.claim_type == ClaimType.CORPUS_AGGREGATE:
            if not self.computed_from:
                raise ValueError("corpus_aggregate must name computed_from (§4.5)")
        elif self.claim_type == ClaimType.CORPUS_READING:
            if self.computed_from:
                raise ValueError("corpus_reading carries no computed_from (§4.5)")
            if len(self.evidence) < 2:
                raise ValueError(
                    "corpus_reading characterises a body of coverage and needs ≥ 2 anchors"
                )
        return self


class Quote(Record):
    """A verbatim quote reference: the sentence ID plus reader-language translations.

    The original text is resolved from the corpus at render time — URL + verbatim
    sentence is the public form (non-negotiable 7).
    """

    sentence_id: str
    translation: Optional[MultiLangText] = None

    @field_validator("sentence_id")
    @classmethod
    def _anchor(cls, v: str) -> str:
        if not is_sentence_id(v):
            raise ValueError(f"quote must reference a sentence ID, got {v!r}")
        return v


class CountBadge(Record):
    """The clickable count ("11 of 12 clusters") behind one side's answer.

    ``computed_from`` names the finding whose group stats these numbers recompute
    from; the pre-render checks re-derive them and refuse the page on mismatch.
    """

    group_id: str = Field(pattern=r"^[a-z]{2,5}$")
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    #: What is being counted, reader-worded per language ("clusters covering this",
    #: "报道组").  The unit is always independent reporting clusters (non-negotiable 3).
    label: Optional[MultiLangText] = None
    computed_from: str = Field(min_length=1)

    @model_validator(mode="after")
    def _sane(self) -> "CountBadge":
        if self.numerator > self.denominator:
            raise ValueError(
                f"badge {self.numerator}/{self.denominator} exceeds denominator"
            )
        return self


class SideAnswerBlock(Record):
    """One side of one angle: the plain-language answer, its quotes, its badge.

    ``answer_label`` is the three-to-eight-word form of the answer the renderer puts on
    the answer card *above* the two side blocks, so a reader meets "what this coverage
    answers" before meeting the paragraph explaining it.  It is short reader
    language — the writer's job — but ``answer_category`` binds it to the counted
    category underneath, and the checks refuse a label whose category does not recompute
    from the finding.
    """

    group_id: str = Field(pattern=r"^[a-z]{2,5}$")
    answer: PageClaim
    #: The answer in a headline-length phrase, per reader language.
    answer_label: Optional[MultiLangText] = None
    #: The ``answer_category`` (as the annotate stage spells it) that ``answer_label``
    #: puts into reader words.  Required whenever the badge counts a modal category.
    answer_category: Optional[str] = None
    quotes: list[Quote] = Field(default_factory=list)
    badge: CountBadge
    #: True when this side is the quiet one of an attention_gap (or legacy blindspot)
    #: angle: the answer text states annotation-layer near-silence, and the block gets
    #: no answer card and no writer-picked quotes.  The renderer still lists whatever
    #: few addressed clusters exist (qa-0.4.0: a quiet side may have one or two), so
    #: the reader sees the mentions without the page asserting an answer for them.
    is_silent_side: bool = False

    @model_validator(mode="after")
    def _sides(self) -> "SideAnswerBlock":
        if self.badge.group_id != self.group_id:
            raise ValueError("badge belongs to another group")
        prefix = f"{self.group_id.upper()}_"
        foreign = sorted(
            {q.sentence_id for q in self.quotes if not q.sentence_id.startswith(prefix)}
        )
        if foreign:
            raise ValueError(
                f"a {self.group_id} side block quotes the other side: {foreign}"
            )
        if self.is_silent_side and self.quotes:
            raise ValueError(
                "a silent side has no writer-picked quotes — the renderer lists its "
                "few mentions itself"
            )
        if self.is_silent_side and (self.answer_label or self.answer_category):
            raise ValueError(
                "a silent side has no answer to put on a card — the renderer words its "
                "annotation-layer silence itself"
            )
        if self.answer_category is not None:
            validate_answer_category(self.answer_category)
        if not self.is_silent_side and not self.quotes:
            raise ValueError("a speaking side needs at least one verbatim quote")
        return self


class AngleBlock(Record):
    """One storyline angle: a question, both sides' answers, the evidence."""

    rank: int = Field(ge=1)
    question_id: str
    #: The finding this angle asserts.  The pre-render checks refuse an angle whose
    #: finding is marked unsupported (V-3), and require a caveat when it is weak.
    finding_id: str
    kind: FindingKind
    #: The question as the reader should meet it (may be sharper than the annotation
    #: wording, but must ask the same thing).  Normally left unset now: the reader wording
    #: of every question lives once in :class:`ReaderLexicon`, so the storyline and the
    #: annotation data view cannot drift apart.  Set here only to override the lexicon for
    #: this one angle.
    question_display: Optional[MultiLangText] = None
    sides: list[SideAnswerBlock] = Field(min_length=2, max_length=2)
    #: Optional deeper material shown on expansion.
    detail: list[PageClaim] = Field(default_factory=list)
    #: Reader-worded caveat badge (used sparingly; only load-bearing warnings).
    caveat: Optional[MultiLangText] = None
    #: One writer's sentence on why a reader would care about this angle (analyze
    #: refactor D-f): the mechanical candidate ranking orders the pool, but "interesting"
    #: is an editorial judgement and this is its audit trail.  English pivot.
    editorial_interest: Optional[LangText] = None
    #: The one answer *both* coverages give, worded once for the answer cards.
    #: Allowed only when both sides name the same ``answer_category`` — that is what
    #: "both sides agree" means here, and both cards then carry the same words.
    shared_answer_label: Optional[MultiLangText] = None
    #: One paragraph written for *both* sides instead of one per side, rendered as a
    #: single full-width column.  Some angles are one thought — where a
    #: divergence comes from, why an agreement is not the obvious answer — and splitting
    #: that thought in two produces symmetrical filler
    #: ("the question here is…", "the question here is likewise…").  When set, the
    #: renderer draws this instead of the two side paragraphs; the side paragraphs stay
    #: required by the schema, since the checks still bind each side's claim to its
    #: anchors.
    commentary_joint: Optional[PageClaim] = None

    @model_validator(mode="after")
    def _ids(self) -> "AngleBlock":
        parse_prefixed_id(self.question_id, "QST")
        parse_prefixed_id(self.finding_id, "FND")
        groups = [s.group_id for s in self.sides]
        if len(set(groups)) != 2:
            raise ValueError(f"an angle needs two distinct sides, got {groups}")
        if self.kind == FindingKind.BLINDSPOT and not any(
            s.is_silent_side for s in self.sides
        ):
            raise ValueError("a blindspot angle must mark its silent side")
        if self.kind not in (FindingKind.BLINDSPOT, FindingKind.ATTENTION_GAP) and any(
            s.is_silent_side for s in self.sides
        ):
            # Under qa-0.4.0 an attention_gap angle always marks its finding's quiet
            # side — that pairing needs the finding, so page_checks enforces it (the
            # schema stays loose enough to load pre-0.4.0 pages, whose gap angles had
            # two speaking sides).
            raise ValueError(
                "only blindspot and attention_gap angles have a silent side"
            )
        if self.shared_answer_label is not None:
            categories = {s.answer_category for s in self.sides}
            if len(categories) != 1 or None in categories:
                raise ValueError(
                    "shared_answer_label says both sides give the same answer, but the "
                    f"sides name {sorted(str(c) for c in categories)}"
                )
        return self

    @property
    def shared_category(self) -> Optional[str]:
        """The category both sides answer with, when there is one."""
        categories = {s.answer_category for s in self.sides}
        if len(categories) == 1 and None not in categories:
            return next(iter(categories))
        return None


class ReaderLexicon(Record):
    """Reader wording for the machine vocabulary the page displays.

    Three vocabularies reach the reader that were never written for one:

    * **question wording** — the annotate stage writes questions for an annotator
      ("What is presented as the problem — what the new visa rules respond to, or the
      rules themselves?"). Those qualifiers make the annotation reproducible and make the
      question unreadable. The reader gets the same question asked plainly ("在整个事件
      里，问题出在哪儿？"); it must ask the same thing, never a different or narrower one.
    * **answer categories** — ``international_students_generally`` is a counting key, not
      a phrase. Every category the page displays needs a short reader label.
    * **topics raised** — collect stores a source phrase plus an English pivot.  The pivot
      is the stable cross-language concept key, not Chinese reader copy; render/localize
      translates that concept instead of reverse-looking-up the article's wording.

    Both are written once per page and localized with the rest of it, so the storyline,
    the answer cards and the annotation data view all say the same words. Entries the page
    does not carry fall back to the annotation wording (questions) or the raw key
    (categories) — a missing entry degrades the page, it never fabricates one.
    """

    #: ``QST-…`` → the question as a reader should meet it.
    questions: dict[str, MultiLangText] = Field(default_factory=dict)
    #: ``answer_category`` → its short reader label.
    categories: dict[str, MultiLangText] = Field(default_factory=dict)
    #: A manifest scope bullet (verbatim English original) → its reader wording.
    #: ``TopicManifest.scope_hash()`` covers every manifest field, so a translation
    #: stored there would invalidate the signed-off ``scope_approval`` of every topic
    #: already collected. The scope panel is reader-facing text like any other, so its
    #: translations live here and are localized with the rest of the page.
    scope: dict[str, MultiLangText] = Field(default_factory=dict)
    #: A collect-stage ``topics_raised.pivot_en`` concept → its reader wording.
    topics: dict[str, MultiLangText] = Field(default_factory=dict)
    #: ``group_id`` → the side's full noun phrase / two-to-four-character pronoun /
    #: definition, in languages beyond what ``TopicManifest.groups[].label`` (etc.)
    #: already carries. Same problem as ``scope`` above: ``TopicManifest.scope_hash()``
    #: covers every manifest field, including these three, so writing a new-site-language
    #: translation straight into the manifest would invalidate the signed-off
    #: ``scope_approval`` of every topic already collected. These three dicts hold
    #: the multilingual completion instead — the renderer prefers an entry here over the
    #: manifest's own value when both exist for a language, and falls back to the
    #: manifest (English, if that is all the manifest has) when a ``group_id`` or a
    #: language is missing here. A missing entry degrades the page, it never fabricates
    #: one, same rule as every other lexicon field.
    group_labels: dict[str, MultiLangText] = Field(default_factory=dict)
    group_short_labels: dict[str, MultiLangText] = Field(default_factory=dict)
    group_definitions: dict[str, MultiLangText] = Field(default_factory=dict)

    @field_validator("group_labels", "group_short_labels", "group_definitions")
    @classmethod
    def _group_ids(cls, v: dict) -> dict:
        for group_id in v:
            if not re.fullmatch(r"[a-z]{2,5}", group_id):
                raise ValueError(f"lexicon group key {group_id!r} is not a group_id")
        return v

    @field_validator("questions")
    @classmethod
    def _question_ids(cls, v: dict) -> dict:
        for question_id in v:
            parse_prefixed_id(question_id, "QST")
        return v

    @field_validator("categories")
    @classmethod
    def _categories(cls, v: dict) -> dict:
        for category in v:
            validate_answer_category(category)
        return v


class Visual(Record):
    """A data visual that carries story weight (never decoration).

    Rendered deterministically from the named analysis artifact; obeys the same
    discipline as sentences — an unsupported contrast may not be drawn (V-3).

    ``concept_cloud`` is the one kind that is not about a question: it sums every side's
    ``category_counts`` across the whole question set and draws the two answer
    vocabularies side by side.  It asserts nothing and compares nothing — two raw
    distributions, normalized by each side's own total — so it carries no ``question_id``
    and V-3 has nothing to bite on.
    """

    kind: str = Field(
        pattern=r"^(answer_distribution|addressed_rates|coverage_timeline|concept_cloud)$"
    )
    question_id: Optional[str] = None
    caption: MultiLangText
    #: The artifact path the renderer reads, e.g. ``qa_run:question_stats``.
    data_from: str = Field(min_length=1)

    @model_validator(mode="after")
    def _kind(self) -> "Visual":
        if self.kind == "concept_cloud" and self.question_id:
            raise ValueError(
                "a concept_cloud collapses the question dimension — it cannot name one "
                f"question ({self.question_id})"
            )
        return self


class HowWeCounted(Record):
    """The methodology appendix block — the only place run IDs may appear."""

    corpus_run_id: str = Field(min_length=1)
    questions_run_id: str = Field(min_length=1)
    answers_run_id: str = Field(min_length=1)
    qa_run_id: str = Field(min_length=1)
    #: Deprecated compatibility field; renderer, checker and judge ignore it.
    notes: list[MultiLangText] = Field(default_factory=list)


class ReaderPage(Record):
    """The whole reader page for one topic (value_chain "The product")."""

    topic_id: str
    title: MultiLangText
    #: A short briefing for a half-informed reader: what happened, to whom, and over what
    #: window. Long enough to orient someone who has read nothing (4–6 claims), never a
    #: summary of the findings.
    intro: list[PageClaim] = Field(min_length=1, max_length=6)
    #: Retired: the striking contrast is the first angle card, so a
    #: pull quote above it said the same thing twice. Kept optional so pages written
    #: before that still load; the renderer does not draw it.
    hook: Optional[PageClaim] = None
    angles: list[AngleBlock] = Field(min_length=1, max_length=6)
    #: Reader wording for the questions and answer categories this page displays.
    lexicon: ReaderLexicon = Field(default_factory=lambda: ReaderLexicon())
    visuals: list[Visual] = Field(default_factory=list)
    how_we_counted: HowWeCounted
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @model_validator(mode="after")
    def _ranks(self) -> "ReaderPage":
        ranks = [a.rank for a in self.angles]
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise ValueError(
                f"angle ranks must be 1..n with no gaps or ties, got {ranks}"
            )
        questions = [a.question_id for a in self.angles]
        if len(set(questions)) != len(questions):
            raise ValueError(f"a question has two angle blocks: {questions}")
        return self


# Legacy class name: this is now a machine-owned pin block used to build the page record.
# Writers do not author its display.
