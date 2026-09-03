"""Controlled vocabularies — THE single definition site.

Blueprint §4.1 locks four vocabularies as "additive only, meaning never changes":
``dimension``, ``speaker_category``, ``angle_type``, ``claim_type``.  Those four MUST NOT
be redefined anywhere else in the repo (no duplicated list in a skill's markdown, no
hard-coded string set in A1, no enum in the future frontend).  Everything downstream
either imports from here or reads ``packages/schema/dist/enums.json``, which is generated
from this module by ``newsab_schema.export``.

The remaining vocabularies are v0.1 working vocabularies for schemas the blueprint marks
as still-draft (§4.6); they live here for the same single-definition reason, but they are
allowed to change while those schemas are draft.  ``LOCKED`` records the distinction.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Python 3.10 has no ``enum.StrEnum``; this is the same behaviour we need."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


# --------------------------------------------------------------------------------------
# Locked vocabularies (blueprint §4.1) — additive only, meaning frozen.
# --------------------------------------------------------------------------------------


class Dimension(StrEnum):
    """Generic framing-analysis coding dimensions (S3 layer 1 / S4 track 1)."""

    PROBLEM_DEFINITION = "problem_definition"
    RESPONSIBILITY = "responsibility"
    CONSEQUENCE = "consequence"
    STANCE = "stance"
    PROPOSED_RESPONSE = "proposed_response"
    ACTOR_ROLE = "actor_role"
    QUOTED_VOICE = "quoted_voice"
    TERMINOLOGY = "terminology"
    FACTUAL_CLAIM = "factual_claim"


class SpeakerCategory(StrEnum):
    """Identity of a quoted voice (§4.1). Feeds C7 "who speaks for whom"."""

    GOVERNMENT_OFFICIAL = "government_official"
    COMPANY_INDUSTRY = "company_industry"
    EXPERT_ACADEMIC = "expert_academic"
    CITIZEN_WORKER = "citizen_worker"
    NGO_CIVIL_SOCIETY = "ngo_civil_society"
    FOREIGN_GOVERNMENT = "foreign_government"
    OTHER_MEDIA = "other_media"
    ANONYMOUS = "anonymous"
    OTHER = "other"


class AngleType(StrEnum):
    """The §3.3 A1 angle types, plus the special-cased blind spot (§4.1).

    These are **labels**, not scan domains (R-3): every bare/attr feature is
    scanned identically, the structural types describe what a feature compares, and
    ``shared_ground`` / ``co_silence`` name interval *readings* (consensus, joint silence)
    rather than shapes.  ``co_silence`` is an additive extension of the locked vocabulary:
    both sides leaving a controlled-vocabulary cell empty is data, not a gap (D5)."""

    SALIENCE = "salience"
    PROBLEM_DEFINITION = "problem_definition"
    CONSEQUENCE = "consequence"
    VOICE_STRUCTURE = "voice_structure"
    ACTOR_ROLE = "actor_role"
    STANCE = "stance"
    TERMINOLOGY = "terminology"
    SHARED_GROUND = "shared_ground"
    CO_SILENCE = "co_silence"
    BLIND_SPOT = "blind_spot"


class ClaimType(StrEnum):
    """Three provenance paths, kept visually distinct on the page (§3.2, §4.5).

    ``corpus_reading`` exists because the page must answer *what* the two sides say and
    not only *how often* they say it.  That answer is read out of the source text; no A1
    metric measures it.  Giving
    it its own type is how the cost stays visible: it may carry no ``computed_from`` and no
    quantifier, so it can never be mistaken on the page — or by a checker — for a number.
    """

    SOURCE_CLAIM = "source_claim"
    CORPUS_AGGREGATE = "corpus_aggregate"
    CORPUS_READING = "corpus_reading"


# --------------------------------------------------------------------------------------
# v0.1 working vocabularies (schemas still marked draft in blueprint §4.6).
# --------------------------------------------------------------------------------------


class Valence(StrEnum):
    """§4.2.1 writes ``pos|neg|mixed``; §4.2's worked example writes ``negative``.

    We take the spelled-out form as canonical and accept the abbreviations as input
    aliases (see :func:`coerce_valence`), so neither reading of the blueprint breaks.
    """

    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"


class CreditBlame(StrEnum):
    """``responsibility.polarity`` (§4.2.1)."""

    CREDIT = "credit"
    BLAME = "blame"


class StancePolarity(StrEnum):
    """``stance.polarity`` (§4.2.1) and ``article_annotation.overall_stance`` (§4.2.3)."""

    SUPPORT = "support"
    OPPOSE = "oppose"
    NEUTRAL = "neutral"
    AMBIVALENT = "ambivalent"


class SourceCategory(StrEnum):
    """Two values, because the only cut this project has ever needed from them is
    "serious press only" versus "everything we collected".

    This was once a five-way institution taxonomy (`state`, `tabloid`,
    `public_broadcaster`, …).  It described media systems more finely than any consumer
    used: nothing branches on `state` versus `serious`, and an ownership taxonomy invites
    the reader to hear a verdict where the project only ever recorded a fact.  What a
    statistic genuinely needs is a quality filter it can state in one clause.

    ``serious`` — a newsroom that reports under its own byline and answers for the facts:
    wires, national and metropolitan dailies, public broadcasters, party organs, staffed
    business newsrooms.  Ownership is *not* the test; the register of the work is.
    ``other`` — everything else we still collect and still count in the "all sources"
    view: tabloids, special-interest and history/science magazines, trade information
    services, aggregating portals, promotional local listings.

    Which one an outlet is must be legible from its ``notes``, which is why that field
    names the institution rather than praising it.
    """

    SERIOUS = "serious"
    OTHER = "other"


class AccessLevel(StrEnum):
    """How much of a source is lawfully retrievable (§1.5). ``partial`` = title+lead only."""

    FULL = "full"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class OriginType(StrEnum):
    """Reporting-origin classification produced by S2 (§3.3 S2). Drives D7's denominator.

    ``press_release`` is a written statement issued by a ministry, regulator,
    industry association or company that several outlets then rewrote.  It looks like wire
    homogeneity in the text-similarity matrix and it is not: a wire agency is a newsroom
    that reported, a press release is an interested party that published, and "six outlets
    carried the association's statement" means something different to a reader than "six
    outlets carried Xinhua's story".  The issuer goes in ``wire_source``.
    """

    ORIGINAL = "original"
    DOMESTIC_WIRE = "domestic_wire"
    FOREIGN_WIRE_REWRITE = "foreign_wire_rewrite"
    SYNDICATION = "syndication"
    PRESS_RELEASE = "press_release"


class TensionType(StrEnum):
    """Angle-card tension marker (§2.4): collision / blind spot / consensus."""

    COLLISION = "collision"
    BLIND_SPOT = "blind_spot"
    CONSENSUS = "consensus"


class IntervalReading(StrEnum):
    """The five readings of a signed-difference interval (R-2.2).

    ``insufficient`` is a first-class outcome: "the sample cannot tell" is a different
    statement from "we checked and there is no difference", and an earlier gate
    silently conflated them.  An interval merely covering zero is evidence of nothing
    (G-5); ``consensus`` and ``co_silence`` require the whole interval inside an
    equivalence band, with different bands because Var ∝ p(1−p)."""

    DIVERGENCE = "divergence"
    SMALL_STABLE_DIFFERENCE = "small_stable_difference"
    CONSENSUS = "consensus"
    CO_SILENCE = "co_silence"
    INSUFFICIENT = "insufficient"


class AngleOrigin(StrEnum):
    """D9: recorded for audit, and forbidden from entering any threshold branch."""

    PRIOR_HYPOTHESIS = "prior_hypothesis"
    DATA_DISCOVERED = "data_discovered"


class AngleStatus(StrEnum):
    """State machine from §4.4's ``selection.status`` comment."""

    PROPOSED = "proposed"
    R_REJECTED = "r_rejected"
    R_PASSED = "r_passed"
    MERGED = "merged"
    CLUSTERED = "clustered"
    E_REJECTED = "e_rejected"
    SHORTLISTED = "shortlisted"
    G2_APPROVED = "g2_approved"
    G2_REJECTED = "g2_rejected"


