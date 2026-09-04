"""What one publication cost to produce: agent wall clock and token spend.

**This is operational telemetry, not publication provenance.**  Nothing here is read by
``verify_candidate`` or ``verify_site``, nothing here reaches a bundle, a catalog row or
the event chain, and no publishing step depends on it.  That is deliberate and it is what
makes the reports freely recomputable and backfillable: a wrong or missing cost report can
never invalidate approved bytes.

Reports are keyed by **topic**, not by publication, and record which publication they were
generated for.  A topic that is republished (eight of the first nine have been) produces
one more publication id but not one more production history: publication-keyed files would
report the same sessions twice under two names and make the index unsummable.  The report
therefore reads "what this topic has cost to date, as of that release", and a later run
overwrites it with the fuller number.

Three rules the arithmetic must not get wrong, each learned the expensive way:

1. **Deduplicate by message id, taking the maximum of every field.**  A streaming response
   is written to the transcript many times under one ``message.id``, each row carrying a
   snapshot of the same ``usage`` object.  Summing the rows roughly doubles the bill;
   keeping the *first* row undercuts output tokens by up to 8x, because early snapshots
   report a partial ``output_tokens``.  Max-per-field is the only reading that survives
   both shapes.
2. **Price the four token classes separately.**  Cache reads are ~0.1x input and cache
   writes 1.25x (5-minute TTL) or 2.0x (1-hour), so a run whose cost is 78% cache reads is
   priced 10x wrong by any "input tokens x input rate" shortcut.  The TTL split is in the
   record (``usage.cache_creation``); it is never assumed when it is stated.
3. **An unpriced model is an error, not a zero.**  Silently costing an unknown model at $0
   produces a cheerful, wrong number that nobody can tell from a cheap run.

Prices are data (``data/model_rates.v1.json``), pinned by version and fingerprint into
every report, because list prices change and an old report must stay interpretable.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence

from newsab_schema.artifacts import load_manifest
from newsab_schema.io import ArtifactError
from newsab_schema.models.manifest import content_digest
from newsab_schema.paths import STAGE_NAMES, TopicPaths

#: Run ids as ``newsab_schema.ids.RUN_ID_RE`` writes them.  Only the *kind* prefix is kept
#: (``s2s``, ``ans``, ``edt``, …): it says which stages a session had its hands in, which is
#: the readable signal, while the ids themselves ran to 290 KB of noise per topic.  Kinds
#: are reported raw rather than mapped to stage names, so a new kind needs no maintenance —
#: and "touched" means seen, created *or* merely read.
_RUN_ID = re.compile(r"\b([a-z][a-z0-9]{0,15})-(?:\d{12}|\d{20})-[0-9a-f]{8}\b")

_RATES_FILE = "model_rates.v1.json"

CLAUDE_ADAPTER_VERSION = "claude-code-2"
CODEX_ADAPTER_VERSION = "codex-rollout-1"
GENERIC_ADAPTER_VERSION = "usage-jsonl-2"

#: Claude Code writes locally-generated notices (a dropped connection, a session limit)
#: into the transcript as assistant messages carrying an all-zero ``usage`` block and this
#: model name.  They were never an API call, so they are dropped rather than priced — an
#: unpriced *real* model must still be an error (module docstring §3).
_SYNTHETIC_MODELS = {"<synthetic>", ""}

#: A session that merely *mentions* a topic is not a session that worked on it, and a raw
#: mention count cannot tell them apart: a parallel session following up a *finding* from
#: this topic (the robots-rule fix that came out of aabb-museum-metal-2026) named it 19 times
#: while doing no work on it at all.  What separates them is whether the session handled
#: the topic's **artifacts**: it opened the topic's own directory, or it named the topic's
#: own run ids.  Both defaults are deliberately low because the evidence is qualitative,
#: not statistical — one path touch is already a session that had the artifacts open, and
#: two run ids rules out a report quoting a single id in passing.
DEFAULT_MIN_PATH_MENTIONS = 1
DEFAULT_MIN_RUN_IDS = 2


def default_rates_path() -> Path:
    return Path(__file__).resolve().parent / "data" / _RATES_FILE


@dataclass(frozen=True)
class RateTable:
    """Per-model list prices in USD per million tokens."""

    version: str
    fingerprint: str
    models: Mapping[str, Mapping[str, float]]
    aliases: Mapping[str, str]

    def canonical(self, model: str) -> str:
        return self.aliases.get(model, model)

    def prices(self, model: str) -> bool:
        return self.canonical(model) in self.models

    def price(
        self,
        model: str,
        usage: "Usage",
        *,
        request_input_tokens: Optional[int] = None,
    ) -> float:
        """Price one usage observation.

        ``request_input_tokens`` deliberately stays optional: callers holding an
        aggregate cannot infer whether its total came from one long request or many
        ordinary requests.  Harness adapters pass the individual request size so a
        model's long-context multiplier is applied at the only safe granularity.
        """
        name = self.canonical(model)
        rates = self.models.get(name)
        if rates is None:
            raise ArtifactError(
                f"no price for model {model!r} in {self.version}; add it to "
                f"{_RATES_FILE} rather than counting it as free"
            )
        threshold = int(rates.get("long_context_threshold", 0) or 0)
        is_long = bool(
            request_input_tokens is not None
            and threshold
            and request_input_tokens > threshold
        )
        input_multiplier = (
            float(rates.get("long_context_input_multiplier", 1.0)) if is_long else 1.0
        )
        output_multiplier = (
            float(rates.get("long_context_output_multiplier", 1.0)) if is_long else 1.0
        )

        token_classes = (
            ("input", usage.input_tokens, input_multiplier),
            ("cache_read", usage.cache_read, input_multiplier),
            ("cache_write_5m", usage.cache_write_5m, input_multiplier),
            ("cache_write_1h", usage.cache_write_1h, input_multiplier),
            ("cache_write_unknown", usage.cache_write_unknown, input_multiplier),
            ("output", usage.output_tokens, output_multiplier),
        )
        total = 0.0
        for rate_name, tokens, multiplier in token_classes:
            if not tokens:
                continue
            if rate_name not in rates:
                raise ArtifactError(
                    f"no {rate_name} price for model {model!r} in {self.version}"
                )
            total += tokens * float(rates[rate_name]) * multiplier
        return total / 1_000_000


def load_rates(path: str | Path | None = None) -> RateTable:
    target = Path(path) if path else default_rates_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArtifactError(f"{target}: unreadable rate table — {exc}") from exc
    models = payload.get("models") or {}
    if not models:
        raise ArtifactError(f"{target}: rate table prices no models")
    required = {"input", "output", "cache_read"}
    for name, rates in models.items():
        missing = sorted(required - set(rates))
        if missing:
            raise ArtifactError(f"{target}: {name} is missing rates {missing}")
    return RateTable(
        version=str(payload["rates_version"]),
        fingerprint=content_digest(payload),
        models=models,
        aliases=payload.get("aliases") or {},
    )


@dataclass
class Usage:
    """Harness-neutral usage with mutually exclusive billed input buckets.

    ``input_tokens`` is *uncached* input.  ``cache_read`` and the cache-write
    buckets are the rest of total input.  ``reasoning_output_tokens`` is a
    diagnostic subset of ``output_tokens`` and is therefore never added to it.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_write_unknown: int = 0
    reasoning_output_tokens: int = 0
    requests: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read += other.cache_read
        self.cache_write_5m += other.cache_write_5m
        self.cache_write_1h += other.cache_write_1h
        self.cache_write_unknown += other.cache_write_unknown
        self.reasoning_output_tokens += other.reasoning_output_tokens
        self.requests += other.requests

    @property
    def context_tokens(self) -> int:
        """Everything the model read: uncached input plus both cache classes."""
        return (
            self.input_tokens
            + self.cache_read
            + self.cache_write_5m
            + self.cache_write_1h
            + self.cache_write_unknown
        )

    @property
    def total_tokens(self) -> int:
        """All billed input plus output; reasoning output is already a subset."""
        return self.context_tokens + self.output_tokens


