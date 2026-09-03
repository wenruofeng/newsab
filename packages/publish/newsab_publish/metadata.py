"""Versioned site metadata and the controlled topic taxonomy.

This is site-owned discovery metadata.  It does not change a topic's analysis and it is
kept separate from both topic artifacts and renderer-owned page strings.  Callers pass
the metadata path explicitly so a production build always pins the bytes it consumed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator

from newsab_schema import LangText, Record
from newsab_schema.common import normalize_lang
from newsab_schema.ids import validate_topic_id


CATEGORY_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

#: The English pivot the reader page is written in (`docs/value_chain.md`).  Every
#: language the site ships is a localization of it, so it is the one locale that is
#: always available and never has to be produced separately.
PIVOT_LOCALE = "en"


class SiteCategory(Record):
    """One category in taxonomy display order."""

    category_id: str = Field(pattern=CATEGORY_ID_PATTERN)
    labels: dict[str, str] = Field(min_length=1)

    @field_validator("labels")
    @classmethod
    def _labels(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for locale, label in value.items():
            canonical_locale = normalize_lang(locale)
            text = label.strip()
            if not text:
                raise ValueError(f"blank category label for {canonical_locale}")
            if canonical_locale in normalized:
                raise ValueError(f"duplicate category label locale: {canonical_locale}")
            normalized[canonical_locale] = text
        return normalized


class TaxonomyBackfillApproval(Record):
    """Founder-visible approval for the one-time legacy topic migration."""

    approval_id: str = Field(pattern=r"^taxonomy-backfill-\d{4}-\d{2}-\d{2}$")
    reviewer_id: str = Field(min_length=1)
    decision: Literal["approved"]
    decided_at: datetime
    topic_ids: list[str] = Field(min_length=1)
    note: LangText

    @field_validator("decided_at")
    @classmethod
    def _decided_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("taxonomy backfill decision time must carry a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("topic_ids")
    @classmethod
    def _topic_ids(cls, value: list[str]) -> list[str]:
        for topic_id in value:
            validate_topic_id(topic_id)
        if len(value) != len(set(value)):
            raise ValueError("taxonomy backfill topic ids must not contain duplicates")
        return value



def _metadata_revision(version: str) -> tuple[int, int, int]:
    """``site-metadata-1.2.3`` -> ``(1, 2, 3)``, for rules that start at a revision."""
    major, minor, patch = version.rsplit("-", 1)[-1].split(".")
    return int(major), int(minor), int(patch)


class TopicCategoryApproval(Record):
    """Founder approval for one topic's categories, decided after the legacy backfill.

    ``TaxonomyBackfillApproval`` covers exactly the topics that existed at the one-time
    migration and cannot grow without rewriting what that sitting decided.  Every topic
    published since needs its own record, or ``topic_categories`` becomes a field an agent
    can extend on its own judgement — and the category a reader filters the home page by
    is a published fact, not a derived one.
    """

    approval_id: str = Field(pattern=r"^taxonomy-topic-[a-z0-9]+(?:-[a-z0-9]+)*-\d{4}-\d{2}-\d{2}$")
    topic_id: str
    reviewer_id: str = Field(min_length=1)
    decision: Literal["approved"]
    decided_at: datetime
    category_ids: list[str] = Field(min_length=1)
    note: LangText

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, value: str) -> str:
        return validate_topic_id(value)

    @field_validator("decided_at")
    @classmethod
    def _decided_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("topic category decision time must carry a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("category_ids")
    @classmethod
    def _categories(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("topic category approval must not repeat a category id")
        return value


class SiteMetadata(Record):
    """One immutable revision of site-owned discovery metadata."""

    metadata_version: str = Field(pattern=r"^site-metadata-\d+\.\d+\.\d+$")
    taxonomy_version: str = Field(pattern=r"^taxonomy-\d+\.\d+\.\d+$")
    #: Every language this site ships.  One file names the full localization set; a
    #: publication localizes into all of it, and adding a language here is what makes
    #: the next publish (and a backfill of the live ones) produce it.
    locales: list[str] = Field(min_length=1)
    categories: list[SiteCategory] = Field(min_length=1)
    topic_categories: dict[str, list[str]] = Field(default_factory=dict)
    taxonomy_backfill_approval: Optional[TaxonomyBackfillApproval] = None
    topic_category_approvals: list[TopicCategoryApproval] = Field(default_factory=list)

    @field_validator("locales")
    @classmethod
    def _locales(cls, value: list[str]) -> list[str]:
        normalized = [normalize_lang(locale) for locale in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("site locales must not contain duplicates")
        if PIVOT_LOCALE not in normalized:
            raise ValueError(
                f"site locales must contain the {PIVOT_LOCALE!r} pivot: every other "
                "language is a localization of it"
            )
        return normalized

    @field_validator("topic_categories")
    @classmethod
    def _topic_ids(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        for topic_id, category_ids in value.items():
            validate_topic_id(topic_id)
            if not category_ids:
                raise ValueError(f"{topic_id}: at least one category is required")
            if len(category_ids) != len(set(category_ids)):
                raise ValueError(f"{topic_id}: duplicate category ids")
        return value

    @model_validator(mode="after")
    def _controlled_taxonomy(self) -> "SiteMetadata":
        category_ids = [category.category_id for category in self.categories]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("taxonomy category ids must be unique")

        required_locales = set(self.locales)
        for category in self.categories:
            # A category may carry labels beyond ``self.locales`` (the halo's other
            # seven, pre-loaded ahead of ``SITE_LOCALES``/``locales`` growing to include
            # them) — only missing coverage of the *live* locales is refused, the same
            # "cover, not match exactly" relaxation made for ``ThemeDefinition.labels``.
            missing = sorted(required_locales - set(category.labels))
            if missing:
                raise ValueError(
                    f"{category.category_id}: category labels must match site locales "
                    f"(missing={missing})"
                )

        controlled = set(category_ids)
        for topic_id, assigned in self.topic_categories.items():
            unknown = sorted(set(assigned) - controlled)
            if unknown:
                raise ValueError(f"{topic_id}: unknown category ids: {unknown}")
        if self.taxonomy_backfill_approval is not None:
            missing_topics = sorted(
                set(self.taxonomy_backfill_approval.topic_ids) - set(self.topic_categories)
            )
            if missing_topics:
                raise ValueError(
                    f"taxonomy backfill approval names topics without mappings: {missing_topics}"
                )

        # Every mapping is the user's decision — the taxonomy backfill covers the topics
        # that existed at the migration, and everything published since carries its own record.
        # Without this the mapping is a field the publishing agent can extend on its own.
        #
        # The requirement is version-gated because archived revisions are approved bytes: a
        # publication pins the exact metadata it shipped against, and tightening a rule must
        # never make an already-approved release fail to load (publish SKILL.md: renderer
        # evolution never invalidates already-approved bytes).  Revisions written before
        # ``site-metadata-1.1.0`` are read exactly as they were signed.
        if _metadata_revision(self.metadata_version) < (1, 1, 0):
            return self
        per_topic = {approval.topic_id: approval for approval in self.topic_category_approvals}
        if len(per_topic) != len(self.topic_category_approvals):
            raise ValueError("topic category approvals must not name a topic twice")
        backfilled = set(
            self.taxonomy_backfill_approval.topic_ids
            if self.taxonomy_backfill_approval is not None
            else ()
        )
        for topic_id, assigned in sorted(self.topic_categories.items()):
            if topic_id in backfilled:
                if topic_id in per_topic:
                    raise ValueError(
                        f"{topic_id}: covered by the taxonomy backfill, so it must not also "
                        "carry a per-topic approval"
                    )
                continue
            approval = per_topic.get(topic_id)
            if approval is None:
                raise ValueError(
                    f"{topic_id}: category mapping has no user approval — add a "
                    "topic_category_approvals entry naming the categories they chose"
                )
            if list(approval.category_ids) != list(assigned):
                raise ValueError(
                    f"{topic_id}: mapping {assigned} does not match the approved "
                    f"categories {approval.category_ids}"
                )
        orphans = sorted(set(per_topic) - set(self.topic_categories))
        if orphans:
            raise ValueError(f"topic category approvals name topics without mappings: {orphans}")
        return self

    def category(self, category_id: str) -> SiteCategory:
        """Return one controlled category or fail rather than inventing a label."""
        for category in self.categories:
            if category.category_id == category_id:
                return category
        raise KeyError(f"unknown category id: {category_id}")

    def category_label(self, category_id: str, locale: str) -> str:
        return self.category(category_id).labels[normalize_lang(locale)]


def default_metadata_path() -> Path:
    """Path to the checked-in M1 metadata revision; loaders do not use it implicitly."""
    return Path(__file__).with_name("data") / "site_metadata.v1.json"


def load_site_metadata(path: str | Path) -> SiteMetadata:
    """Load and validate one explicit metadata revision from UTF-8 JSON."""
    metadata_path = Path(path)
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    return SiteMetadata.model_validate(payload)