class HypothesisLayer(StrEnum):
    """S3 two-layer structure: fixed generic dimensions vs issue-specific hypotheses."""

    GENERIC = "generic"
    ISSUE_SPECIFIC = "issue_specific"


class QuestionTier(StrEnum):
    """The two tiers of the Q×A question set (value_chain.md, V-1).

    ``template`` questions are comparative-journalism standards asked of every topic;
    ``reader`` questions are topic-specific, generated from the scope brief and the
    corpus itself.  The tier is recorded for audit and cross-topic comparability — the
    annotation and analysis treatment of both tiers is identical (D9 carries over:
    a template question earns no lower evidence bar).
    """

    TEMPLATE = "template"
    READER = "reader"


class SeedQuestionMandate(StrEnum):
    """Touchpoint-one authority attached to an approved scope question.

    ``reference`` lets annotate use or discard the seed on semantic grounds.
    ``required`` compels annotate to include a semantically equivalent question, but gives
    that question no privilege in analysis or editorial selection.
    """

    REFERENCE = "reference"
    REQUIRED = "required"


class TemplateQuestionKey(StrEnum):
    """The standing template-tier questions (value_chain.md "The Q×A model").

    One member per standard: a topic's question set instantiates each key at most once,
    wording it for the topic.  This vocabulary absorbs the old S3 generic dimension
    layer — the old ``Dimension`` values map onto these keys where a mapping exists.
    Additive only: a new standard is a new member, never a re-reading of an old one.
    """

    PROBLEM_DEFINITION = "problem_definition"  # what is the problem
    RESPONSIBILITY = "responsibility"  # who or what is blamed / credited
    CONSEQUENCES = "consequences"  # what consequences are foreseen, for whom
    PROPOSED_RESPONSE = "proposed_response"  # what should be done
    QUOTED_VOICES = "quoted_voices"  # who gets quoted / who speaks
    LOADED_LANGUAGE = "loaded_language"  # what language is loaded