@dataclass(frozen=True)
class UsageRow:
    """One API response, as recorded by whichever harness ran it."""

    message_id: str
    model: str
    timestamp: Optional[str]
    usage: Usage
    raw_usage: Mapping[str, Any] = field(default_factory=dict)


def _row_from_usage(message_id: str, model: str, ts: Optional[str], raw: Mapping) -> UsageRow:
    creation = raw.get("cache_creation") or {}
    write_5m = int(creation.get("ephemeral_5m_input_tokens", 0) or 0)
    write_1h = int(creation.get("ephemeral_1h_input_tokens", 0) or 0)
    if not write_5m and not write_1h:
        # A record that states no TTL split still states a total.  Charging it at the
        # cheaper 5-minute rate understates rather than inflates, and the report says so.
        write_5m = int(raw.get("cache_creation_input_tokens", 0) or 0)
    return UsageRow(
        message_id=message_id,
        model=model,
        timestamp=ts,
        usage=Usage(
            input_tokens=int(raw.get("input_tokens", 0) or 0),
            output_tokens=int(raw.get("output_tokens", 0) or 0),
            cache_read=int(raw.get("cache_read_input_tokens", 0) or 0),
            cache_write_5m=write_5m,
            cache_write_1h=write_1h,
            requests=1,
        ),
        raw_usage=dict(raw),
    )


def collapse(rows: Iterable[UsageRow]) -> list[UsageRow]:
    """One row per ``message_id``, each field the maximum seen.  See module docstring §1."""
    best: dict[str, UsageRow] = {}
    for row in rows:
        seen = best.get(row.message_id)
        if seen is None:
            best[row.message_id] = row
            continue
        merged = Usage(
            input_tokens=max(seen.usage.input_tokens, row.usage.input_tokens),
            output_tokens=max(seen.usage.output_tokens, row.usage.output_tokens),
            cache_read=max(seen.usage.cache_read, row.usage.cache_read),
            cache_write_5m=max(seen.usage.cache_write_5m, row.usage.cache_write_5m),
            cache_write_1h=max(seen.usage.cache_write_1h, row.usage.cache_write_1h),
            cache_write_unknown=max(
                seen.usage.cache_write_unknown, row.usage.cache_write_unknown
            ),
            reasoning_output_tokens=max(
                seen.usage.reasoning_output_tokens, row.usage.reasoning_output_tokens
            ),
            requests=1,
        )
        best[row.message_id] = UsageRow(
            message_id=row.message_id,
            model=seen.model or row.model,
            timestamp=seen.timestamp or row.timestamp,
            usage=merged,
            raw_usage=seen.raw_usage or row.raw_usage,
        )
    return list(best.values())


# --- harness readers -------------------------------------------------------------------
#
# Everything above is harness-neutral.  Below, one reader per transcript format.  A harness
# this repo has never seen feeds the same report through ``read_usage_jsonl``.


