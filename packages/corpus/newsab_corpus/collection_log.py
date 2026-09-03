"""The collection log — what was searched, what was found, and what failed.

§3.3 S2 requires two things this file exists to make routine: search terms must cover
*every* naming variant of the topic (searching the other side's media with only your own
side's vocabulary is the single largest source of sampling bias), and failures must be
recorded honestly rather than dropped.

A reviewer reading only the artifacts should be able to answer "what would you have found
if you had searched differently?" — this log is the only place that question is answerable.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

EntryKind = Literal["query", "fetch_failure", "excluded", "note", "source_added"]

#: Retrieval layer a fetch was attempted at.  ``http`` is the cheap first try; ``browser``
#: is the Playwright retry that every HTTP refusal must go through before it counts as a
#: failure (``skills/collect/references/fetch-extract.md`` §1.3).
RetrievalLayer = Literal["http", "browser"]

#: ``layer`` became mandatory on ``fetch_failure`` entries from this date -- the first full
#: day after the rule landed (2026-08-27), so runs already in flight when it did are not
#: invalidated mid-run.  Records are immutable (§3.2): earlier logs are not rewritten to
#: satisfy a later rule, they simply predate it.  A pre-cutoff log whose failures were never
#: browser-retried is re-collected, not edited.
LAYER_REQUIRED_FROM = datetime(2026, 8, 28, tzinfo=timezone.utc)

#: ``results_staged`` became mandatory on ``query`` entries from this date -- the first full
#: day after the rule landed (2026-08-29 UTC), following the same convention as
#: :data:`LAYER_REQUIRED_FROM`.  A query line that omits the count is not a smaller version
#: of one that records it: the reconciliation in ``skills/collect/scripts/check_collection_log.py``
#: has to read the omission as zero, so a whole round can be hollowed out while every line
#: still validates -- which is exactly how ``aabb-island-dance-2024``'s first round passed.  Zero is
#: a real and common answer ("this query surfaced nothing new"), so it is written as ``0``;
#: what the field may no longer be is absent.  Earlier logs are not rewritten to satisfy a
#: later rule (§3.2), they simply predate it.
STAGED_REQUIRED_FROM = datetime(2026, 8, 30, tzinfo=timezone.utc)


class CollectionLogEntry(BaseModel):
    """One line of ``corpus/collection_log.jsonl``."""

    model_config = ConfigDict(extra="forbid")

    kind: EntryKind
    at: datetime
    group_id: str = Field(pattern=r"^[a-z]{2,5}$")

    # kind=query
    query: Optional[str] = None
    lang: Optional[str] = None
    engine_or_site: Optional[str] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    results_seen: Optional[int] = None
    results_staged: Optional[int] = None
    #: Which naming variant this query covers, so coverage of the variant matrix is
    #: checkable rather than asserted.
    term_variant: Optional[str] = None

    # kind=fetch_failure / excluded
    url: Optional[str] = None
    source_id: Optional[str] = None
    reason: Optional[str] = None
    #: Which retrieval layer produced this failure.  A refusal at the HTTP layer is a
    #: transport artifact, not the publisher's answer about who may read the page, so it is
    #: not a finding: only a failure that survives the browser retry is one, and this field
    #: is how that is checkable rather than asserted.  A bot-score 403 recorded as a block
    #: becomes an attention gap downstream -- the whole reason the field exists.
    layer: Optional[RetrievalLayer] = None

    # kind=source_added (D19: the source frame is open; additions must leave a trace)
    #: The query that surfaced this outlet, so a reviewer can see the source entered the
    #: frame because it belongs there and not merely because one article was noticed.
    found_via: Optional[str] = None
    #: The snapshot version this addition minted.
    snapshot_id: Optional[str] = None

    #: Points at an earlier entry this one supersedes.  Records are immutable (§3.2), so a
    #: correction is a new line naming what it corrects, never an edit of the old one.
    corrects: Optional[str] = None

    note: Optional[str] = None

    @field_validator("at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)

    def model_post_init(self, __context) -> None:
        if self.kind == "query" and not self.query:
            raise ValueError("kind=query entries must record the query string")
        if (
            self.kind == "query"
            and self.at >= STAGED_REQUIRED_FROM
            and self.results_staged is None
        ):
            raise ValueError(
                "kind=query entries must record results_staged: the corpus is reconciled "
                "against these counts, and an omitted count is read as 0, so a round can "
                "be hollowed out while every line still validates. Write 0 when the query "
                "staged nothing — see skills/collect/references/search-strategy.md §6"
            )
        if self.kind in ("fetch_failure", "excluded") and not self.reason:
            raise ValueError(f"kind={self.kind} entries must record a reason")
        if self.kind == "fetch_failure" and self.at >= LAYER_REQUIRED_FROM and self.layer != "browser":
            raise ValueError(
                "kind=fetch_failure entries must record layer='browser': an HTTP refusal "
                "(403, WAF interstitial, JS challenge, empty body) has to be retried in the "
                "Playwright browser before it counts as a failure — see "
                "skills/collect/references/fetch-extract.md §1.3"
            )
        if self.kind == "source_added" and not (self.source_id and self.found_via):
            raise ValueError("kind=source_added entries must record source_id and found_via")


def variant_coverage(entries: list[CollectionLogEntry], expected: dict[str, list[str]]) -> dict:
    """Which of the expected naming variants were actually searched, per group.

    ``expected`` maps group_id -> the term variants that group's media use for the topic.
    Anything missing is returned so it becomes a decision, not an oversight.
    """
    searched: dict[str, set[str]] = {}
    for entry in entries:
        if entry.kind == "query" and entry.term_variant:
            searched.setdefault(entry.group_id, set()).add(entry.term_variant)
    return {
        group: {
            "searched": sorted(searched.get(group, set())),
            "missing": sorted(set(variants) - searched.get(group, set())),
        }
        for group, variants in expected.items()
    }
