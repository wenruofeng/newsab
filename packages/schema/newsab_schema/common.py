"""Shared value objects: language-tagged text, provenance, gate records.

Blueprint §1.6 / §3.2: field names and enum values are English; every free-text field
carries a ``lang`` tag; every record carries provenance so any published number is
traceable to the run that produced it.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import Gate, GateDecider

#: Permissive BCP-47 subset: ``en``, ``zh-CN``, ``id``, ``pt-BR``.  Deliberately not a
#: closed list — new topics bring new languages, and rejecting an unknown-but-well-formed
#: tag would block a contributor for no safety gain.
LANG_TAG_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z]{2,4})?(?:-[A-Za-z0-9]{2,8})?$")

#: The English pivot used by the comparison layer (D6 / §1.6 L2).
PIVOT_LANG = "en"


class Record(BaseModel):
    """Base for every artifact record.

    ``frozen`` encodes §3.2's immutability rule at the type level: a correction is a new
    record plus a mapping, never an in-place edit.  ``extra="forbid"`` means a typo in a
    contributor's package fails loudly instead of being silently dropped.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        use_enum_values=False,
        # ``model_id`` is a blueprint field name (§3.2), not a pydantic attribute.
        protected_namespaces=(),
    )


def normalize_lang(raw: str) -> str:
    """Canonical form: lower-case language, upper-case region (``zh-cn`` -> ``zh-CN``)."""
    tag = str(raw).strip()
    if not LANG_TAG_RE.match(tag):
        raise ValueError(f"not a BCP-47-shaped language tag: {raw!r}")
    parts = tag.split("-")
    out = [parts[0].lower()]
    for part in parts[1:]:
        out.append(part.upper() if len(part) == 2 else part.title())
    return "-".join(out)


LangTag = Annotated[str, Field(min_length=2, max_length=16)]


class LangText(Record):
    """A free-text field with its language, per §1.6's hard rule."""

    text: str = Field(min_length=1)
    lang: LangTag

    @field_validator("lang")
    @classmethod
    def _lang(cls, v: str) -> str:
        return normalize_lang(v)

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("text must not be blank")
        return stripped


class MultiLangText(Record):
    """A label carried in several languages at once (topic titles, concept labels)."""

    values: dict[str, str] = Field(min_length=1)

    @field_validator("values")
    @classmethod
    def _values(cls, v: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for lang, text in v.items():
            if not str(text).strip():
                raise ValueError(f"empty label for language {lang!r}")
            out[normalize_lang(lang)] = str(text).strip()
        return out

    def get(self, lang: str, default: Optional[str] = None) -> Optional[str]:
        return self.values.get(normalize_lang(lang), default)


class Provenance(Record):
    """``{skill_version, model_id, run_id, timestamp}`` (§3.2, §4.1).

    ``model_id`` is ``None`` for purely deterministic producers (A1, scripts): recording
    "no model was involved" is itself an audit fact, and D10 makes it a meaningful one.
    """

    skill_version: str = Field(pattern=r"^[A-Za-z0-9]+-\d+\.\d+\.\d+$")
    model_id: Optional[str] = None
    run_id: str = Field(min_length=1)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        """Timestamps are stored in UTC so runs from different contributors sort."""
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @property
    def deterministic(self) -> bool:
        return self.model_id is None


class GateRecord(Record):
    """Who passed a human gate, and whether a human was actually involved.

    AGENTS.md §8: if an LLM stands in for the user at a gate, that fact must reach the
    manifest *and* the published record.  Making it a required field is how it gets there.
    """

    gate: Gate
    decided_by: GateDecider
    decided_at: datetime
    decision: str = Field(pattern=r"^(approved|rejected|approved_with_changes)$")
    note: Optional[LangText] = None
    #: Set when ``decided_by == llm_stand_in``; surfaced on the page.
    stand_in_model_id: Optional[str] = None

    @field_validator("decided_at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)

    def model_post_init(self, __context: Any) -> None:
        if self.decided_by == GateDecider.LLM_STAND_IN and not self.stand_in_model_id:
            raise ValueError(
                "an LLM stand-in gate decision must record stand_in_model_id "
                "(AGENTS.md §8: it has to be shown on the published record)"
            )
