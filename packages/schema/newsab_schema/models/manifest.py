"""Manifest records (§3.2, AGENTS.md §7).

Every run of every stage appends one entry.  The contract a hostile reviewer relies on is
that ``input_hashes`` + ``skill_version`` + ``model_id`` identify what produced each output
hash — so a submission can be re-verified from artifacts alone.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import Field, field_validator, model_validator

from ..common import GateRecord, LangText, Provenance, Record
from ..ids import RUN_ID_RE, validate_topic_id

HASH_RE = r"^sha256:[0-9a-f]{64}$"


def file_digest(path: str | Path) -> str:
    """``sha256:<hex>`` of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def content_digest(obj: Any) -> str:
    """``sha256:<hex>`` of a JSON value, canonicalised so the hash is stable across
    machines, key orderings and Python versions."""
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


class Escalation(Record):
    """Something the run refused to decide on its own (§3.3 escalation conditions)."""

    kind: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    resolved_by: Optional[str] = None


class ManifestEntry(Record):
    """One stage run (§3.2)."""

    skill_id: str = Field(min_length=1)
    skill_version: str = Field(min_length=1)
    #: ``None`` for deterministic stages — A1 records this as null on purpose (D10).
    model_id: Optional[str] = None
    run_id: str = Field(pattern=RUN_ID_RE.pattern)
    topic_id: str
    status: Literal["completed", "no_op", "stopped"] = "completed"
    #: Which versioned stage this run produced, when it produced one.  Together with
    #: ``run_id`` it names the run directory, which is what ``output_set_hash`` is a
    #: fingerprint of.
    stage: Optional[str] = None
    #: The upstream runs this one consumed, by ``run_id`` (R-4).  This is the real
    #: dependency edge: "A1 run X analysed corpus run Y", not "A1 read these bytes at this
    #: path".  Paths move as content legitimately grows; run IDs do not.
    inputs: list[str] = Field(default_factory=list)
    #: Fingerprint of the content set this run produced.  For a corpus run it is the
    #: :class:`CorpusRun` ``set_hash``; for every other stage it is the digest of the run
    #: directory's file hashes.  Verification asks "can this set still be restored, and
    #: does it still fingerprint the same" — a question that survives the corpus growing.
    output_set_hash: Optional[str] = Field(default=None, pattern=HASH_RE)
    #: Byte hashes of the files read and written, kept as **historical evidence** of what
    #: this run touched.  They are deliberately *not* re-verified later (R-4): a mutable
    #: acquisition workspace, or a legitimately extended source registry, would fail a
    #: path-keyed check every time without anything being wrong.
    input_hashes: dict[str, str] = Field(default_factory=dict)
    output_hashes: dict[str, str] = Field(default_factory=dict)
    judge_scores: dict[str, float] = Field(default_factory=dict)
    escalations: list[Escalation] = Field(default_factory=list)
    #: Free-form per-stage counters (articles read, observations emitted, clusters, …).
    counters: dict[str, Any] = Field(default_factory=dict)
    #: Gate decisions taken during this run, including LLM stand-ins (AGENTS.md §8).
    gates: list[GateRecord] = Field(default_factory=list)
    #: Stage-specific audit context that does not participate in threshold decisions.
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @field_validator("timestamp")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)

    @field_validator("input_hashes", "output_hashes")
    @classmethod
    def _hashes(cls, v: dict[str, str]) -> dict[str, str]:
        import re

        bad = {k: h for k, h in v.items() if not re.match(HASH_RE, h)}
        if bad:
            raise ValueError(f"hashes must be 'sha256:<64 hex>'; bad entries: {sorted(bad)}")
        return v

    @field_validator("stage")
    @classmethod
    def _stage(cls, v: Optional[str]) -> Optional[str]:
        from ..paths import STAGE_NAMES

        if v is not None and v not in STAGE_NAMES:
            raise ValueError(f"unknown versioned stage {v!r}; expected one of {STAGE_NAMES}")
        return v

    @model_validator(mode="after")
    def _outputs(self) -> "ManifestEntry":
        if self.status == "completed" and not (self.output_hashes or self.output_set_hash):
            raise ValueError(
                "a completed run must record what it produced (output_set_hash, or "
                "output_hashes for a run that writes no versioned directory); use stopped "
                "with escalations or no_op when it produced none"
            )
        if self.status == "stopped" and not self.escalations:
            raise ValueError("a stopped run must record why it stopped in escalations")
        if self.status == "no_op" and (
            self.output_hashes or self.output_set_hash or self.escalations
        ):
            raise ValueError("a no-op run has neither new outputs nor an escalation")
        if self.output_set_hash is not None and self.stage is None:
            raise ValueError("output_set_hash needs a stage to say which run directory it fingerprints")
        return self

    @property
    def had_human_gate(self) -> bool:
        return any(g.decided_by.value == "human" for g in self.gates)


class ArtifactReference(Record):
    """One immutable file, optionally narrowed to a record inside a stream."""

    run_id: str = Field(pattern=RUN_ID_RE.pattern)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=HASH_RE)
    record_id: Optional[str] = Field(default=None, min_length=1)

    @field_validator("path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value.endswith("/"):
            raise ValueError("artifact path must be a topic-relative file path")
        return path.as_posix()


class CorrectionMapping(Record):
    """Append-only link from an erroneous record/file to its replacement (§3.2)."""

    correction_id: str = Field(pattern=r"^COR-[a-z0-9]+(?:-[a-z0-9]+)*-\d{4,8}$")
    topic_id: str
    superseded: ArtifactReference
    replacement: ArtifactReference
    reason: LangText
    provenance: Provenance
    timestamp: datetime

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, value: str) -> str:
        return validate_topic_id(value)

    @field_validator("timestamp")
    @classmethod
    def _timestamp(cls, value: datetime) -> datetime:
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )

    @model_validator(mode="after")
    def _actually_changes_something(self) -> "CorrectionMapping":
        if self.superseded == self.replacement:
            raise ValueError(
                "a correction replacement must differ from the superseded reference"
            )
        return self


class TopicManifestLog(Record):
    """The append-only chain of runs for one topic (§S10's ``manifest`` directory)."""

    topic_id: str
    entries: list[ManifestEntry] = Field(default_factory=list)

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, v: str) -> str:
        return validate_topic_id(v)

    @model_validator(mode="after")
    def _same_topic(self) -> "TopicManifestLog":
        wrong = sorted({e.topic_id for e in self.entries if e.topic_id != self.topic_id})
        if wrong:
            raise ValueError(f"entries from other topics: {wrong}")
        run_ids = [e.run_id for e in self.entries]
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("duplicate run_id: artifacts are immutable, re-runs get a new id")
        return self

    def latest(self, skill_id: str) -> Optional[ManifestEntry]:
        matching = [e for e in self.entries if e.skill_id == skill_id]
        return max(matching, key=lambda e: e.timestamp) if matching else None
