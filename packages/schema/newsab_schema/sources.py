"""Quality rules for ``sources/registry.yaml`` that a model validator cannot state.

:class:`~newsab_schema.models.corpus.SourceEntry` refuses an entry that is structurally
unusable — a missing English masthead, a country code no filter will match.  What it
cannot refuse is an entry that is *filled in badly*: a media card written at an agent
instead of a reader, a front-page URL that is really the article that surfaced the outlet,
a search channel nobody has ever recorded.

Those are warnings rather than errors on purpose.  The registry is knowledge, never a gate
(R-3), so a thin entry must not stop a build; it must be visible to the next agent that
touches this outlet.  Both readers of these rules — ``newsab_schema validate-topic`` and
``newsab_corpus registry check`` — phrase them the same way so that fixing one silences the
other.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models.corpus import SourceEntry

#: Phrases that give away copy written for an agent rather than for a reader.  Every one of
#: them was found in the registry itself, which is why they are listed
#: rather than imagined.
_AGENT_FACING = (
    "auto-registered",
    "由采集运行自动登记",
    "classified at collection time",
    "采集时判定为",
    "backfill",
    "term_variant",
    "d19a",
    "§2.3",
    "vertical trade press",
    "this sampling frame",
    "本采样框",
    "not established during this run",
    "本快照未确认",
    "collection_log",
)

#: A front page is short.  Anything past this many path segments is almost always the
#: article that surfaced the outlet, which sends the reader somewhere arbitrary.
_MAX_URL_SEGMENTS = 2

#: After this long, "we measured this channel" is a claim about a website that has since
#: been redesigned at least once.
_CHANNEL_STALE_DAYS = 365


def registry_entry_problems(entry: "SourceEntry", *, today: date | None = None) -> list[str]:
    """Everything wrong with one outlet's entry, as sentences an agent can act on."""

    problems: list[str] = []

    for lang, text in entry.notes.values.items():
        lowered = text.lower()
        hit = next((phrase for phrase in _AGENT_FACING if phrase in lowered), None)
        if hit is not None:
            problems.append(
                f"notes[{lang}] contains {hit!r}: the media card is one sentence for a "
                "reader about what kind of outlet this is, not a note to the next agent"
            )

    if entry.lang != "en" and entry.lang not in entry.name.values:
        problems.append(
            f"name has no {entry.lang!r} value: an outlet that does not publish in "
            "English is named in its own language first"
        )

    path = entry.url.split("//", 1)[-1].partition("/")[2].strip("/")
    if path and len(path.split("/")) > _MAX_URL_SEGMENTS:
        problems.append(
            f"url {entry.url} looks like an article rather than the outlet's front page"
        )

    # An empty ``channel`` is not a defect.  Most outlets enter through a search engine and
    # nobody ever needed their site search; recording that as a per-entry problem would put
    # a warning on two thirds of the file, which is how warnings stop being read.  What is
    # wrong is a channel note nobody dated, or one dated long enough ago to be fiction.
    channel = entry.channel
    if channel.checked_at is None and channel.search_channel is not None:
        problems.append("channel.search_channel is recorded without a channel.checked_at date")
    elif channel.checked_at is not None:
        age = ((today or date.today()) - channel.checked_at).days
        if age > _CHANNEL_STALE_DAYS:
            problems.append(
                f"channel was last checked {age} days ago; re-measure it before trusting "
                "search_channel, rate_limit or status"
            )

    return problems