class FindingKind(StrEnum):
    """The shapes a Q×A finding can take (value_chain.md "The Q×A model").

    Since the analyze refactor the emitted kinds are ``consensus`` /
    ``divergence`` / ``attention_gap``, and a question emits at most one of them.  An
    attention gap (qa-0.4.0 semantics) asserts one side barely addresses the question
    (rate below the ``silent_max_rate`` threshold) while the other side addresses it
    substantially more — the blindspot-like reading; a mere rate difference between two
    sides that both plainly speak is not a finding.  It is first-class (it can carry an
    angle) and its angle always marks the quiet side; when the quiet side has zero
    addressed clusters the finding sets ``total_silence`` and is worded as
    annotation-layer silence.  ``blindspot`` and ``coverage_gap`` are no longer emitted
    but stay members — historical runs on disk reference them (append-only).
    """

    CONSENSUS = "consensus"
    DIVERGENCE = "divergence"
    ATTENTION_GAP = "attention_gap"
    BLINDSPOT = "blindspot"
    COVERAGE_GAP = "coverage_gap"


class FindingStrength(StrEnum):
    """The analyze stage's verdict on one finding at the current corpus size (V-3).

    Computed by plain Python against versioned thresholds; the writer cannot move it.
    ``unsupported`` findings may not be asserted in prose or charts.
    """

    SUPPORTED = "supported"
    WEAK = "weak"
    UNSUPPORTED = "unsupported"


class QuestionStatus(StrEnum):
    """Lifecycle of one question inside a versioned question set.

    ``retired`` keeps the question and its old answers restorable while excluding it
    from new annotation passes and from every denominator (append-only, never delete).
    """

    ACTIVE = "active"
    RETIRED = "retired"


