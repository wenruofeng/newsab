"""Corpus-side records: topic manifest, source registry, article + corpus run.

Blueprint §4.6 lists these three as *draft* schemas ("待定 schema 清单") whose outlines
live in §S0 / §1.5 / §S2.  They are pinned down here because S4 cannot validate a single
evidence anchor without knowing what an article looks like, and the pipeline needs a concrete
on-disk corpus format.  They are marked ``draft`` in ``SCHEMA_STATUS`` so that a later
session knows these may still move, unlike the §4 schemas.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from pydantic import Field, field_validator, model_validator

from ..common import LangText, MultiLangText, Provenance, Record, normalize_lang
from ..enums import (
    AccessLevel,
    GateDecider,
    HypothesisLayer,
    OriginType,
    RiskLevel,
    SeedQuestionMandate,
    SourceCategory,
    TopicStatus,
)
from ..ids import (
    GROUP_RE,
    CLUSTER_ID_RE,
    RUN_ID_RE,
    make_sentence_id,
    validate_article_id,
    validate_topic_id,
)

# --------------------------------------------------------------------------------------
# S0 — topic manifest
# --------------------------------------------------------------------------------------


class Group(Record):
    """One semantically defined side of a comparison.

    Membership is a collection-stage judgement against ``definition``.  It is deliberately
    not derived from a country/language tuple: a valid side may span countries, mix source
    languages, or be defined as "English coverage" versus "all other languages".
    ``prefix`` is the stable article-ID namespace; ``label`` is short reader-facing copy.
    """

    group_id: str = Field(pattern=r"^[a-z]{2,5}$")
    prefix: str = Field(pattern=r"^[A-Z]{2,5}$")
    label: MultiLangText
    #: The two-to-four character pronoun the reader page uses everywhere a side is named
    #: ("中方" / "美方", "China side" / "US side").  ``label`` is the full noun phrase and
    #: appears once, in the tag's tooltip; this is what a reader sees in running text, in
    #: card headers and in chart axes.  It is chosen at touchpoint one, with the rest of
    #: scope, because it is how the user and the reader will both refer to this side —
    #: the renderer only localizes ``group_id`` into it, it never invents one.
    short_label: MultiLangText
    definition: MultiLangText

    @model_validator(mode="after")
    def _prefix_matches(self) -> "Group":
        if self.prefix.lower() != self.group_id:
            raise ValueError(
                f"group_id {self.group_id!r} must be the lower-case form of prefix {self.prefix!r}"
            )
        return self


class Contributor(Record):
    """A human who put this topic forward and answers for it.

    Identity only — this is who a reader can hold responsible, not a role in the
    pipeline.  Both fields are optional: an external contributor may stay anonymous, and
    a contributor who does not want a public address simply carries no ``contact``.
    """

    name: Optional[str] = Field(default=None, min_length=1)
    contact: Optional[str] = Field(default=None, min_length=1)


class ScopeApproval(Record):
    """Touchpoint #1, bound to the exact scope fields that were approved.

    A model may stand in only when the user explicitly requests it.  The distinction is
    structural because a stand-in may approve reference seeds but cannot create a
    must-answer instruction for annotate.
    """

    approved_by: str = Field(min_length=1)
    approved_at: datetime
    scope_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    note: Optional[str] = None
    decided_by: GateDecider = GateDecider.HUMAN
    stand_in_model_id: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _recognize_legacy_stand_in(cls, raw: Any) -> Any:
        """Keep the one pre-field stand-in approval truthful without rewriting its topic."""
        if not isinstance(raw, dict) or raw.get("decided_by") is not None:
            return raw
        approved_by = str(raw.get("approved_by", ""))
        if "stand-in" not in approved_by.lower():
            return raw
        data = dict(raw)
        data["decided_by"] = GateDecider.LLM_STAND_IN.value
        match = re.search(r"\(([^()]+)\)\s*$", approved_by)
        if match and not data.get("stand_in_model_id"):
            data["stand_in_model_id"] = match.group(1)
        return data

    @field_validator("approved_at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _stand_in_is_named(self) -> "ScopeApproval":
        if self.decided_by == GateDecider.LLM_STAND_IN and not self.stand_in_model_id:
            raise ValueError("LLM stand-in scope approval must record stand_in_model_id")
        return self


class Period(Record):
    """The time window the topic is frozen to.  ``end=None`` means "still running"."""

    start: date
    end: Optional[date] = None

    @model_validator(mode="after")
    def _ordered(self) -> "Period":
        if self.end is not None and self.end < self.start:
            raise ValueError(f"period end {self.end} precedes start {self.start}")
        return self

    def contains(self, when: date) -> bool:
        return self.start <= when and (self.end is None or when <= self.end)


class QuestionSeed(Record):
    """One touchpoint-one question approved for annotate's input packet.

    Discovery origin deliberately does not travel here.  The annotator sees only the
    question's meaning and whether a human made it mandatory; audience-source notes remain
    in the scope-only candidate review artifact.
    """

    seed_id: str = Field(pattern=r"^SQ-[0-9]{3}$")
    text: MultiLangText
    mandate: SeedQuestionMandate = SeedQuestionMandate.REFERENCE


class TopicManifest(Record):
    """S0 output; the object gate G1 approves (§3.3 S0).

    G1 approves *scope and risk*, never a conclusion — which is why this record has no
    field for an expected finding, and why ``seed_questions`` is explicitly documented as
    retrieval-only (D9).
    """

    topic_id: str
    title: MultiLangText
    status: TopicStatus = TopicStatus.CANDIDATE
    groups: list[Group] = Field(min_length=2)
    period: Period
    #: Sub-topics inside scope. Must be specific: "who, what, which window" (§3.3 S0).
    include: list[str] = Field(min_length=1)
    exclude: list[str] = Field(default_factory=list)
    #: Blueprint §S0 calls this "矩阵四类" but never defines the four.  Left as free text
    #: pending a decision; do not invent a vocabulary for it.
    type: Optional[str] = None
    risk_level: RiskLevel = RiskLevel.MEDIUM
    #: Legacy pre-0.6 scope seeds. New scopes write ``question_seeds`` instead. Existing
    #: manifests remain readable and need no migration or rerun; annotate treats every
    #: legacy entry as reference-only.
    seed_questions: list[LangText] = Field(default_factory=list)
    #: The only scope questions annotate receives. ``reference`` is optional input;
    #: ``required`` must be represented by a semantically equivalent annotation question.
    #: Neither value may enter analyze thresholds or write-stage angle selection.
    question_seeds: list[QuestionSeed] = Field(default_factory=list)
    #: Adaptive target, not a quota (§3.3 S0).
    target_clusters_per_group: dict[str, int] = Field(default_factory=dict)
    #: Groups expected to produce near-zero independent coverage; exempt from the cluster
    #: target, because silence is the finding rather than a sampling failure (D5).
    expected_silence: list[str] = Field(default_factory=list)
    lead: Optional[MultiLangText] = None
    #: The humans who put this topic forward.  The page record names them above the
    #: signed scope, and — unless a stand-in is declared below — they are also who signs
    #: scope and who takes touchpoint two.  Empty reads as "anonymous".
    contributors: list[Contributor] = Field(default_factory=list)
    #: Declared at scope time: when set, an LLM stands in for the user at touchpoint
    #: two, and the page record names this model instead of a contributor.  It has to be
    #: known before the page is rendered, because the page states who reviews it and
    #: nothing may be injected into approved bytes afterwards (AGENTS.md §8 requires the
    #: stand-in fact to reach the published record).
    review_stand_in_model_id: Optional[str] = Field(default=None, min_length=1)
    #: The language the reviewer reads the page in at touchpoint two.  It lives beside
    #: the stand-in for the same reason: the page *states* who reviewed it, so it must
    #: also be able to state in which language — an approval is of one rendering, and a
    #: record that omits the language reads as "a human read this" when what happened is
    #: "a human read *this one*".  Known before render, never injected afterwards.
    #: ``None`` on manifests written before the field existed; the page then says who
    #: reviewed it and no more.
    review_locale: Optional[str] = Field(default=None, min_length=2)
    #: Explicit human touchpoint #1. ``status: active`` alone is not approval: an agent can
    #: set an enum. The hash makes later scope edits invalidate approval until confirmed.
    scope_approval: Optional[ScopeApproval] = None
    #: Containment threshold for reporting-cluster merging, when this topic needs one
    #: other than the package default.  It lives here because it sets the D7 denominator:
    #: a rebuild that silently fell back to the default would move every prevalence figure
    #: on the page without anyone choosing to.
    cluster_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    #: What happens to an already-approved angle set when a later corpus run adds
    #: articles (R-5).  ``inherit`` (default) carries the angles forward and marks any
    #: that no longer clear the R-gate for the next G2 to look at; ``recheck`` sends them
    #: back to G2 immediately.  G2 approves *the question*, not the numbers — numbers are
    #: expected to move as the corpus grows.
    angle_carryover: Literal["inherit", "recheck"] = "inherit"
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @field_validator("review_locale")
    @classmethod
    def _review_locale(cls, v: Optional[str]) -> Optional[str]:
        return normalize_lang(v) if v else None

    def group_by_id(self, group_id: str) -> Optional[Group]:
        return next((g for g in self.groups if g.group_id == group_id), None)

    def scope_hash(self) -> str:
        """Fingerprint only the fields the user approves at touchpoint #1."""
        payload = self.model_dump(
            mode="json",
            exclude={
                "status",
                "lead",
                "scope_approval",
                "provenance",
                # Who submitted the topic, and who will review the page, are not the
                # comparison boundary the user signs — and folding them in would
                # invalidate every approval already on disk.
                "contributors",
                "review_stand_in_model_id",
                "review_locale",
                # The clustering threshold is collection mechanics, not comparison
                # boundary: it varies per topic at the collecting agent's discretion
                # so it must not force a re-signature.
                # The corpus run still records the value every build actually used.
                "cluster_threshold",
            },
        )
        # Backward compatibility: adding the new field must not stale the hash-bound
        # approvals of existing topics that have no structured question seeds.
        if not payload.get("question_seeds"):
            payload.pop("question_seeds", None)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def scope_approval_problem(self) -> Optional[str]:
        if self.status != TopicStatus.ACTIVE:
            return f"topic status is {self.status.value!r}, not 'active'"
        if self.scope_approval is None:
            return "scope_approval is missing"
        actual = self.scope_hash()
        if self.scope_approval.scope_hash != actual:
            return (
                "scope changed after human approval: "
                f"recorded {self.scope_approval.scope_hash}, current {actual}"
            )
        return None

    @model_validator(mode="after")
    def _group_refs(self) -> "TopicManifest":
        ids = [g.group_id for g in self.groups]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate group_id in groups: {ids}")
        for key in list(self.target_clusters_per_group) + list(self.expected_silence):
            if key not in ids:
                raise ValueError(f"unknown group_id {key!r}; declared groups are {ids}")
        if self.seed_questions and self.question_seeds:
            raise ValueError(
                "legacy seed_questions and structured question_seeds cannot both be populated"
            )
        seed_ids = [seed.seed_id for seed in self.question_seeds]
        if len(set(seed_ids)) != len(seed_ids):
            raise ValueError(f"duplicate question seed ids: {seed_ids}")
        if (
            self.scope_approval is not None
            and self.scope_approval.decided_by == GateDecider.LLM_STAND_IN
            and any(seed.mandate == SeedQuestionMandate.REQUIRED for seed in self.question_seeds)
        ):
            raise ValueError(
                "an LLM stand-in may approve reference question seeds only; "
                "required is reserved to a human"
            )
        return self


