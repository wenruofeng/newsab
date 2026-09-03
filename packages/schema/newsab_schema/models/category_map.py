"""The normalize-stage artifact: a versioned category merge map (analyze refactor D-c).

The annotate stage mints ``answer_category`` values freely — a genuinely new answer mints
a new category — so two annotation passes can spell one concept two ways and the split
vote decides every downstream statistic (stats audit P5).  The normalize stage (value
chain stage 3.5) is where an agent judges which categories are the same concept; ALL of
that judgement is frozen into this artifact, and the analyze stage applies it
deterministically.  That is how analyze keeps its "code only" identity (non-negotiable
4): every number is still recomputable from (answers, category_map, thresholds).

The map is **merge-only**: it may collapse categories into one canonical spelling, never
split one apart (a split would need re-annotation).  ``unclear`` never participates — it
is the reserved "addressed but unbucketable" outcome, not a concept.
"""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from ..common import LangText, Provenance, Record
from ..ids import parse_prefixed_id, validate_topic_id
from .qa import ANSWER_CATEGORY_UNCLEAR, validate_answer_category


class CategoryMerge(Record):
    """One merge group: every member category is counted as ``canonical``.

    ``rationale`` is one auditable sentence on why these are the same concept — it
    travels with the artifact so a reviewer can challenge the merge, not reconstruct it.
    """

    canonical: str
    members: list[str] = Field(min_length=1)
    rationale: LangText

    @field_validator("canonical")
    @classmethod
    def _canonical(cls, v: str) -> str:
        value = validate_answer_category(v)
        if value == ANSWER_CATEGORY_UNCLEAR:
            raise ValueError("'unclear' is not a concept and cannot be a canonical category")
        return value

    @field_validator("members")
    @classmethod
    def _members(cls, v: list[str]) -> list[str]:
        cleaned = [validate_answer_category(m) for m in v]
        if ANSWER_CATEGORY_UNCLEAR in cleaned:
            raise ValueError("'unclear' never participates in a merge")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError(f"duplicate members in merge: {cleaned}")
        return cleaned

    @model_validator(mode="after")
    def _not_a_noop(self) -> "CategoryMerge":
        if set(self.members) <= {self.canonical}:
            raise ValueError(
                f"merge into {self.canonical!r} renames nothing — a question with no "
                "merges is simply omitted from the map"
            )
        return self


class CategoryMap(Record):
    """One topic's category normalization, pinned to the answers run it was built on.

    Per question a list of merge groups; a question absent from ``merges`` maps every
    category to itself (the identity is the default, so an empty map is a valid map).
    Merge-only invariants, per question: no member appears in two groups, and no
    canonical is itself a member of another group — projection is a single lookup,
    never a chain.
    """

    topic_id: str
    question_set_version: str = Field(min_length=1)
    #: The answers run this map was built against.  Applying the map to a *newer*
    #: answers run is legitimate (new categories fall through as identity) but the
    #: analyze run records both ids so the pairing is auditable.
    answers_run_id: str = Field(min_length=1)
    #: ``question_id -> merge groups``.  Questions with nothing to merge are omitted.
    merges: dict[str, list[CategoryMerge]] = Field(default_factory=dict)
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @model_validator(mode="after")
    def _consistency(self) -> "CategoryMap":
        if self.provenance.model_id is None:
            raise ValueError(
                "a category map is an agent judgement — provenance must name model_id"
            )
        for question_id, groups in self.merges.items():
            parse_prefixed_id(question_id, "QST")
            if not groups:
                raise ValueError(
                    f"{question_id}: empty merge list — omit the question instead"
                )
            members_seen: set[str] = set()
            canonicals = {g.canonical for g in groups}
            if len(canonicals) != len(groups):
                raise ValueError(f"{question_id}: two merge groups share a canonical")
            for group in groups:
                for member in group.members:
                    if member in members_seen:
                        raise ValueError(
                            f"{question_id}: category {member!r} appears in two merge groups"
                        )
                    members_seen.add(member)
                    if member != group.canonical and member in canonicals:
                        raise ValueError(
                            f"{question_id}: {member!r} is both a member and a canonical "
                            "— merges must not chain"
                        )
        return self

    def project(self, question_id: str, category: str) -> str:
        """The canonical spelling of ``category`` for ``question_id`` (identity default)."""
        for group in self.merges.get(question_id, []):
            if category in group.members:
                return group.canonical
        return category