class TopicStatus(StrEnum):
    """§1.4 topic lifecycle."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    ARCHIVED = "archived"


class PublicationEventType(StrEnum):
    """Append-only lifecycle transitions for an immutable publication record."""

    PUBLISH = "publish"
    SUPERSEDE = "supersede"
    WITHDRAW = "withdraw"
    RESTORE = "restore"
    AUDIT_DELETE = "audit_delete"


class RiskLevel(StrEnum):
    """S0 ``risk_level``; ``high`` forces the G3 human gate (§3.3 S8-L2)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LanguageSignal(StrEnum):
    """``article_annotation.notable_language[].signal`` (§4.2.3).

    Descriptive labels for *wording*, never verdicts about the underlying facts (D4).
    """

    HIGH_EMOTION = "high_emotion"
    EUPHEMISM = "euphemism"
    METAPHOR = "metaphor"
    EPITHET = "epithet"
    INTENSIFIER = "intensifier"
    HEDGE = "hedge"
    OFFICIAL_FORMULA = "official_formula"
    OTHER = "other"


class RecommendedVisual(StrEnum):
    """Controlled vocabulary mapped onto the §2.2 component list, so S6 cannot invent a
    chart the frontend does not have.  Each member names the component(s) it renders in."""

    PAIRED_RANKED_CONCEPTS = "paired_ranked_concepts"  # C4 expanded layer
    PREVALENCE_BARS = "prevalence_bars"  # C4 / C5
    SOURCE_CATEGORY_STACK = "source_category_stack"  # C5
    STANCE_DISTRIBUTION = "stance_distribution"  # C6
    VOICE_STRUCTURE_GRAPH = "voice_structure_graph"  # C7
    TERM_PAIR_CARDS = "term_pair_cards"  # C8
    DUAL_TIMELINE = "dual_timeline"  # C2
    HOMOGENEITY_CLUSTERS = "homogeneity_clusters"  # C3
    SHARED_GROUND_PANEL = "shared_ground_panel"  # C4, consensus angles
    SILENCE_PANEL = "silence_panel"  # C1 zeroth angle / blind spot


class LintVerdict(StrEnum):
    """Outcome of one mechanical lint (§3.3 S8-L0)."""

    PASS = "pass"
    FLAG = "flag"  # needs judge/human confirmation, does not auto-fail
    FAIL = "fail"


class Gate(StrEnum):
    """The three human gates (§3.4)."""

    G1 = "G1"
    G2 = "G2"
    G3 = "G3"


class GateDecider(StrEnum):
    """Who actually passed a gate.  ``llm_stand_in`` MUST be surfaced on the published
    record (AGENTS.md §8)."""

    HUMAN = "human"
    LLM_STAND_IN = "llm_stand_in"


#: Which vocabularies blueprint §4.1 freezes.  Consumed by tests and by the exporter.
LOCKED: dict[str, type[StrEnum]] = {
    "dimension": Dimension,
    "speaker_category": SpeakerCategory,
    "angle_type": AngleType,
    "claim_type": ClaimType,
}

#: Working vocabularies for still-draft schemas (§4.6).  Changeable while draft.
DRAFT: dict[str, type[StrEnum]] = {
    "valence": Valence,
    "credit_blame": CreditBlame,
    "stance_polarity": StancePolarity,
    "source_category": SourceCategory,
    "access_level": AccessLevel,
    "origin_type": OriginType,
    "tension_type": TensionType,
    "interval_reading": IntervalReading,
    "angle_origin": AngleOrigin,
    "angle_status": AngleStatus,
    "hypothesis_layer": HypothesisLayer,
    "question_tier": QuestionTier,
    "seed_question_mandate": SeedQuestionMandate,
    "template_question_key": TemplateQuestionKey,
    "question_status": QuestionStatus,
    "finding_kind": FindingKind,
    "finding_strength": FindingStrength,
    "topic_status": TopicStatus,
    "risk_level": RiskLevel,
    "language_signal": LanguageSignal,
    "recommended_visual": RecommendedVisual,
    "lint_verdict": LintVerdict,
    "gate": Gate,
    "gate_decider": GateDecider,
    "publication_event_type": PublicationEventType,
}

ALL: dict[str, type[StrEnum]] = {**LOCKED, **DRAFT}