class AngleHypothesis(Record):
    """S3 output (§3.3 S3).  A prior, and explicitly *not* a privilege: R-gate thresholds
    are identical for prior and data-discovered candidates (D9)."""

    angle_id: str
    topic_id: str
    title: LangText
    layer: HypothesisLayer
    rationale: LangText
    expected_tension_type: Optional[str] = None
    annotation_targets: list[str] = Field(default_factory=list)
    provenance: Provenance


# --------------------------------------------------------------------------------------
# Source registry — global, append-only, never frozen (R-3)
# --------------------------------------------------------------------------------------


class SourceChannel(Record):
    """The machine-usable half of the collection playbook (R-8).

    ``skills/collect/references/discovery*.md`` keeps the judgement calls — where
    a boundary case falls, how to triage a block.  What a *machine* needs to reach a source
    lives here so a collector does not have to read 260 lines of prose to find a URL
    template.  Absent fields mean "not established yet", never "does not exist".
    """

    #: URL template for the outlet's own search, with ``{query}`` / ``{page}`` placeholders.
    search_channel: Optional[str] = None
    #: How to turn a result page into article records: encoding quirks, JSON shape, the
    #: selector for the body, whether a browser is required.
    fetch_notes: Optional[str] = None
    #: Observed limit, in words a human can act on ("~2-3 requests then site-wide 405").
    rate_limit: Optional[str] = None
    #: The page/API field that settles reporting origin for this outlet
    #: (``newsDetail.isOrigin``, ``nodeInfo.name``, …).  Origin is a judgement everywhere
    #: else; where the outlet states it, say so.
    origin_field: Optional[str] = None
    #: ``ok`` — reachable. ``discovery_blocked`` — article pages fetch but no channel turns
    #: a keyword into URLs (a browser does not help: the problem is not knowing which URL
    #: to open). ``ip_blocked`` — a channel exists but the whole host rejects this IP after
    #: a few requests (a browser does not help either; the block is below the UA layer).
    #: Keeping these two apart is the difference between "search elsewhere" and "wait".
    status: Literal["ok", "discovery_blocked", "ip_blocked", "unknown"] = "unknown"
    checked_at: Optional[date] = None


