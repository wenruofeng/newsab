"""S4 records: observation units, article-level annotations, concept ontology.

Blueprint §4.2 / §4.2.3 / §4.3.  These are the schemas the whole pipeline is built to
serve: an observation is the atom at which evidence is bound (§3.0 rule 4), and the
ontology is the join key A1 aggregates on (§4.3).

One deliberate omission: §3.3 S4 lists an article-level ``quoted_sources[]`` field, while
§4.2.3 — the actual schema section — does not.  We follow §4.2.3 and represent every
quoted voice as a ``dimension=quoted_voice`` observation, which is sentence-anchored.  A
second, unanchored copy of the same information would be free to drift from the first, and
A1 would have to choose between them.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import Field, field_validator, model_validator

from ..common import LangText, MultiLangText, Provenance, Record, normalize_lang
from ..enums import (
    ATTR_ENUMS,
    REQUIRED_ATTRS,
    Dimension,
    LanguageSignal,
    StancePolarity,
    coerce_valence,
)
from ..ids import (
    SentenceId,
    parse_prefixed_id,
    topic_slug_matches,
    validate_article_id,
    validate_concept_id,
    validate_topic_id,
)

# --------------------------------------------------------------------------------------
# §4.2 Observation
# --------------------------------------------------------------------------------------


class Observation(Record):
    """One local presentation act, in one article, on one dimension.

    Small and many, never a whole-article summary (§4.2): an article dense with framing
    yields 10–30 of these.  Everything a reader eventually sees is aggregated from here,
    which is why ``evidence`` is required at construction — there is no code path that
    creates an observation and attaches evidence later (§3.0 rule 4).
    """

    observation_id: str
    topic_id: str
    article_id: str
    dimension: Dimension
    #: Short English phrase naming what is being observed — English so that the two sides'
    #: observations can be laid side by side before the ontology merges anything.
    subject: str = Field(min_length=1, max_length=120)
    #: The issue-specific concept **as the article words it**, in the source language.
    #: Never rewritten; normalisation only adds a mapping (§4.2.2 invariant 3).
    concept_surface: str = Field(min_length=1)
    #: One sentence describing HOW the article presents it, in the article's language.
    #: Lint-enforced to be descriptive, not explanatory (§4.2.2 invariant 2).
    proposition: LangText
    attrs: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @field_validator("article_id")
    @classmethod
    def _article(cls, v: str) -> str:
        return validate_article_id(v)

    @field_validator("evidence")
    @classmethod
    def _evidence_grammar(cls, v: list[str]) -> list[str]:
        for sid in v:
            SentenceId.parse(sid)  # raises IdError on a malformed anchor
        if len(set(v)) != len(v):
            raise ValueError(f"duplicate sentence IDs in evidence: {v}")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> "Observation":
        parsed = parse_prefixed_id(self.observation_id, "OBS")
        if not topic_slug_matches(parsed.topic_slug, self.topic_id):
            raise ValueError(
                f"observation_id topic slug {parsed.topic_slug!r} does not match "
                f"topic_id {self.topic_id!r}"
            )
        # §4.2.2 invariant 1: all evidence belongs to this article.
        foreign = sorted({s for s in self.evidence if SentenceId.parse(s).article_id != self.article_id})
        if foreign:
            raise ValueError(
                f"evidence must all belong to {self.article_id}; foreign anchors: {foreign}"
            )
        _validate_attrs(self.dimension, self.attrs)
        return self

    @property
    def evidence_ids(self) -> list[SentenceId]:
        return sorted(SentenceId.parse(s) for s in self.evidence)


def _validate_attrs(dimension: Dimension, attrs: dict[str, Any]) -> None:
    """Enforce the §4.2.1 per-dimension ``attrs`` table.

    Missing keys fail.  Extra keys are allowed: the generic dimension track is fixed, but
    a topic may legitimately want one more descriptor on a specific observation, and
    forbidding that would push annotators into misusing ``concept_surface``.
    """
    required = REQUIRED_ATTRS[dimension]
    missing = [k for k in required if k not in attrs or attrs[k] in (None, "")]
    if missing:
        raise ValueError(
            f"dimension={dimension.value} requires attrs {list(required)}; missing {missing}"
        )
    for key in required:
        enum_cls = ATTR_ENUMS.get((dimension, key))
        if enum_cls is None:
            continue
        raw = attrs[key]
        try:
            if (dimension, key) == (Dimension.CONSEQUENCE, "valence"):
                coerce_valence(raw)
            else:
                enum_cls(raw)
        except ValueError as exc:
            raise ValueError(
                f"attrs.{key}={raw!r} is not a valid {enum_cls.__name__}: "
                f"{enum_cls.values()}"
            ) from exc


# --------------------------------------------------------------------------------------
# §4.2.3 Article annotation
# --------------------------------------------------------------------------------------


class OverallStance(Record):
    """Article-level stance toward a named target, always with a confidence.

    §2.2's C6 also mentions a sentiment axis, which §4.2.3 no longer carries.  We follow
    §4.2.3; if sentiment comes back it is an additive field
    here, not a change to anything already stored.
    """

    target: str = Field(min_length=1)
    polarity: StancePolarity
    confidence: float = Field(ge=0.0, le=1.0)


class NotableLanguage(Record):
    """A wording signal, anchored to the sentence it occurs in."""

    phrase: str = Field(min_length=1)
    sentence: str
    signal: LanguageSignal

    @field_validator("sentence")
    @classmethod
    def _sentence(cls, v: str) -> str:
        SentenceId.parse(v)
        return v


class ArticleAnnotation(Record):
    """The light per-article record that runs alongside the observations (§4.2.3)."""

    article_id: str
    topic_id: str
    overall_stance: Optional[OverallStance] = None
    notable_language: list[NotableLanguage] = Field(default_factory=list)
    provenance: Provenance

    @field_validator("article_id")
    @classmethod
    def _article(cls, v: str) -> str:
        return validate_article_id(v)

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @model_validator(mode="after")
    def _anchors(self) -> "ArticleAnnotation":
        foreign = sorted(
            {
                n.sentence
                for n in self.notable_language
                if SentenceId.parse(n.sentence).article_id != self.article_id
            }
        )
        if foreign:
            raise ValueError(
                f"notable_language anchors must belong to {self.article_id}; got {foreign}"
            )
        return self


# --------------------------------------------------------------------------------------
# §4.3 Concept ontology
# --------------------------------------------------------------------------------------


class ConceptSurface(Record):
    """An original wording that was merged into a canonical concept.

    ``example_obs`` keeps the merge auditable: a reviewer can open the observation the
    surface came from and judge whether the merge was fair.
    """

    text: str = Field(min_length=1)
    lang: str
    example_obs: str

    @field_validator("lang")
    @classmethod
    def _lang(cls, v: str) -> str:
        return normalize_lang(v)

    @field_validator("example_obs")
    @classmethod
    def _obs(cls, v: str) -> str:
        parse_prefixed_id(v, "OBS")
        return v

    @property
    def key(self) -> tuple[str, str]:
        return (self.text, self.lang)


class MergedBy(Record):
    """Provenance of one merge decision.

    ``run_id``/``skill_version`` identify the run that *produced* this record — an
    incremental re-normalisation restamps them even for concepts it carried forward
    unchanged. ``first_run_id`` is the run in which the merge was first *decided*;
    ``None`` means "this run" (the concept is new). Without it, "this merge decision
    is from an earlier round" is lost on every re-run (non-negotiable 9).
    """

    skill_version: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    first_run_id: Optional[str] = None

    @property
    def decided_run_id(self) -> str:
        return self.first_run_id or self.run_id


class Concept(Record):
    """One canonical concept and every surface form merged into it (§4.3)."""

    concept_id: str
    label: MultiLangText
    surfaces: list[ConceptSurface] = Field(min_length=1)
    merged_by: MergedBy

    @field_validator("concept_id")
    @classmethod
    def _cid(cls, v: str) -> str:
        return validate_concept_id(v)

    @model_validator(mode="after")
    def _unique_surfaces(self) -> "Concept":
        keys = [s.key for s in self.surfaces]
        if len(set(keys)) != len(keys):
            dupes = sorted({k for k in keys if keys.count(k) > 1})
            raise ValueError(f"duplicate surfaces inside {self.concept_id}: {dupes}")
        return self


class ConceptOntology(Record):
    """The versioned surface -> concept map for one topic.

    A1 joins on ``ontology_version`` (§4.3): re-merging concepts produces a new ontology
    version and therefore a new feature matrix, rather than silently changing yesterday's
    numbers.
    """

    topic_id: str
    ontology_version: str = Field(min_length=1)
    concepts: list[Concept] = Field(default_factory=list)
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @model_validator(mode="after")
    def _one_concept_per_surface(self) -> "ConceptOntology":
        """§4.3 invariant: every surface maps to exactly one concept."""
        owner: dict[tuple[str, str], str] = {}
        collisions: list[str] = []
        for concept in self.concepts:
            for surface in concept.surfaces:
                previous = owner.get(surface.key)
                if previous is not None and previous != concept.concept_id:
                    collisions.append(
                        f"{surface.text!r}({surface.lang}) -> {previous} and {concept.concept_id}"
                    )
                owner[surface.key] = concept.concept_id
        if collisions:
            raise ValueError("surface mapped to more than one concept: " + "; ".join(collisions))
        ids = [c.concept_id for c in self.concepts]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate concept_id: {sorted({i for i in ids if ids.count(i) > 1})}")
        return self

    def lookup(self, surface: str, lang: str) -> Optional[str]:
        """The canonical ``concept_id`` for a raw surface form, or ``None`` if unmapped."""
        key = (surface, normalize_lang(lang))
        for concept in self.concepts:
            if any(s.key == key for s in concept.surfaces):
                return concept.concept_id
        return None

    def surface_map(self) -> dict[tuple[str, str], str]:
        return {s.key: c.concept_id for c in self.concepts for s in c.surfaces}