def _iter_json_lines(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


@dataclass(frozen=True)
class Evidence:
    """Why a session was judged to have worked on the topic, or not."""

    mentions: int = 0
    # These are found only in actual tool/function-call arguments.
    path_mentions: int = 0
    run_ids: int = 0
    # Transcript-wide strings are retained for audit, never silently called file access.
    transcript_path_mentions: int = 0
    transcript_run_ids: int = 0


@dataclass
class SessionUsage:
    """One harness session and its normalized observations."""

    session_id: str
    source: str
    subagent: bool = False
    harness: str = "generic"
    provider: str = ""
    parent_session_id: Optional[str] = None
    adapter_version: str = GENERIC_ADAPTER_VERSION
    cli_version: str = ""
    evidence: Evidence = field(default_factory=Evidence)
    rows: list[UsageRow] = field(default_factory=list)
    stamps: list[str] = field(default_factory=list)
    run_ids: set[str] = field(default_factory=set)
    included: bool = True
    reason: str = ""
    attribution_method: str = "structured"
    usage_complete: bool = True
    usage_note: str = ""
    pricing_complete: bool = True
    pricing_note: str = ""

    @property
    def key(self) -> str:
        return f"{self.harness}:{self.session_id}"

    @property
    def parent_key(self) -> str:
        return f"{self.harness}:{self.parent_session_id}" if self.parent_session_id else ""


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _claude_tool_text(record: Mapping[str, Any]) -> str:
    message = record.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    calls = [item.get("input") for item in content if isinstance(item, dict) and item.get("type") == "tool_use"]
    return "\n".join(_json_text(call) for call in calls)


def _codex_tool_text(record: Mapping[str, Any]) -> str:
    if record.get("type") != "response_item":
        return ""
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("type") not in {
        "function_call",
        "custom_tool_call",
    }:
        return ""
    # Outputs are deliberately excluded: a tool may print inherited/user text.
    return _json_text({key: payload.get(key) for key in ("name", "arguments", "input")})


def _evidence(
    records: Sequence[Mapping[str, Any]],
    topic_id: str,
    topic_runs: set[str],
    tool_reader,
) -> tuple[Evidence, set[str], str]:
    transcript = "\n".join(_json_text(record) for record in records)
    tool_text = "\n".join(filter(None, (tool_reader(record) for record in records)))
    structured_runs = {run_id for run_id in topic_runs if run_id in tool_text}
    transcript_runs = {run_id for run_id in topic_runs if run_id in transcript}
    all_tool_runs = {match.group(0) for match in _RUN_ID.finditer(tool_text)}
    return (
        Evidence(
            mentions=transcript.count(topic_id),
            path_mentions=tool_text.count(f"topics/{topic_id}"),
            run_ids=len(structured_runs),
            transcript_path_mentions=transcript.count(f"topics/{topic_id}"),
            transcript_run_ids=len(transcript_runs),
        ),
        all_tool_runs,
        tool_text,
    )


def read_claude_code_transcript(path: Path) -> tuple[list[UsageRow], list[str], list[dict]]:
    """Normalized usage, timestamps and parsed records from one Claude Code session."""
    rows: list[UsageRow] = []
    stamps: list[str] = []
    records = list(_iter_json_lines(path))
    for record in records:
        stamp = record.get("timestamp")
        if isinstance(stamp, str):
            stamps.append(stamp)
        message = record.get("message")
        if (
            isinstance(message, dict)
            and isinstance(message.get("usage"), dict)
            and str(message.get("model") or "") not in _SYNTHETIC_MODELS
        ):
            rows.append(
                _row_from_usage(
                    str(message.get("id") or f"{path.name}:{len(rows)}"),
                    str(message.get("model") or ""),
                    stamp if isinstance(stamp, str) else None,
                    message["usage"],
                )
            )
    return rows, stamps, records


def _generic_usage_row(record: Mapping[str, Any], message_id: str, model: str) -> UsageRow:
    if "input_tokens_total" not in record:
        return _row_from_usage(message_id, model, record.get("timestamp"), record)
    total_input = int(record.get("input_tokens_total", 0) or 0)
    cache_read = int(record.get("cache_read_tokens", 0) or 0)
    write_5m = int(record.get("cache_write_5m_tokens", 0) or 0)
    write_1h = int(record.get("cache_write_1h_tokens", 0) or 0)
    write_unknown = int(record.get("cache_write_tokens_unknown", 0) or 0)
    uncached = total_input - cache_read - write_5m - write_1h - write_unknown
    output = int(record.get("output_tokens_total", 0) or 0)
    reasoning = int(record.get("reasoning_output_tokens", 0) or 0)
    if uncached < 0 or reasoning > output:
        raise ArtifactError(f"invalid neutral usage for message {message_id}")
    return UsageRow(
        message_id=message_id,
        model=model,
        timestamp=record.get("timestamp"),
        usage=Usage(
            input_tokens=uncached,
            cache_read=cache_read,
            cache_write_5m=write_5m,
            cache_write_1h=write_1h,
            cache_write_unknown=write_unknown,
            output_tokens=output,
            reasoning_output_tokens=reasoning,
            requests=1,
        ),
        raw_usage=dict(record),
    )


def read_usage_jsonl(path: Path, topic_id: Optional[str] = None) -> list[SessionUsage]:
    """Read explicit harness-neutral work-span observations.

    Every row must bind itself to ``topic_id``.  This prevents a caller from silently
    assigning an entire multi-topic session to whichever report it happens to generate.
    ``input_tokens_total`` includes cached input; reasoning output is an output subset.
    Legacy Anthropic bucket fields remain accepted when the topic binding is present.
    """
    grouped: dict[tuple[str, str], SessionUsage] = {}
    for record in _iter_json_lines(path):
        bound_topic = str(record.get("topic_id") or "")
        if not bound_topic:
            raise ArtifactError(f"{path}: a usage record has no topic_id/work-span binding")
        if topic_id and bound_topic != topic_id:
            continue
        session = str(record.get("session") or "")
        if not session:
            raise ArtifactError(f"{path}: a usage record has no session id")
        harness = str(record.get("harness") or "generic")
        key = (harness, session)
        holder = grouped.setdefault(
            key,
            SessionUsage(
                session_id=session,
                source=str(path),
                subagent=bool(record.get("subagent")),
                harness=harness,
                provider=str(record.get("provider") or ""),
                parent_session_id=record.get("parent_session_id"),
                adapter_version=GENERIC_ADAPTER_VERSION,
                attribution_method="work_span",
                reason=f"explicit work-span binding to {bound_topic}",
            ),
        )
        holder.rows.append(
            _generic_usage_row(
                record,
                str(record.get("message_id") or f"{session}:{len(holder.rows)}"),
                str(record.get("model") or ""),
            )
        )
        stamp = record.get("timestamp")
        if isinstance(stamp, str):
            holder.stamps.append(stamp)
        holder.run_ids.update(record.get("run_ids") or ())
    return list(grouped.values())


def claude_code_projects_dir(repo_root: str | Path, home: Optional[Path] = None) -> Path:
    """Where Claude Code keeps this repo's transcripts (``~/.claude/projects/<slug>``)."""
    base = (home or Path.home()) / ".claude" / "projects"
    # Every character that is not a letter or digit becomes a dash — separators and
    # underscores alike, so ``/home/u/news_ab`` is ``-home-u-news-ab``.
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(repo_root).resolve()))
    return base / slug


def codex_sessions_dir(home: Optional[Path] = None) -> Path:
    """Where Codex stores local rollout JSONL files."""
    return (home or Path.home()) / ".codex" / "sessions"


def topic_run_ids(topics_root: str | Path, topic_id: str) -> set[str]:
    """Every run id this topic's own artifacts carry."""
    root = Path(topics_root) / topic_id
    if not root.is_dir():
        raise ArtifactError(f"{root}: no such topic directory")
    found: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".html", ".png", ".jpg", ".pdf"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found.update(match.group(0) for match in _RUN_ID.finditer(text))
    return found


def topic_active_run_ids(topics_root: str | Path, topic_id: str) -> dict[str, str]:
    """Every stage's currently *active* run id, read from ``manifest/active.json``.

    Narrower than :func:`topic_run_ids` (every run id the topic's artifacts ever mention,
    including superseded ones) on purpose: this is what a cost query should use when there
    is no publication yet to anchor it — "what the topic is made of right now", not its
    whole rewrite history.  A topic with no stage run yet returns an empty mapping (not an
    error); only a missing topic directory is one.
    """
    paths = TopicPaths.for_topic(topics_root, topic_id)
    if not paths.root.is_dir():
        raise ArtifactError(f"{paths.root}: no such topic directory")
    found: dict[str, str] = {}
    for stage in STAGE_NAMES:
        run_id = paths.active_run_id(stage)
        if run_id:
            found[stage] = run_id
    return found


def topic_manifest_entries(topics_root: str | Path, topic_id: str) -> dict[str, dict[str, Any]]:
    """``run_id -> {skill_id, stage, model_id, status, timestamp}`` from the topic's own
    manifest — the one place a run's declared skill and model are recorded without
    guessing at the run id's kind prefix (``ans``, ``edt``, …).

    Empty rather than an error for a topic with no manifest yet.  A run id absent from the
    result just means it predates the manifest or belongs to a stage that never appends
    one (e.g. ``scope``, which produces no versioned stage output) — callers report that
    as a coverage gap, not a zero.
    """
    paths = TopicPaths.for_topic(topics_root, topic_id)
    if not paths.root.is_dir():
        return {}
    entries: dict[str, dict[str, Any]] = {}
    for entry in load_manifest(paths):
        entries[entry.run_id] = {
            "skill_id": entry.skill_id,
            "stage": entry.stage,
            # ``None`` is a legitimate value here (a deterministic stage, D10) and is kept
            # as ``None`` rather than folded into "n/a" — a caller can tell "no model was
            # used" apart from "we don't know" only by also checking the run id is present
            # in this mapping at all.
            "model_id": entry.model_id,
            "status": entry.status,
            "timestamp": entry.timestamp.isoformat().replace("+00:00", "Z"),
        }
    return entries