#: Per-language ceiling on ``notes``, checked only for the languages listed here.  ``en``
#: is required, so it is always checked; the rest are optional localization-pass output
#: this model does not otherwise constrain, and only get a tighter number where CJK text
#: says the same thing in fewer characters.
_NOTES_CHAR_LIMITS: dict[str, int] = {"en": 400, "zh-CN": 200, "ja": 200}


class SourceEntry(Record):
    """One outlet in ``sources/registry.yaml`` (§1.5).

    Every field here is written and kept correct by **the agent that first meets the
    outlet**, at the moment it meets it (R-3).  There is no "a human will
    confirm this later" tier and no placeholder value: the operator looks at this file
    occasionally, never as the annotator of record.  So the model refuses an entry that a
    reader could not use — no slug standing in for a masthead, no missing English, no
    country code a filter cannot match.

    Deliberately no single "reliability score": §3.3 S1 rules it out because no one number
    can span media systems.  We record *what a source is*, not what it is worth.

    No ``group_id``: the registry spans topics, and membership belongs to an individual
    article in one comparison. The collector judges it against that topic's semantic group
    definitions and records the result explicitly in staging.
    """

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    #: Masthead in the outlet's own language (when that is not English), plus ``en``.
    #: ``en`` is required; anything further — including a translation into the site's own
    #: operating language — is the job of the localization pass, not of the agent
    #: registering the outlet, and a reader in a locale this entry has no name for falls
    #: back to ``en``.
    name: MultiLangText
    #: The outlet's front page — what a reader clicks in the media card.  Not the article
    #: URL that surfaced it, and not a section index unless the "outlet" really is one.
    url: str = Field(pattern=r"^https?://")
    lang: str
    #: ISO 3166-1 alpha-2, upper case, so that ``--country`` filters match exactly one
    #: spelling.  ``GB``, never ``UK``.
    country: str = Field(pattern=r"^[A-Z]{2}$")
    #: ``serious`` / ``other`` — the quality filter a statistic can state in one clause.
    #: See :class:`~newsab_schema.enums.SourceCategory` for where the line falls.
    category: SourceCategory
    #: General-interest newsroom or industry/sector desk.  Orthogonal
    #: to ``category``, which is about register: SMM, Katadata, detikFinance, IHE and the
    #: Chronicle are all `vertical` yet fall on both sides of the serious/other line, so a
    #: balance check that reads only `category` misses the worst composition bias in the
    #: sample — a side whose coverage is entirely trade press is a different sample from
    #: one whose coverage is entirely general news, however "serious" both are.
    #: `general` is the default because it is the overwhelmingly common case; a collector
    #: who leaves it unset on a trade outlet has mislabelled it, not accepted a default.
    beat_scope: Literal["general", "vertical"] = "general"
    #: The media card a reader opens from any outlet name on the page (C10): **one
    #: sentence, in English, written for that reader** (other locales are the localization
    #: pass's job, same as ``name``).  It says what kind of institution this is — who runs
    #: it, what it covers, what a reader should discount — which is also what makes
    #: ``category`` checkable by the next agent.  Nothing addressed to an agent belongs
    #: here: fetch mechanics go to ``channel.fetch_notes``, and a topic's sampling debt
    #: goes to that topic's ``collection_log``.
    notes: MultiLangText
    channel: SourceChannel = Field(default_factory=SourceChannel)

    @field_validator("lang")
    @classmethod
    def _lang(cls, v: str) -> str:
        return normalize_lang(v)

    @model_validator(mode="after")
    def _reader_facing(self) -> "SourceEntry":
        for field in ("name", "notes"):
            if not getattr(self, field).values.get("en"):
                raise ValueError(f"{self.id}: {field} is missing en")
        if any(text == self.id for text in self.name.values.values()):
            raise ValueError(
                f"{self.id}: name still carries the source_id as a masthead; register the "
                "outlet's real name in English"
            )
        for lang, limit in _NOTES_CHAR_LIMITS.items():
            text = self.notes.values.get(lang)
            if text is None:
                continue
            if len(text) > limit:
                raise ValueError(
                    f"{self.id}: notes[{lang}] is {len(text)} characters; the media card "
                    f"holds about {limit}. It is one sentence for a reader, not a dossier "
                    "— fetch mechanics belong in channel.fetch_notes and a topic's "
                    "sampling debt in that topic's collection_log"
                )
        return self


