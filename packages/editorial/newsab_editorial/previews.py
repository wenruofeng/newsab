"""Which stage-6 previews exist, and what each one is — read off the repo's own facts.

Touchpoint 2 is the reviewer opening a preview.  Hunting the newest
``editorial/versions/<run>/preview.zh-CN.html`` down a file tree is a tax on the one human
step the chain cannot automate, so the listing is *derived* from facts the repo already
records: which run directories exist, what the manifest says about each run, and which run
the active selector points at.

This module only collects; it renders nothing.  The one surface that shows these runs is
the ``dev-serve`` dashboard, which serves each preview over http (`AGENTS.md` §4, "never
hand a human a file path").  The former ``preview_home.html`` file:// index is retired.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from newsab_schema.locales import HALO_LOCALES

try:  # PT is the repo's wall clock (report filenames, the user's day)
    from zoneinfo import ZoneInfo

    DISPLAY_TZ = ZoneInfo("America/Los_Angeles")
    DISPLAY_TZ_LABEL = "PT"
except Exception:  # pragma: no cover - no tzdata on this machine
    DISPLAY_TZ = timezone.utc
    DISPLAY_TZ_LABEL = "UTC"

#: Which language each rendered file is, and what to call its button: every halo locale
#: (`newsab_schema.locales.HALO_LOCALES`) by its own endonym, no locale singled out.  A
#: reviewer reading Japanese is no less the reviewer than one reading Chinese, so the
#: label for their language is not a special case here.  Order is the halo's own.
LANG_LABELS: dict[str, str] = {entry.locale: entry.endonym for entry in HALO_LOCALES}
LANG_ORDER: tuple[str, ...] = tuple(entry.locale for entry in HALO_LOCALES) + ("",)

STATUS_LABELS: dict[str, str] = {
    "completed": "完成",
    "stopped": "中止",
    "no_op": "无变更",
}


@dataclass
class PreviewRun:
    """One run directory that contains at least one rendered preview."""

    topic_id: str
    stage: str
    run_id: str | None  # None for a pre-versioning preview (e.g. `qa/preview.html`)
    dir_label: str  # what to show when there is no run_id
    files: dict[str, Path] = field(default_factory=dict)  # lang -> file
    when: datetime = datetime.fromtimestamp(0, tz=timezone.utc)
    when_is_exact: bool = False  # True when it came from the manifest, not from mtime
    status: str = ""
    model_id: str = ""
    active: bool = False
    page_title: str = ""
    angle_count: int | None = None


@dataclass
class TopicPreviews:
    topic_id: str
    title: str
    runs: list[PreviewRun]  # newest first


def _read_manifest(manifest_file: Path) -> dict[str, dict]:
    """run_id -> the manifest entry, last line wins.

    Parsed as raw JSON rather than through ``ManifestEntry``: the index must still render
    when one legacy line no longer validates against the current model.  It only reads
    display fields, never audits.
    """
    entries: dict[str, dict] = {}
    if not manifest_file.exists():
        return entries
    for line in manifest_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        run_id = payload.get("run_id")
        if run_id:
            entries[str(run_id)] = payload
    return entries


def _localized(value: object, prefer: tuple[str, ...] = ("en",)) -> str:
    """Pull a display string out of a `{values: {lang: text}}` block.

    ``prefer`` is the caller's reading order — the topic's own ``review_locale`` where
    there is one, the English pivot otherwise.  Never a fixed language: this index is
    read by whoever is reviewing, and which language that is, the manifest says.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        values = value.get("values") if isinstance(value.get("values"), dict) else value
        if isinstance(values, dict):
            for lang in prefer:
                text = values.get(lang)
                if isinstance(text, str) and text:
                    return text
            for text in values.values():
                if isinstance(text, str) and text:
                    return text
    return ""


