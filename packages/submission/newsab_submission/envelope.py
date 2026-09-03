"""The submission envelope: the first member of every archive (plan §6.1).

The envelope is the archive's self-description — versions, identity, operation, sponsor
choice, the pinned run closure and the closed member table.  It is a *claim*, not an
authority: G1 recomputes everything it asserts from the archive's own bytes, and the
site's trust ends at "internally consistent"; semantic trust only ever comes from
G2 recomputation plus the private G3/G4 review.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional, Tuple

from pydantic import Field, field_validator, model_validator

from newsab_schema.common import LangText, Record
from newsab_schema.models.manifest import HASH_RE
from newsab_schema.models.publication import SponsorAttribution, TopicRunPin

from . import PROTOCOL_VERSION

#: The seven logical stages a create closure must pin, in order (plan §6.1).
CLOSURE_STAGES: tuple[str, ...] = (
    "scope",
    "corpus",
    "questions",
    "answers",
    "normalization",
    "analysis",
    "page",
)

SUBMISSION_ID_RE = r"^SUB-[0-9a-f]{16}$"
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

#: Archive member paths are chosen by the packer, never by the contributor: everything
#: lives under these fixed roots (plan §6.1 "not the submitter's directory names").
ENVELOPE_MEMBER = "submission.json"
TOPIC_ROOT = "topic"
REGISTRY_MEMBER = "sources/registry.yaml"


class ArchiveMember(Record):
    """One entry of the closed member table.

    ``included`` members carry bytes in the archive.  ``hash_only`` members record the
    hash of a file the closure fingerprints but the archive refuses to carry — today
    that is exactly the page run's rendered ``*.html`` previews (plan §6.1: the site
    rebuilds every displayable surface itself; contributor HTML is never accepted).
    """

    path: str = Field(min_length=1, max_length=300)
    sha256: str = Field(pattern=HASH_RE)
    size_bytes: int = Field(ge=0)
    kind: Literal["included", "hash_only"] = "included"


class SubmissionDiagnostics(Record):
    """Contributor-side results carried for diagnosis only — never a trust input."""

    #: What the contributor's local `verify` reported, if they ran it.
    local_validation: Optional[str] = None
    #: Fingerprint of the local candidate render, per locale (diagnostic).
    preview_fingerprints: dict[str, str] = Field(default_factory=dict)


class SubmissionEnvelope(Record):
    magic: Literal["newsab-submission"] = "newsab-submission"
    protocol_version: str = PROTOCOL_VERSION
    #: The public toolkit that produced the archive (package version; optional VCS ref).
    toolkit_version: str = Field(min_length=1)
    toolkit_ref: Optional[str] = None
    submission_id: str = Field(pattern=SUBMISSION_ID_RE)
    created_at: datetime
    #: There is no revision procedure (privacy notice §4.7):
    #: a corrected report is a ``withdraw`` followed by a new ``create`` under a new
    #: invitation.  ``revise`` is refused by name below so the message says so.
    operation: Literal["create", "withdraw"] = "create"
    #: Required for withdraw: the publication this operation refers to.
    prior_publication_id: Optional[str] = None
    topic_id: str = Field(min_length=1)
    #: The candidate page run the closure ends in (absent for withdraw).
    page_run_id: Optional[str] = None
    requested_locales: Tuple[str, ...] = ()
    sponsor: SponsorAttribution
    terms_version: str = Field(min_length=1)
    #: The contributor's source-responsibility statement (plan §6.1).
    source_statement: LangText
    run_closure: Tuple[TopicRunPin, ...] = ()
    members: Tuple[ArchiveMember, ...] = ()
    diagnostics: SubmissionDiagnostics = Field(default_factory=SubmissionDiagnostics)

    @field_validator("protocol_version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not _SEMVER_RE.match(value):
            raise ValueError(f"protocol_version is not MAJOR.MINOR.PATCH: {value!r}")
        return value

    @model_validator(mode="before")
    @classmethod
    def _no_revision(cls, value):
        if isinstance(value, dict) and value.get("operation") == "revise":
            raise ValueError(
                "revision is not offered by the submission protocol: withdraw the "
                "publication, then submit a new archive under a new invitation"
            )
        return value

    @model_validator(mode="after")
    def _operation_shape(self) -> "SubmissionEnvelope":
        if self.operation == "withdraw":
            if self.prior_publication_id is None:
                raise ValueError("withdraw requires prior_publication_id")
            if self.page_run_id or self.run_closure or self.members:
                raise ValueError("withdraw carries no closure and no data members")
            return self
        if self.prior_publication_id is not None:
            raise ValueError("create must not name a prior publication")
        if not self.page_run_id:
            raise ValueError(f"{self.operation} requires page_run_id")
        if not self.requested_locales:
            raise ValueError(f"{self.operation} requires requested_locales")
        stages = tuple(pin.stage for pin in self.run_closure)
        if stages != CLOSURE_STAGES:
            raise ValueError(
                f"run_closure must pin exactly {list(CLOSURE_STAGES)}, got {list(stages)}"
            )
        if not self.members:
            raise ValueError(f"{self.operation} requires a member table")
        seen: set[str] = set()
        for member in self.members:
            if member.path in seen:
                raise ValueError(f"duplicate member path: {member.path}")
            seen.add(member.path)
        return self


def protocol_compatible(declared: str) -> bool:
    """Same major, declared minor <= ours: we can verify what we could have packed."""
    ours = _SEMVER_RE.match(PROTOCOL_VERSION)
    theirs = _SEMVER_RE.match(declared)
    assert ours is not None
    if theirs is None:
        return False
    return int(theirs.group(1)) == int(ours.group(1)) and int(theirs.group(2)) <= int(
        ours.group(2)
    )