class SourceRegistry(Record):
    """The cross-topic outlet registry (R-3).

    **Not** a frozen artifact and **not** a gate.  Three things used to live in one
    per-topic ``sources_snapshot.yaml``: the collection playbook, the source
    classification, and "which sources this version actually covered".  Only the third is
    a claim about a piece of published analysis, and it is a fact *derived* from a corpus
    run (:class:`CorpusRun.source_ids`), not a list approved in advance.  The first two are
    knowledge that only ever grows, so this file is append-only, unhashed, and read — never
    approved — by S2.

    G1 therefore approves topic scope and risk (§3.3 S0), not a sampling frame; a page
    shows the sources the published run actually covered, which is both more honest and
    harder to argue with than a list of intentions.
    """

    registry_version: str = Field(min_length=1)
    updated_at: datetime
    sources: list[SourceEntry] = Field(default_factory=list)

    @field_validator("updated_at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _unique(self) -> "SourceRegistry":
        ids = [s.id for s in self.sources]
        if len(set(ids)) != len(ids):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate source ids in registry: {dupes}")
        return self

    def by_id(self, source_id: str) -> SourceEntry:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise KeyError(f"no source {source_id!r} in sources/registry.yaml")

    def get(self, source_id: str) -> Optional[SourceEntry]:
        return next((s for s in self.sources if s.id == source_id), None)

    def with_source(self, entry: SourceEntry) -> "SourceRegistry":
        """A copy carrying one more outlet.  Records are immutable (§3.2); the *file* is
        append-only, which is a different and weaker promise on purpose."""
        if self.get(entry.id) is not None:
            raise ValueError(f"source {entry.id!r} is already registered")
        return self.model_copy(
            update={
                "sources": sorted([*self.sources, entry], key=lambda s: s.id),
                "updated_at": datetime.now(timezone.utc),
            }
        )


# --------------------------------------------------------------------------------------
# S2 — article + structured text
# --------------------------------------------------------------------------------------


class Sentence(Record):
    """One sentence with its 1-based index inside its paragraph."""

    index: int = Field(ge=1)
    text: str = Field(min_length=1)


class Paragraph(Record):
    """A paragraph. Index 0 is the synthetic headline block: S01 = title, S02 = subtitle
    (§4.1).  Body paragraphs start at 1."""

    index: int = Field(ge=0)
    sentences: list[Sentence] = Field(min_length=1)

    @model_validator(mode="after")
    def _contiguous(self) -> "Paragraph":
        expected = list(range(1, len(self.sentences) + 1))
        actual = [s.index for s in self.sentences]
        if actual != expected:
            raise ValueError(
                f"paragraph {self.index}: sentence indices must be 1..n contiguous, got {actual}"
            )
        return self


class LocalEdits(Record):
    """What a syndicating outlet changed — the part of wire reuse that is still an
    editorial choice, and therefore still analysable at publication-instance level."""

    headline_changed: bool
    lead_changed: bool


class Origin(Record):
    """Reporting-origin classification (§3.3 S2).  This is what turns publication
    instances into the independent reporting clusters D7 makes the denominator."""

    type: OriginType
    wire_source: Optional[str] = None
    local_edits: Optional[LocalEdits] = None

    @model_validator(mode="after")
    def _wire_source_present(self) -> "Origin":
        needs_source = {
            OriginType.DOMESTIC_WIRE,
            OriginType.FOREIGN_WIRE_REWRITE,
            OriginType.SYNDICATION,
            # For a press release the "source" is the body that issued the statement
            # (a ministry, regulator, association, company).  Naming it is the whole
            # point of the classification: unattributed, it is indistinguishable from
            # wire copy in the corpus.
            OriginType.PRESS_RELEASE,
        }
        if self.type in needs_source and not self.wire_source:
            raise ValueError(f"origin.type={self.type.value} requires wire_source")
        if self.type == OriginType.ORIGINAL and self.wire_source:
            raise ValueError("origin.type=original must not carry a wire_source")
        return self


class Article(Record):
    """One publication instance, sentence-segmented and permanently numbered.

    Full text lives here and **never ships publicly** (D14): the publishable artifacts
    carry only URL + the exact quoted sentence.  ``sentence_text`` is what makes S8's
    character-exact quote check possible without republishing anything.
    """

    article_id: str
    topic_id: str
    source_id: str
    url: str = Field(pattern=r"^https?://")
    title: str = Field(min_length=1)
    publish_date: date
    lang: str
    structured_text: list[Paragraph] = Field(min_length=1)
    fetch_timestamp: datetime
    access_level: AccessLevel
    origin: Origin
    reporting_cluster_id: str
    #: §4.1: the splitter version goes in the manifest so the same version reproduces the
    #: same segmentation, and therefore the same sentence IDs.
    splitter_version: str = Field(min_length=1)
    provenance: Provenance

    @field_validator("article_id")
    @classmethod
    def _article(cls, v: str) -> str:
        return validate_article_id(v)

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @field_validator("lang")
    @classmethod
    def _lang(cls, v: str) -> str:
        return normalize_lang(v)

    @field_validator("reporting_cluster_id")
    @classmethod
    def _cluster(cls, v: str) -> str:
        if not CLUSTER_ID_RE.match(v):
            raise ValueError(f"not a reporting_cluster_id: {v!r} (expected RC-{{GROUP}}-{{nnn}})")
        return v

    @field_validator("fetch_timestamp")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _structure(self) -> "Article":
        indices = [p.index for p in self.structured_text]
        expected_indices = list(range(len(self.structured_text)))
        if indices != expected_indices:
            raise ValueError(
                "paragraph indices must be contiguous from 0 (the headline block); "
                f"expected {expected_indices}, got {indices}"
            )
        head = self.structured_text[0]
        if head.sentences[0].text != self.title:
            raise ValueError(
                "P00:S01 must be exactly the article title (§4.1); "
                f"got {head.sentences[0].text!r} vs title {self.title!r}"
            )
        prefix = self.article_id.split("_")[0]
        if not GROUP_RE.match(prefix):
            raise ValueError(f"article_id prefix {prefix!r} is not a group prefix")
        cluster_group = self.reporting_cluster_id.split("-")[1]
        if cluster_group != prefix:
            raise ValueError(
                f"reporting_cluster_id group {cluster_group!r} does not match "
                f"article_id group {prefix!r}"
            )
        if self.access_level == AccessLevel.BLOCKED:
            raise ValueError(
                "a blocked source cannot yield an article record; record the failure in the "
                "collection log instead (§3.3 S2: '失败如实记录')"
            )
        return self

    # -- sentence access ---------------------------------------------------------------

    def sentence_ids(self) -> list[str]:
        return [
            make_sentence_id(self.article_id, p.index, s.index)
            for p in self.structured_text
            for s in p.sentences
        ]

    def sentence_text(self, sentence_id: str) -> str:
        """Verbatim text of one sentence — the reference side of S8's quote check."""
        from ..ids import SentenceId

        sid = SentenceId.parse(sentence_id)
        if sid.article_id != self.article_id:
            raise KeyError(f"{sentence_id} does not belong to {self.article_id}")
        for p in self.structured_text:
            if p.index == sid.paragraph:
                for s in p.sentences:
                    if s.index == sid.sentence:
                        return s.text
        raise KeyError(f"{sentence_id} does not exist in {self.article_id}")

    def has_sentence(self, sentence_id: str) -> bool:
        try:
            self.sentence_text(sentence_id)
        except (KeyError, ValueError):
            return False
        return True

    @property
    def is_independent(self) -> bool:
        """Whether this instance counts as independent information production (D7)."""
        return self.origin.type == OriginType.ORIGINAL


# --------------------------------------------------------------------------------------
# S2 — the corpus run: the set of content one analysis saw (R-2)
# --------------------------------------------------------------------------------------


class RunArticle(Record):
    """One article as a *member of a run*: identity, content fingerprint, cluster."""

    article_id: str
    source_id: str
    #: ``sha256:`` of the article's semantic payload — everything an anchor or a count can
    #: depend on, with ``fetch_timestamp``, ``provenance`` and the per-run cluster excluded.
    #: This is what makes "the same set" checkable without keeping a copy of the text.
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    #: Assigned by *this* run.  Clustering is a property of the set, not of the article:
    #: adding one piece of wire copy can merge two clusters, so the assignment cannot live
    #: on the immutable article record.
    reporting_cluster_id: str
    #: The collector's topic-centrality judgement, carried from staging.  It lives
    #: on the run for the same reason the cluster does: it is a reading of *this* topic's
    #: scope, it can be refined when the scope is, and putting it on the immutable article
    #: would change every stored content hash and make earlier runs unrestorable.
    #: `core` is the default everywhere, so a run built before this field counts exactly as it
    #: did — the label can only ever *remove* a cluster from a denominator, never add one.
    topic_relevance: Literal["core", "peripheral"] = "core"

    @field_validator("article_id")
    @classmethod
    def _article(cls, v: str) -> str:
        return validate_article_id(v)

    @field_validator("reporting_cluster_id")
    @classmethod
    def _cluster(cls, v: str) -> str:
        if not CLUSTER_ID_RE.match(v):
            raise ValueError(f"not a reporting_cluster_id: {v!r} (expected RC-{{GROUP}}-{{key}})")
        return v


class WithdrawnArticle(Record):
    """An article held in the store but excluded from this run, and why (R-2).

    Deleting the file would make every earlier run unrestorable, so withdrawal is a
    statement about *this* set.  Reasons are the honest ones: wrong origin attribution,
    out of period, duplicate carrier page.  A withdrawal is never silent — it appears here
    and in the collection log.
    """

    article_id: str
    reason: str = Field(min_length=1)
    at: datetime

    @field_validator("at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)


#: How many targeted retry rounds a debt is owed before its budget counts as spent.
#: Collect's Done gate retries only the debt cells, at most this many rounds;
#: annotate's preflight refuses a corpus while any debt still has budget remaining.
BACKFILL_RETRY_BUDGET = 2


class BackfillDebt(Record):
    """A cell of the §2.3 search matrix this run did not manage to cover (R-3).

    An unsearched cell is a known limit of one run, and the page reads prevalence off the
    covered subset with this listed beside it.  What is forbidden is reading an unsearched
    cell as silence (D5).  A debt is a ledger entry, not a note: the build rolls
    every unclosed debt forward onto the next run, and annotate refuses the corpus until
    each entry is either closed or has :attr:`budget_exhausted` — at which point the
    residue rides the run report to touchpoint two.
    """

    source_id: str
    #: Which cell: term variant, period, or however the topic's matrix is cut.
    cell: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    #: Targeted retry rounds already spent on this cell (``--retry-debt`` at build time).
    retries: int = Field(default=0, ge=0)
    #: The miss is a class no retry can change — a subscription wall that survived both
    #: fetch layers, a channel that does not exist.  Counts as budget spent immediately;
    #: the ``fetch_failure`` already in the collection log is the evidence.
    retry_futile: bool = False

    @property
    def key(self) -> str:
        """``source:cell`` — how build flags address one debt across runs."""
        return f"{self.source_id}:{self.cell}"

    @property
    def budget_exhausted(self) -> bool:
        return self.retry_futile or self.retries >= BACKFILL_RETRY_BUDGET


class CorpusRun(Record):
    """One S2 build: **the set of content this analysis saw** (R-2).

    §3.2's "records are immutable" is implemented here as *the set a run referenced is
    immutable*, not as *the files on disk may never change*.  The article store
    (``corpus/articles/``) only ever grows; a run pins which members it saw and what each
    contained.  Adding an article therefore means: write one file, annotate that one file,
    re-run the deterministic layers, mint a new run — every existing annotation stands.

    ``set_hash`` is the fingerprint of that set and is what a reviewer re-derives; the
    manifest stores it, and every published number pins the run that produced it.
    """

    run_id: str = Field(pattern=RUN_ID_RE.pattern)
    topic_id: str
    #: Members, sorted by ``article_id`` so the record is byte-stable.
    articles: list[RunArticle] = Field(default_factory=list)
    withdrawn: list[WithdrawnArticle] = Field(default_factory=list)
    #: ``sha256:`` over ``[[article_id, content_hash], ...]`` in ``article_id`` order.
    set_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    splitter_version: str = Field(min_length=1)
    cluster_threshold: float = Field(ge=0.0, le=1.0)
    cluster_shingle_n: int = Field(ge=1)
    #: Han script fold the cluster fingerprints ran under (e.g. ``t2s-cn-v1``); ``None``
    #: on runs from before the fold existed, whose clusters re-derive without folding.
    cluster_han_fold: Optional[str] = None
    backfill_debt: list[BackfillDebt] = Field(default_factory=list)
    #: Dual-unit statistics, cluster members and build warnings — everything §2.3 and D7
    #: need, computed over this set.
    build_report: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @model_validator(mode="after")
    def _consistent(self) -> "CorpusRun":
        ids = [a.article_id for a in self.articles]
        if ids != sorted(ids):
            raise ValueError("corpus run articles must be sorted by article_id")
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate article_id in corpus run")
        overlap = sorted({w.article_id for w in self.withdrawn} & set(ids))
        if overlap:
            raise ValueError(f"articles cannot be both a member and withdrawn: {overlap}")
        expected = compute_set_hash({a.article_id: a.content_hash for a in self.articles})
        if self.set_hash != expected:
            raise ValueError(
                f"set_hash does not match the declared members: {self.set_hash} != {expected}"
            )
        return self

    @property
    def article_ids(self) -> list[str]:
        return [a.article_id for a in self.articles]

    @property
    def retexted_anchors(self) -> list[str]:
        """Fully-qualified sentence IDs this build kept at the same address and rewrote.

        The build is the only place that ever sees both generations of an article, so it
        is the only place that can notice an anchor which still resolves and no longer
        means the same thing.  It records the delta here; ``validate_answers`` reads this
        and refuses any answer citing one.  Empty for every build that changed no text,
        which is the normal case.
        """
        delta = self.build_report.get("anchor_delta") or {}
        return sorted(
            f"{article_id}:{sentence_id}"
            for article_id, change in delta.items()
            for sentence_id in (change or {}).get("retexted", ())
        )

    @property
    def content_hashes(self) -> dict[str, str]:
        return {a.article_id: a.content_hash for a in self.articles}

    @property
    def cluster_assignment(self) -> dict[str, str]:
        return {a.article_id: a.reporting_cluster_id for a in self.articles}

    @property
    def cluster_relevance(self) -> dict[str, str]:
        """Per-cluster topic relevance: `core` if **any** member is core.

        Any rather than all, and deliberately: a cluster is one piece of reporting seen
        through several outlets.  If one member is a real report on this topic and another
        is a market wrap that reprinted a paragraph of it, the reporting exists — it would
        be the wrong kind of tidiness to drop it from the denominator because a peripheral
        outlet also carried it.
        """
        out: dict[str, str] = {}
        for article in self.articles:
            current = out.get(article.reporting_cluster_id)
            if current == "core":
                continue
            out[article.reporting_cluster_id] = article.topic_relevance
        return out

    @property
    def core_clusters(self) -> list[str]:
        """The denominator for every prevalence statement (D7)."""
        return sorted(c for c, rel in self.cluster_relevance.items() if rel == "core")

    @property
    def peripheral_clusters(self) -> list[str]:
        """Excluded from statistics, still in the corpus and still quotable."""
        return sorted(c for c, rel in self.cluster_relevance.items() if rel != "core")

    @property
    def source_ids(self) -> list[str]:
        """The sources this version actually covered — derived, never approved up front."""
        return sorted({a.source_id for a in self.articles})


def compute_set_hash(content_hashes: "dict[str, str]") -> str:
    """The fingerprint of a content set: ``sha256`` over sorted ``[id, hash]`` pairs."""
    from .manifest import content_digest

    return content_digest([[k, content_hashes[k]] for k in sorted(content_hashes)])


def article_sentence_hash(article: "Article") -> str:
    """Fingerprint only what a sentence anchor can point at.

    ``article_content_hash`` answers "did this record change"; this answers the different
    and narrower question "did any anchor into this article move".  They came apart the
    first time a mechanism-only change shipped: a ``splitter_version`` bump, an ``origin``
    relabel or a corrected ``access_level`` all change the record while leaving every
    ``{article_id}:P{n}:S{n}`` resolving to byte-identical text.  Driving the
    "re-annotate this" signal off the content hash therefore reported 100% of a corpus as
    stale after a version bump that moved nothing, which turns every incremental rebuild
    into a full re-annotation — the exact cost the append-only store exists to avoid.

    The identity that runs pin stays ``article_content_hash``: restoring the exact bytes a
    run saw must stay sensitive to every field.  This hash is for the staleness question
    only.
    """
    from .manifest import content_digest

    return content_digest(
        [
            [f"P{paragraph.index:02d}:S{sentence.index:02d}", sentence.text]
            for paragraph in article.structured_text
            for sentence in paragraph.sentences
        ]
    )


def article_content_hash(article: "Article") -> str:
    """Fingerprint the part of an article a downstream anchor or count can depend on.

    ``fetch_timestamp`` and ``provenance`` are when and by what the record was made, and
    ``reporting_cluster_id`` belongs to a run rather than to the article — none of the
    three changes what the article *says*, so none of them belongs in the hash that decides
    whether two runs saw the same content.
    """
    from .manifest import content_digest

    payload = article.model_dump(mode="json")
    for volatile in ("fetch_timestamp", "provenance", "reporting_cluster_id"):
        payload.pop(volatile, None)
    return content_digest(payload)