def _attribute_session(
    holder: SessionUsage,
    topic_id: str,
    *,
    min_path_mentions: int,
    min_run_ids: int,
    include: Sequence[str],
    exclude: Sequence[str],
) -> None:
    if holder.session_id in exclude or holder.key in exclude:
        holder.included, holder.reason = False, "excluded by operator"
        holder.attribution_method = "operator_override"
    elif holder.session_id in include or holder.key in include:
        holder.included, holder.reason = True, "included by operator"
        holder.attribution_method = "operator_override"
    elif holder.evidence.path_mentions >= min_path_mentions:
        holder.included = True
        holder.reason = f"tool call touched topics/{topic_id} {holder.evidence.path_mentions}x"
    elif holder.evidence.run_ids >= min_run_ids:
        holder.included = True
        holder.reason = f"tool call named {holder.evidence.run_ids} of the topic's run ids"
    else:
        holder.included = False
        holder.reason = (
            f"transcript-only mention or parent relation: tool paths "
            f"{holder.evidence.path_mentions}, tool run ids {holder.evidence.run_ids}; "
            f"transcript paths {holder.evidence.transcript_path_mentions}, run ids "
            f"{holder.evidence.transcript_run_ids}"
        )


def discover_claude_code_sessions(
    projects_dir: Path,
    topic_id: str,
    *,
    run_ids: set[str],
    min_path_mentions: int = DEFAULT_MIN_PATH_MENTIONS,
    min_run_ids: int = DEFAULT_MIN_RUN_IDS,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> list[SessionUsage]:
    """Claude sessions attributed from tool calls, never user/inherited prose."""
    if not projects_dir.is_dir():
        raise ArtifactError(
            f"{projects_dir}: no transcript directory — pass --projects-dir, or feed a "
            "harness-neutral --usage-jsonl instead of guessing at a zero-cost report"
        )
    found: list[SessionUsage] = []
    for path in sorted(projects_dir.glob("*.jsonl")):
        rows, stamps, records = read_claude_code_transcript(path)
        evidence, touched_runs, _ = _evidence(records, topic_id, run_ids, _claude_tool_text)
        if not evidence.mentions:
            continue
        session_id = path.stem
        holder = SessionUsage(
            session_id=session_id,
            source=str(path),
            harness="claude-code",
            provider="anthropic",
            adapter_version=CLAUDE_ADAPTER_VERSION,
            evidence=evidence,
            rows=rows,
            stamps=stamps,
            run_ids=touched_runs,
        )
        _attribute_session(
            holder,
            topic_id,
            min_path_mentions=min_path_mentions,
            min_run_ids=min_run_ids,
            include=include,
            exclude=exclude,
        )
        found.append(holder)

        # Subagents write under <session>/subagents/*.jsonl.  Parentage is recorded but
        # never grants attribution: a parent can spawn siblings for unrelated topics.
        pool = projects_dir / session_id / "subagents"
        if not pool.is_dir():
            continue
        for sub_path in sorted(pool.glob("*.jsonl")):
            rows, stamps, records = read_claude_code_transcript(sub_path)
            sub_evidence, touched, _ = _evidence(records, topic_id, run_ids, _claude_tool_text)
            if not sub_evidence.mentions:
                continue
            sub = SessionUsage(
                session_id=f"{session_id}/{sub_path.stem}",
                source=str(sub_path),
                subagent=True,
                harness="claude-code",
                provider="anthropic",
                parent_session_id=session_id,
                adapter_version=CLAUDE_ADAPTER_VERSION,
                evidence=sub_evidence,
                rows=rows,
                stamps=stamps,
                run_ids=touched,
            )
            _attribute_session(
                sub,
                topic_id,
                min_path_mentions=min_path_mentions,
                min_run_ids=min_run_ids,
                include=include,
                exclude=exclude,
            )
            found.append(sub)
    return found


def _codex_usage_row(
    message_id: str,
    model: str,
    stamp: Optional[str],
    raw: Mapping[str, Any],
) -> UsageRow:
    total_input = int(raw.get("input_tokens", 0) or 0)
    cached = int(raw.get("cached_input_tokens", 0) or 0)
    cache_write = int(raw.get("cache_write_input_tokens", 0) or 0)
    output = int(raw.get("output_tokens", 0) or 0)
    reasoning = int(raw.get("reasoning_output_tokens", 0) or 0)
    uncached = total_input - cached - cache_write
    if uncached < 0:
        raise ArtifactError(
            f"Codex usage {message_id}: cached/write input exceeds total input"
        )
    if reasoning > output:
        raise ArtifactError(f"Codex usage {message_id}: reasoning exceeds total output")
    return UsageRow(
        message_id=message_id,
        model=model,
        timestamp=stamp,
        usage=Usage(
            input_tokens=uncached,
            output_tokens=output,
            cache_read=cached,
            cache_write_unknown=cache_write,
            reasoning_output_tokens=reasoning,
            requests=1,
        ),
        raw_usage=dict(raw),
    )


def read_codex_rollout(path: Path) -> tuple[SessionUsage, list[dict]]:
    """Read one observed Codex rollout schema into neutral observations.

    ``last_token_usage`` rows are additive.  The cumulative total is used only as a
    consistency check, never summed across snapshots.  If an older row has no ``last``
    value, its monotone cumulative delta is used and coverage is marked partial.
    """
    records = list(_iter_json_lines(path))
    meta = next((r.get("payload") for r in records if r.get("type") == "session_meta"), {})
    if not isinstance(meta, dict):
        meta = {}
    session_id = str(meta.get("id") or meta.get("session_id") or path.stem)
    holder = SessionUsage(
        session_id=session_id,
        source=str(path),
        subagent=bool(meta.get("parent_thread_id")),
        harness="codex",
        provider=str(meta.get("model_provider") or "openai"),
        parent_session_id=meta.get("parent_thread_id"),
        adapter_version=CODEX_ADAPTER_VERSION,
        cli_version=str(meta.get("cli_version") or ""),
    )
    model = next(
        (
            str(record.get("payload", {}).get("model") or "")
            for record in records
            if record.get("type") == "turn_context"
            and isinstance(record.get("payload"), dict)
            and record.get("payload", {}).get("model")
        ),
        "",
    )
    previous_total: Optional[Mapping[str, Any]] = None
    final_total: Optional[Mapping[str, Any]] = None
    seen_totals: set[tuple[int, ...]] = set()
    raw_sums = {key: 0 for key in (
        "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
        "output_tokens", "reasoning_output_tokens", "total_tokens",
    )}
    used_delta = False
    for index, record in enumerate(records):
        stamp = record.get("timestamp")
        if isinstance(stamp, str):
            holder.stamps.append(stamp)
        payload = record.get("payload")
        if record.get("type") == "turn_context" and isinstance(payload, dict):
            model = str(payload.get("model") or model)
        if record.get("type") != "event_msg" or not isinstance(payload, dict):
            continue
        if payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        if not isinstance(info, dict):
            holder.usage_complete = False
            holder.usage_note = "token_count event has no info object"
            continue
        total = info.get("total_token_usage")
        last = info.get("last_token_usage")
        if isinstance(total, dict):
            final_total = total
            fingerprint = tuple(int(total.get(key, 0) or 0) for key in raw_sums)
            if fingerprint in seen_totals:
                # Codex can repeat the same token_count solely to update rate-limit
                # metadata.  Its repeated ``last`` block is not another model call.
                continue
            seen_totals.add(fingerprint)
        raw: Optional[dict] = dict(last) if isinstance(last, dict) else None
        if raw is None and isinstance(total, dict):
            used_delta = True
            raw = {
                key: max(0, int(total.get(key, 0) or 0) - int((previous_total or {}).get(key, 0) or 0))
                for key in raw_sums
            }
        if isinstance(total, dict):
            previous_total = total
        if raw is None:
            holder.usage_complete = False
            holder.usage_note = "token_count event has neither last nor cumulative usage"
            continue
        for key in raw_sums:
            raw_sums[key] += int(raw.get(key, 0) or 0)
        holder.rows.append(
            _codex_usage_row(
                f"{session_id}:token-{record.get('ordinal', index)}",
                model,
                stamp if isinstance(stamp, str) else None,
                raw,
            )
        )
    if used_delta:
        holder.usage_complete = False
        holder.usage_note = "older cumulative-only usage converted by monotone deltas"
    if final_total is not None:
        mismatched = [
            key for key in raw_sums
            if raw_sums[key] != int(final_total.get(key, 0) or 0)
        ]
        if mismatched:
            holder.usage_complete = False
            holder.usage_note = "last-usage sum differs from final cumulative: " + ", ".join(mismatched)
    elif not holder.rows:
        holder.usage_complete = False
        holder.usage_note = "rollout contains no usage observations"
    return holder, records


def _is_within(path: str, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def discover_codex_sessions(
    sessions_dir: Path,
    repo_root: str | Path,
    topic_id: str,
    *,
    run_ids: set[str],
    min_path_mentions: int = DEFAULT_MIN_PATH_MENTIONS,
    min_run_ids: int = DEFAULT_MIN_RUN_IDS,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> list[SessionUsage]:
    """Discover repo-local Codex roots/subagents and restore their parent relation."""
    if not sessions_dir.is_dir():
        raise ArtifactError(f"{sessions_dir}: no Codex sessions directory")
    all_sessions: dict[str, SessionUsage] = {}
    for path in sorted(sessions_dir.rglob("rollout-*.jsonl")):
        holder, records = read_codex_rollout(path)
        meta = next((r.get("payload") for r in records if r.get("type") == "session_meta"), {})
        if not isinstance(meta, dict) or not _is_within(str(meta.get("cwd") or ""), Path(repo_root)):
            continue
        evidence, touched_runs, _ = _evidence(records, topic_id, run_ids, _codex_tool_text)
        holder.evidence = evidence
        holder.run_ids = touched_runs
        all_sessions[holder.session_id] = holder

    found: list[SessionUsage] = []
    candidates = {
        sid for sid, session in all_sessions.items()
        if session.evidence.mentions or sid in include or session.key in include
    }
    for sid in sorted(candidates):
        holder = all_sessions[sid]
        _attribute_session(
            holder,
            topic_id,
            min_path_mentions=min_path_mentions,
            min_run_ids=min_run_ids,
            include=include,
            exclude=exclude,
        )
        found.append(holder)
    return found


# --- report ----------------------------------------------------------------------------


def portable(path: str | Path) -> str:
    """Home-relative form of a transcript path.

    Reports are versioned, so an absolute ``/home/<user>/...`` would bake one machine's
    layout (and its username) into git and read as noise on any other clone.
    """
    text = str(path)
    home = str(Path.home())
    return f"~{text[len(home):]}" if text.startswith(home) else text


def _parse(stamp: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _span(stamps: Sequence[str]) -> tuple[Optional[datetime], Optional[datetime]]:
    moments = sorted(m for m in (_parse(s) for s in stamps) if m is not None)
    return (moments[0], moments[-1]) if moments else (None, None)


def _union_minutes(spans: Sequence[tuple[datetime, datetime]]) -> float:
    """Wall clock the *operator* waited: overlapping sessions are not additive.

    Subagents run inside their parent's span, so summing rows would bill their minutes
    twice.  Merge the intervals instead.
    """
    ordered = sorted(spans)
    total = 0.0
    cursor_start: Optional[datetime] = None
    cursor_end: Optional[datetime] = None
    for start, end in ordered:
        if cursor_end is None:
            cursor_start, cursor_end = start, end
            continue
        if start <= cursor_end:
            cursor_end = max(cursor_end, end)
        else:
            total += (cursor_end - cursor_start).total_seconds()
            cursor_start, cursor_end = start, end
    if cursor_end is not None and cursor_start is not None:
        total += (cursor_end - cursor_start).total_seconds()
    return round(total / 60.0, 1)


@dataclass
class SessionLine:
    session_id: str
    harness: str
    provider: str
    parent_session_id: str
    kind: str
    model: str
    start: str
    end: str
    wall_clock_minutes: float
    usage: Usage
    usd: Optional[float]
    pricing_status: str
    run_kinds: str
    #: The full run ids (not just kind prefixes) this session's tool calls named, for
    #: grouping cost by run_id/skill.  Not filtered to the query's target run ids — that
    #: intersection happens where the grouping is computed, so this stays a plain fact
    #: about the session.
    run_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Coverage:
    configured_harnesses: tuple[str, ...]
    observed_harnesses: tuple[str, ...]
    missing_harnesses: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass
class HarnessTotal:
    wall_clock_minutes: float
    sessions: int
    usage: Usage
    total_usd: Optional[float]
    priced_usd: float
    pricing_status: str


@dataclass
class CostReport:
    #: ``None`` when the report was run by ``--topic-id``/``--run-id`` before any
    #: publication exists — the report is keyed by topic either way (module docstring).
    publication_id: Optional[str]
    topic_id: str
    generated_at: str
    rates_version: str
    rates_fingerprint: str
    lines: list[SessionLine]
    candidates: list[dict]
    wall_clock_minutes: float
    totals_by_model: dict[str, Usage]
    totals_by_harness: dict[str, HarnessTotal]
    total_usd: Optional[float]
    priced_usd: float
    pricing_status: str
    usage_coverage: str
    attribution_coverage: str
    coverage: Coverage
    reader: str
    #: Per-run_id breakdown (skill_id/model_id from the topic's manifest, tokens/usd/wall
    #: clock from sessions *exclusively* attributed to that one run). See ``_group_by_run``.
    by_run: list[dict] = field(default_factory=list)
    #: ``by_run`` rolled up per skill_id.
    by_skill: list[dict] = field(default_factory=list)
    #: Sessions whose tool calls named more than one queried run id in one conversation —
    #: cannot be split by run without further instrumentation, so kept out of
    #: ``by_run``/``by_skill`` and reported once here instead of being double-counted.
    cross_stage: dict = field(default_factory=dict)

    def csv_rows(self) -> list[list]:
        head = [
            "session",
            "harness",
            "provider",
            "parent_session",
            "kind",
            "model",
            "start_utc",
            "end_utc",
            "wall_clock_minutes",
            "requests",
            "uncached_input_tokens",
            "cache_write_5m_tokens",
            "cache_write_1h_tokens",
            "cache_write_unknown_tokens",
            "cache_read_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "pricing_status",
            "usd",
            "run_kinds",
        ]
        body = [
            [
                line.session_id,
                line.harness,
                line.provider,
                line.parent_session_id,
                line.kind,
                line.model,
                line.start,
                line.end,
                f"{line.wall_clock_minutes:.1f}",
                line.usage.requests,
                line.usage.input_tokens,
                line.usage.cache_write_5m,
                line.usage.cache_write_1h,
                line.usage.cache_write_unknown,
                line.usage.cache_read,
                line.usage.output_tokens,
                line.usage.reasoning_output_tokens,
                line.pricing_status,
                f"{line.usd:.4f}" if line.usd is not None else "",
                line.run_kinds,
            ]
            for line in self.lines
        ]
        return [head, *body]

    def to_json(self) -> dict:
        return {
            "publication_id": self.publication_id,
            "topic_id": self.topic_id,
            "generated_at": self.generated_at,
            "reader": self.reader,
            "coverage": {
                "harnesses_configured": list(self.coverage.configured_harnesses),
                "harnesses_observed": list(self.coverage.observed_harnesses),
                "harnesses_missing": list(self.coverage.missing_harnesses),
                "usage_coverage": self.usage_coverage,
                "attribution_coverage": self.attribution_coverage,
                "pricing_status": self.pricing_status,
                "notes": list(self.coverage.notes),
            },
            "rates_version": self.rates_version,
            "rates_fingerprint": self.rates_fingerprint,
            "pricing_note": (
                "List-price equivalent in USD, not an invoice: this repo's agents run "
                "under a subscription that bills differently."
            ),
            "wall_clock_minutes": self.wall_clock_minutes,
            "total_tokens": sum(usage.total_tokens for usage in self.totals_by_model.values()),
            "total_usd": round(self.total_usd, 4) if self.total_usd is not None else None,
            "priced_usd": round(self.priced_usd, 4),
            "pricing_status": self.pricing_status,
            "by_harness": {
                harness: {
                    "wall_clock_minutes": total.wall_clock_minutes,
                    "sessions": total.sessions,
                    "requests": total.usage.requests,
                    "uncached_input_tokens": total.usage.input_tokens,
                    "cache_write_5m_tokens": total.usage.cache_write_5m,
                    "cache_write_1h_tokens": total.usage.cache_write_1h,
                    "cache_write_unknown_tokens": total.usage.cache_write_unknown,
                    "cache_read_tokens": total.usage.cache_read,
                    "context_tokens": total.usage.context_tokens,
                    "output_tokens": total.usage.output_tokens,
                    "reasoning_output_tokens": total.usage.reasoning_output_tokens,
                    "total_tokens": total.usage.total_tokens,
                    "usd": round(total.total_usd, 4) if total.total_usd is not None else None,
                    "priced_usd": round(total.priced_usd, 4),
                    "pricing_status": total.pricing_status,
                }
                for harness, total in sorted(self.totals_by_harness.items())
            },
            "by_model": {
                model: {
                    "requests": usage.requests,
                    "uncached_input_tokens": usage.input_tokens,
                    "cache_write_5m_tokens": usage.cache_write_5m,
                    "cache_write_1h_tokens": usage.cache_write_1h,
                    "cache_write_unknown_tokens": usage.cache_write_unknown,
                    "cache_read_tokens": usage.cache_read,
                    "context_tokens": usage.context_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                    "reasoning_output_tokens": usage.reasoning_output_tokens,
                    "pricing_status": "complete"
                    if all(
                        line.usd is not None
                        for line in self.lines
                        if line.model == model
                    )
                    else "unpriced",
                }
                for model, usage in sorted(self.totals_by_model.items())
            },
            "sessions": [
                {
                    "session": line.session_id,
                    "harness": line.harness,
                    "provider": line.provider,
                    "parent_session": line.parent_session_id or None,
                    "kind": line.kind,
                    "model": line.model,
                    "start_utc": line.start,
                    "end_utc": line.end,
                    "wall_clock_minutes": line.wall_clock_minutes,
                    "requests": line.usage.requests,
                    "input_tokens_total": line.usage.context_tokens,
                    "uncached_input_tokens": line.usage.input_tokens,
                    "cache_read_tokens": line.usage.cache_read,
                    "cache_write_5m_tokens": line.usage.cache_write_5m,
                    "cache_write_1h_tokens": line.usage.cache_write_1h,
                    "cache_write_unknown_tokens": line.usage.cache_write_unknown,
                    "output_tokens_total": line.usage.output_tokens,
                    "reasoning_output_tokens": line.usage.reasoning_output_tokens,
                    "pricing_status": line.pricing_status,
                    "usd": round(line.usd, 4) if line.usd is not None else None,
                    "run_kinds": line.run_kinds.split(" ") if line.run_kinds else [],
                    "run_ids": list(line.run_ids),
                }
                for line in self.lines
            ],
            "attribution": self.candidates,
            "by_run": self.by_run,
            "by_skill": self.by_skill,
            "cross_stage": self.cross_stage,
        }


def _group_by_run(
    lines: Sequence[SessionLine],
    target_run_ids: Sequence[str],
    manifest_entries: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict], list[dict], dict]:
    """Roll session-level ``lines`` up by run_id, then by skill_id.

    A session's tokens/usd/wall-clock are attributed to a run only when that session's
    *own* run ids (as its tool calls named them) intersect the queried ``target_run_ids``
    in exactly one place — that is the only case in which "this session's cost belongs to
    this run" is a fact rather than a guess.  A session that names two or more of the
    queried runs in one conversation cannot be split between them without instrumentation
    this repo does not have (module docstring); it is reported once in ``cross_stage``
    instead of being double-counted into every run
    it touched.  A run with no exclusively-attributed session is not silently a zero: its
    numeric fields come back ``None`` (serialised as JSON ``null``) with
    ``coverage: "no_exclusive_sessions"``, so a reader cannot mistake "unmeasured" for
    "measured at zero".
    """
    target = sorted(set(target_run_ids))
    target_set = set(target)
    runs: list[dict] = []
    skill_acc: dict[str, dict[str, Any]] = {}

    for run_id in target:
        entry = manifest_entries.get(run_id)
        exclusive = [ln for ln in lines if set(ln.run_ids) & target_set == {run_id}]
        shared = [
            ln
            for ln in lines
            if run_id in ln.run_ids and len(set(ln.run_ids) & target_set) > 1
        ]
        usage = Usage()
        usd_total = 0.0
        has_unpriced = False
        wall_total = 0.0
        for ln in exclusive:
            usage.add(ln.usage)
            wall_total += ln.wall_clock_minutes
            if ln.usd is None:
                has_unpriced = True
            else:
                usd_total += ln.usd
        has_data = bool(exclusive)
        skill_id = entry.get("skill_id") if entry else None
        runs.append(
            {
                "run_id": run_id,
                "manifest_entry_found": entry is not None,
                "skill_id": skill_id,
                "stage": entry.get("stage") if entry else None,
                "model_id": entry.get("model_id") if entry else None,
                "manifest_status": entry.get("status") if entry else None,
                "finalized_at": entry.get("timestamp") if entry else None,
                "coverage": "exclusive_sessions" if has_data else "no_exclusive_sessions",
                "sessions": sorted({ln.session_id for ln in exclusive}),
                "shared_sessions": sorted({ln.session_id for ln in shared}),
                "requests": usage.requests if has_data else None,
                "uncached_input_tokens": usage.input_tokens if has_data else None,
                "cache_read_tokens": usage.cache_read if has_data else None,
                "cache_write_5m_tokens": usage.cache_write_5m if has_data else None,
                "cache_write_1h_tokens": usage.cache_write_1h if has_data else None,
                "cache_write_unknown_tokens": usage.cache_write_unknown if has_data else None,
                "output_tokens": usage.output_tokens if has_data else None,
                "total_tokens": usage.total_tokens if has_data else None,
                "wall_clock_minutes": round(wall_total, 1) if has_data else None,
                "usd": (round(usd_total, 4) if not has_unpriced else None) if has_data else None,
                "pricing_status": (
                    "n/a" if not has_data else ("unpriced" if has_unpriced else "complete")
                ),
            }
        )
        if skill_id:
            acc = skill_acc.setdefault(
                skill_id,
                {"usage": Usage(), "usd": 0.0, "unpriced": False, "wall": 0.0, "runs": 0, "runs_with_data": 0},
            )
            acc["runs"] += 1
            if has_data:
                acc["runs_with_data"] += 1
                acc["usage"].add(usage)
                acc["wall"] += wall_total
                if has_unpriced:
                    acc["unpriced"] = True
                else:
                    acc["usd"] += usd_total

    by_skill = [
        {
            "skill_id": skill_id,
            "runs": acc["runs"],
            "runs_with_data": acc["runs_with_data"],
            "requests": acc["usage"].requests,
            "uncached_input_tokens": acc["usage"].input_tokens,
            "cache_read_tokens": acc["usage"].cache_read,
            "cache_write_5m_tokens": acc["usage"].cache_write_5m,
            "cache_write_1h_tokens": acc["usage"].cache_write_1h,
            "cache_write_unknown_tokens": acc["usage"].cache_write_unknown,
            "output_tokens": acc["usage"].output_tokens,
            "total_tokens": acc["usage"].total_tokens,
            "wall_clock_minutes": round(acc["wall"], 1) if acc["runs_with_data"] else None,
            "usd": round(acc["usd"], 4) if acc["runs_with_data"] and not acc["unpriced"] else None,
            "pricing_status": (
                "n/a"
                if not acc["runs_with_data"]
                else ("unpriced" if acc["unpriced"] else "complete")
            ),
        }
        for skill_id, acc in sorted(skill_acc.items())
    ]

    cross_usage = Usage()
    cross_usd = 0.0
    cross_has_unpriced = False
    cross_sessions: set[str] = set()
    for ln in lines:
        touched = set(ln.run_ids) & target_set
        if len(touched) > 1:
            cross_usage.add(ln.usage)
            cross_sessions.add(ln.session_id)
            if ln.usd is None:
                cross_has_unpriced = True
            else:
                cross_usd += ln.usd
    cross_stage = {
        "sessions": sorted(cross_sessions),
        "note": (
            "sessions whose tool calls named more than one of the queried run ids in the "
            "same conversation; their tokens/usd cannot be split by run without further "
            "instrumentation, so they are excluded from by_run/by_skill and reported once "
            "here instead of being double-counted into every run they touched"
        ),
        "requests": cross_usage.requests,
        "total_tokens": cross_usage.total_tokens,
        "usd": round(cross_usd, 4) if cross_sessions and not cross_has_unpriced else None,
        "pricing_status": (
            "n/a" if not cross_sessions else ("unpriced" if cross_has_unpriced else "complete")
        ),
    }
    return runs, by_skill, cross_stage


def build_report(
    publication_id: Optional[str],
    topic_id: str,
    sessions: Sequence[SessionUsage],
    rates: RateTable,
    *,
    reader: str,
    coverage: Optional[Coverage] = None,
    now: Optional[datetime] = None,
    target_run_ids: Sequence[str] = (),
    manifest_entries: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> CostReport:
    lines: list[SessionLine] = []
    candidates: list[dict] = []
    totals: dict[str, Usage] = {}
    spans: list[tuple[datetime, datetime]] = []
    spans_by_harness: dict[str, list[tuple[datetime, datetime]]] = {}
    priced_usd = 0.0
    unpriced = False
    priced = False
    for session in sessions:
        candidates.append(
            {
                "session": session.key,
                "raw_session_id": session.session_id,
                "harness": session.harness,
                "provider": session.provider,
                "parent_session": session.parent_key or None,
                "adapter_version": session.adapter_version,
                "cli_version": session.cli_version or None,
                "source": portable(session.source),
                "mentions": session.evidence.mentions,
                "structured_topic_path_touches": session.evidence.path_mentions,
                "structured_topic_run_ids": session.evidence.run_ids,
                "transcript_topic_path_mentions": session.evidence.transcript_path_mentions,
                "transcript_topic_run_ids": session.evidence.transcript_run_ids,
                "included": session.included,
                "reason": session.reason,
                "attribution_method": session.attribution_method,
                "usage_complete": session.usage_complete,
                "usage_note": session.usage_note or None,
                "pricing_complete": session.pricing_complete,
                "pricing_note": session.pricing_note or None,
            }
        )
        if not session.included:
            continue
        start, end = _span(session.stamps)
        if start is not None and end is not None:
            spans.append((start, end))
            spans_by_harness.setdefault(session.harness, []).append((start, end))
        by_model: dict[str, Usage] = {}
        usd_by_model: dict[str, float] = {}
        unpriced_by_model: set[str] = set()
        for row in collapse(session.rows):
            model = rates.canonical(row.model)
            by_model.setdefault(model, Usage()).add(row.usage)
            if not rates.prices(model) or not session.pricing_complete:
                unpriced_by_model.add(model)
                continue
            try:
                usd_by_model[model] = usd_by_model.get(model, 0.0) + rates.price(
                    model,
                    row.usage,
                    request_input_tokens=row.usage.context_tokens,
                )
            except ArtifactError:
                unpriced_by_model.add(model)
        for model, usage in sorted(by_model.items()):
            if model not in unpriced_by_model:
                usd: Optional[float] = usd_by_model.get(model, 0.0)
                priced_usd += usd
                priced = True
                pricing = "complete"
            else:
                usd = None
                unpriced = True
                pricing = "unpriced"
            totals.setdefault(model, Usage()).add(usage)
            lines.append(
                SessionLine(
                    session_id=session.key,
                    harness=session.harness,
                    provider=session.provider,
                    parent_session_id=session.parent_key,
                    kind="subagents" if session.subagent else "session",
                    model=model,
                    start=start.isoformat().replace("+00:00", "Z") if start else "",
                    end=end.isoformat().replace("+00:00", "Z") if end else "",
                    wall_clock_minutes=round((end - start).total_seconds() / 60.0, 1)
                    if start and end
                    else 0.0,
                    usage=usage,
                    usd=usd,
                    pricing_status=pricing,
                    run_kinds=" ".join(sorted({rid.split("-")[0] for rid in session.run_ids})),
                    run_ids=tuple(sorted(session.run_ids)),
                )
            )
    if coverage is None:
        harnesses = tuple(sorted({session.harness for session in sessions}))
        coverage = Coverage(harnesses, harnesses)
    usage_coverage = (
        "partial"
        if coverage.missing_harnesses or any(not session.usage_complete for session in sessions if session.included)
        else "complete"
    )
    methods = {session.attribution_method for session in sessions if session.included}
    if "transcript_heuristic" in methods and len(methods) > 1:
        attribution_coverage = "mixed"
    elif "transcript_heuristic" in methods:
        attribution_coverage = "heuristic"
    else:
        attribution_coverage = "exact"
    pricing_status = "partial" if priced and unpriced else "unavailable" if unpriced else "complete"
    totals_by_harness: dict[str, HarnessTotal] = {}
    configured_harnesses = set(coverage.configured_harnesses)
    configured_harnesses.update(line.harness for line in lines)
    for harness in sorted(configured_harnesses):
        harness_lines = [line for line in lines if line.harness == harness]
        harness_usage = Usage()
        for line in harness_lines:
            harness_usage.add(line.usage)
        harness_priced = sum(line.usd or 0.0 for line in harness_lines)
        has_unpriced = any(line.usd is None for line in harness_lines)
        if harness in coverage.missing_harnesses:
            harness_status = "unavailable"
        elif has_unpriced and harness_priced:
            harness_status = "partial"
        elif has_unpriced:
            harness_status = "unavailable"
        else:
            harness_status = "complete"
        totals_by_harness[harness] = HarnessTotal(
            wall_clock_minutes=_union_minutes(spans_by_harness.get(harness, [])),
            sessions=len({line.session_id for line in harness_lines}),
            usage=harness_usage,
            total_usd=harness_priced if harness_status == "complete" else None,
            priced_usd=harness_priced,
            pricing_status=harness_status,
        )
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds").replace("+00:00", "Z")
    by_run, by_skill, cross_stage = _group_by_run(lines, target_run_ids, manifest_entries or {})
    return CostReport(
        publication_id=publication_id,
        topic_id=topic_id,
        generated_at=stamp,
        rates_version=rates.version,
        rates_fingerprint=rates.fingerprint,
        lines=lines,
        candidates=candidates,
        wall_clock_minutes=_union_minutes(spans),
        totals_by_model=totals,
        totals_by_harness=totals_by_harness,
        total_usd=priced_usd if pricing_status == "complete" else None,
        priced_usd=priced_usd,
        pricing_status=pricing_status,
        usage_coverage=usage_coverage,
        attribution_coverage=attribution_coverage,
        coverage=coverage,
        reader=reader,
        by_run=by_run,
        by_skill=by_skill,
        cross_stage=cross_stage,
    )


def cost_dir(site_root: str | Path) -> Path:
    return Path(site_root) / "audit" / "cost"


def write_report(site_root: str | Path, report: CostReport) -> tuple[Path, Path]:
    target = cost_dir(site_root)
    target.mkdir(parents=True, exist_ok=True)
    csv_path = target / f"{report.topic_id}.csv"
    json_path = target / f"{report.topic_id}.json"
    with csv_path.open("w", encoding="utf-8", newline="\n") as handle:
        csv.writer(handle, lineterminator="\n").writerows(report.csv_rows())
    json_path.write_text(
        json.dumps(report.to_json(), indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return csv_path, json_path


def rebuild_index(site_root: str | Path) -> Path:
    """One row per publication, for cross-topic analysis.

    The per-publication CSV is one row per session and carries no total row, so summing it
    is always correct; the totals live here instead of being repeated there.
    """
    target = cost_dir(site_root)
    target.mkdir(parents=True, exist_ok=True)
    rows = [
        [
            "topic_id",
            "as_of_publication_id",
            "generated_at",
            "claude_wall_clock_minutes",
            "claude_requests",
            "claude_context_tokens",
            "claude_output_tokens",
            "claude_total_tokens",
            "claude_usd",
            "codex_wall_clock_minutes",
            "codex_requests",
            "codex_context_tokens",
            "codex_output_tokens",
            "codex_total_tokens",
            "codex_usd",
            "total_wall_clock_minutes",
            "total_requests",
            "total_context_tokens",
            "total_output_tokens",
            "total_tokens",
            "total_usd",
            "rates_version",
            "harnesses_configured",
            "harnesses_observed",
            "usage_coverage",
            "attribution_coverage",
            "pricing_status",
        ]
    ]
    for path in sorted(target.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        by_model = payload.get("by_model", {})
        by_harness = payload.get("by_harness", {})
        coverage = payload.get("coverage") or {}
        total_usd = payload.get("total_usd")
        claude = by_harness.get("claude-code", {})
        codex = by_harness.get("codex", {})

        def _usd(summary: Mapping[str, Any]) -> str:
            value = summary.get("usd")
            return f"{value:.4f}" if value is not None else ""

        def _value(summary: Mapping[str, Any], key: str) -> int | float:
            return summary.get(key, 0)

        rows.append(
            [
                payload["topic_id"],
                # "" for a pre-activation report (--topic-id/--run-id, no publication yet)
                # rather than the literal string "None" a bare csv.writer would emit.
                payload.get("publication_id") or "",
                payload["generated_at"],
                f"{_value(claude, 'wall_clock_minutes'):.1f}",
                _value(claude, "requests"),
                _value(claude, "context_tokens"),
                _value(claude, "output_tokens"),
                _value(claude, "total_tokens"),
                _usd(claude),
                f"{_value(codex, 'wall_clock_minutes'):.1f}",
                _value(codex, "requests"),
                _value(codex, "context_tokens"),
                _value(codex, "output_tokens"),
                _value(codex, "total_tokens"),
                _usd(codex),
                f"{payload['wall_clock_minutes']:.1f}",
                sum(m["requests"] for m in by_model.values()),
                sum(m["context_tokens"] for m in by_model.values()),
                sum(m["output_tokens"] for m in by_model.values()),
                sum(
                    m.get("total_tokens", m["context_tokens"] + m["output_tokens"])
                    for m in by_model.values()
                ),
                f"{total_usd:.4f}" if total_usd is not None else "",
                payload["rates_version"],
                " ".join(coverage.get("harnesses_configured") or ["claude-code"]),
                " ".join(coverage.get("harnesses_observed") or ["claude-code"]),
                coverage.get("usage_coverage", "unknown"),
                coverage.get("attribution_coverage", "heuristic"),
                coverage.get("pricing_status", payload.get("pricing_status", "complete")),
            ]
        )
    index = target / "index.csv"
    with index.open("w", encoding="utf-8", newline="\n") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    return index