_VALENCE_ALIASES = {"pos": Valence.POSITIVE, "neg": Valence.NEGATIVE}


def coerce_valence(raw: str) -> Valence:
    """Accept the §4.2.1 abbreviations (``pos``/``neg``) as input, emit canonical values."""
    key = str(raw).strip().lower()
    if key in _VALENCE_ALIASES:
        return _VALENCE_ALIASES[key]
    return Valence(key)


#: Which ``attrs`` keys each dimension requires (blueprint §4.2.1).  Single definition
#: site for the table; the observation model and the S4 self-check both read it.
REQUIRED_ATTRS: dict[Dimension, tuple[str, ...]] = {
    Dimension.PROBLEM_DEFINITION: (),
    Dimension.RESPONSIBILITY: ("actor", "polarity"),
    Dimension.CONSEQUENCE: ("affected_party", "valence"),
    Dimension.STANCE: ("target", "polarity"),
    Dimension.PROPOSED_RESPONSE: (),
    Dimension.ACTOR_ROLE: ("actor", "role_characterization"),
    Dimension.QUOTED_VOICE: ("speaker", "speaker_category"),
    Dimension.TERMINOLOGY: ("referent", "term_used"),
    Dimension.FACTUAL_CLAIM: ("claim_normalized",),
}

#: Which ``attrs`` values are themselves drawn from a controlled vocabulary.
ATTR_ENUMS: dict[tuple[Dimension, str], type[StrEnum]] = {
    (Dimension.RESPONSIBILITY, "polarity"): CreditBlame,
    (Dimension.CONSEQUENCE, "valence"): Valence,
    (Dimension.STANCE, "polarity"): StancePolarity,
    (Dimension.QUOTED_VOICE, "speaker_category"): SpeakerCategory,
}

#: Which dimension(s) each structural ``angle_type`` label describes (R-3: labels,
#: not scan domains — nothing branches on this to decide what gets computed).
#: ``shared_ground`` and ``co_silence`` are interval readings and can arise on any
#: dimension; ``blind_spot`` is deliberately absent: §3.3 S6 routes it through its own
#: four-condition check.
ANGLE_TYPE_DIMENSIONS: dict[AngleType, tuple[Dimension, ...]] = {
    AngleType.SALIENCE: tuple(Dimension),
    AngleType.PROBLEM_DEFINITION: (Dimension.PROBLEM_DEFINITION,),
    AngleType.CONSEQUENCE: (Dimension.CONSEQUENCE,),
    AngleType.VOICE_STRUCTURE: (Dimension.QUOTED_VOICE,),
    AngleType.ACTOR_ROLE: (Dimension.ACTOR_ROLE, Dimension.RESPONSIBILITY),
    AngleType.STANCE: (Dimension.STANCE,),
    AngleType.TERMINOLOGY: (Dimension.TERMINOLOGY,),
    AngleType.SHARED_GROUND: tuple(Dimension),
    AngleType.CO_SILENCE: tuple(Dimension),
}

#: E-score axes (§3.3 S6 as revised by R-7), scored 0–2 each against ``rubrics.md``.
#: Four axes, down from six: ``specificity`` was structurally guaranteed by
#: evidence-first + sentence anchors (double-charged), ``comprehensibility`` is a
#: property of the question's *wording* and fixable, so it is a lint rather than a
#: score, and ``visual_potential`` lives in ``recommended_visual``.  ``story_potential``
#: is new: can this angle join others in one coherent narrative — deliberately in
#: tension with ``non_redundancy``.  The E-score's uses are (i) the audit trail of the
#: subjective selection and (ii) R-6's calibration regression; nothing downstream
#: consumes it as a number.
E_SCORE_AXES: tuple[str, ...] = (
    "surprise",
    "relevance",
    "non_redundancy",
    "story_potential",
)

#: Human four-axis scoring used by the gold-standard set and the Phase 0 acceptance gate
#: (blueprint ⑤), scored 1–5 each.
HUMAN_SCORE_AXES: tuple[str, ...] = ("interesting", "clear", "defensible", "distinct")