def _parse_timestamp(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _lang_of(preview_file: Path) -> str:
    """`preview.zh-CN.html` -> `zh-CN`; `preview.html` -> `` (legacy, language unstated)."""
    name = preview_file.name
    middle = name[len("preview") : -len(".html")]
    return middle.lstrip(".")


def _preview_dirs(topic_dir: Path) -> list[Path]:
    found = {p.parent for p in topic_dir.glob("*/versions/*/preview*.html")}
    found |= {p.parent for p in topic_dir.glob("*/preview*.html")}
    return sorted(found)


def collect_topics(topics_root: Path) -> list[TopicPreviews]:
    """Every topic that has at least one rendered preview, newest topic first."""
    topics: list[TopicPreviews] = []
    for topic_dir in sorted(topics_root.iterdir()):
        if not (topic_dir / "topic_manifest.yaml").is_file():
            continue
        run_dirs = _preview_dirs(topic_dir)
        if not run_dirs:
            continue

        manifest = _read_manifest(topic_dir / "manifest" / "manifest.jsonl")
        active: dict[str, str] = {}
        active_file = topic_dir / "manifest" / "active.json"
        if active_file.exists():
            try:
                loaded = json.loads(active_file.read_text(encoding="utf-8"))
                active = {k: str(v) for k, v in loaded.items() if v}
            except (json.JSONDecodeError, OSError, AttributeError):
                active = {}

        title, prefer = _topic_display(topic_dir)
        runs = [_build_run(topic_dir, d, manifest, active, prefer) for d in run_dirs]
        runs.sort(key=lambda r: (r.when, r.run_id or ""), reverse=True)
        topics.append(
            TopicPreviews(
                topic_id=topic_dir.name,
                title=title,
                runs=runs,
            )
        )
    topics.sort(key=lambda t: t.runs[0].when, reverse=True)
    return topics


def _topic_display(topic_dir: Path) -> tuple[str, tuple[str, ...]]:
    """This topic's title, and the reading order every other string here follows.

    Both come from the manifest in one read: the reading order is ``review_locale`` then
    the English pivot, so the index speaks to whoever this topic's touchpoint two
    belongs to.  A hand-rolled scan of the `title:` block would drift from the schema;
    ``yaml`` is already a dependency, and a topic whose manifest does not parse still
    deserves a row (its id) rather than vanishing from the index.
    """
    manifest_file = topic_dir / "topic_manifest.yaml"
    try:
        from newsab_schema.io import load_yaml_text

        payload = load_yaml_text(manifest_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return topic_dir.name, ("en",)
    prefer = tuple(
        dict.fromkeys(x for x in (payload.get("review_locale"), "en") if isinstance(x, str))
    )
    return _localized(payload.get("title"), prefer) or topic_dir.name, prefer


def _build_run(
    topic_dir: Path,
    run_dir: Path,
    manifest: dict[str, dict],
    active: dict[str, str],
    prefer: tuple[str, ...] = ("en",),
) -> PreviewRun:
    versioned = run_dir.parent.name == "versions"
    stage = run_dir.parent.parent.name if versioned else run_dir.name
    run_id = run_dir.name if versioned else None

    run = PreviewRun(
        topic_id=topic_dir.name,
        stage=stage,
        run_id=run_id,
        dir_label=str(run_dir.relative_to(topic_dir)),
    )
    for preview_file in sorted(run_dir.glob("preview*.html")):
        run.files[_lang_of(preview_file)] = preview_file

    entry = manifest.get(run_id or "", {})
    when = _parse_timestamp(entry.get("timestamp"))
    if when is not None:
        run.when, run.when_is_exact = when, True
    else:
        newest = max(f.stat().st_mtime for f in run.files.values())
        run.when = datetime.fromtimestamp(newest, tz=timezone.utc)
    run.status = str(entry.get("status") or "")
    run.model_id = str(entry.get("model_id") or "")
    run.active = bool(run_id) and active.get(stage) == run_id

    page_file = run_dir / "page.json"
    if page_file.exists():
        try:
            page = json.loads(page_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            page = {}
        run.page_title = _localized(page.get("title"), prefer)
        angles = page.get("angles")
        if isinstance(angles, list):
            run.angle_count = len(angles)
    return run


def stamp(when: datetime) -> str:
    """A run's time in the repo's wall clock — the reviewer reads PT, not UTC."""
    return when.astimezone(DISPLAY_TZ).strftime("%m-%d %H:%M")
