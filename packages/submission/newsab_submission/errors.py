"""Structured refusals for the submission gates (plan §7.1: public error codes).

Every refusal carries a stable ``code`` a contributor can fix against, the gate that
raised it, and a human-readable message.  Codes are part of the public protocol: rename
one only with a protocol version bump.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SubmissionIssue:
    """One machine-readable defect found by a gate."""

    gate: str  # "G0" | "G1" | "G2"
    code: str  # stable identifier, e.g. "G0_PATH_TRAVERSAL"
    message: str
    path: Optional[str] = None  # archive member path, when one is implicated

    def to_dict(self) -> dict:
        payload = {"gate": self.gate, "code": self.code, "message": self.message}
        if self.path is not None:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class SubmissionRefused(Exception):
    """A gate refused the archive.  Never raised after work on the archive's behalf
    has begun — refusal always precedes model calls, imports, or namespace writes
    outside the throwaway work directory."""

    issues: tuple[SubmissionIssue, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.issues:
            raise ValueError("SubmissionRefused requires at least one issue")

    def __str__(self) -> str:
        return "; ".join(
            f"{issue.code}: {issue.message}" for issue in self.issues
        )

    def to_dict(self) -> dict:
        return {"refused": True, "issues": [issue.to_dict() for issue in self.issues]}


def refuse(gate: str, code: str, message: str, path: Optional[str] = None) -> SubmissionRefused:
    return SubmissionRefused(issues=(SubmissionIssue(gate, code, message, path),))
