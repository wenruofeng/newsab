"""``python -m newsab_corpus registry …`` — read and maintain ``sources/registry.yaml``.

The registry is cross-topic and only ever grows, so by the time a collector opens it, it
holds mostly outlets from other topics in other languages.  Reading the whole file to find
the four Kenyan outlets in it is the wrong shape of work: a scoped topic already knows its
languages and countries, and a collector that has just landed on an unfamiliar homepage
knows the host it wants to look up.  ``registry find`` answers both with a filter, so what
enters an agent's context is the handful of entries it will actually use.

``registry check`` is the other half of that bargain.  Since 2026-08-22 nobody reviews this
file on a schedule — the agent that meets an outlet is its author of record — so the
quality rules have to be runnable rather than remembered.

``registry set-channel`` exists because channel knowledge is the one part of an entry that
is *measured* rather than judged: a collector establishes it mid-run, and hand-editing a
sorted machine-written YAML file mid-run is how a run loses an hour.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

from newsab_schema.models.corpus import SourceEntry, SourceRegistry
from newsab_schema.sources import registry_entry_problems
from newsab_schema.store import load_registry, save_registry

#: Where an agent invoked from the repo root finds the registry without being told.
DEFAULT_REGISTRY = "sources/registry.yaml"


def _host(url: str) -> str:
    return url.split("//", 1)[-1].partition("/")[0].lower().removeprefix("www.")


def _matches(entry: SourceEntry, args: argparse.Namespace) -> bool:
    if args.country and entry.country.upper() not in {c.upper() for c in args.country}:
        return False
    if args.lang and entry.lang not in set(args.lang):
        return False
    if args.category and entry.category.value not in set(args.category):
        return False
    if args.beat_scope and entry.beat_scope not in set(args.beat_scope):
        return False
    if args.host:
        wanted = _host(args.host if "//" in args.host else f"//{args.host}")
        if wanted not in _host(entry.url) and _host(entry.url) not in wanted:
            return False
    if args.id and not any(fragment in entry.id for fragment in args.id):
        return False
    if args.has_channel and entry.channel.search_channel is None:
        return False
    if args.missing_channel and entry.channel.search_channel is not None:
        return False
    return True


def _brief(entry: SourceEntry) -> str:
    kind = f"{entry.category.value}/{entry.beat_scope}"
    return f"{entry.id:26} {entry.country}/{entry.lang:6} {kind:17} {entry.url}"


def _full(entry: SourceEntry) -> list[str]:
    names = " · ".join(
        dict.fromkeys(
            v for k, v in entry.name.values.items() if k in (entry.lang, "zh-CN", "en")
        )
    )
    out = [_brief(entry), f"    {names}"]
    for lang in ("zh-CN", "en"):
        out.append(f"    notes[{lang}]: {entry.notes.values.get(lang, '')}")
    channel = entry.channel
    checked = channel.checked_at.isoformat() if channel.checked_at else "never checked"
    out.append(f"    channel: {channel.status} ({checked})")
    for label, value in (
        ("search", channel.search_channel),
        ("fetch", channel.fetch_notes),
        ("rate", channel.rate_limit),
        ("origin_field", channel.origin_field),
    ):
        if value:
            out.append(f"      {label}: {value}")
    return out


def cmd_find(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    hits = [entry for entry in registry.sources if _matches(entry, args)]
    for entry in hits:
        if args.brief:
            print(_brief(entry))
        else:
            print("\n".join(_full(entry)))
    print(f"-- {len(hits)}/{len(registry.sources)} outlets in {args.registry}", file=sys.stderr)
    # An empty result is a fact about the registry, not a failure: it is exactly what
    # "nobody has collected this country before" looks like.
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    today = date.fromisoformat(args.today) if args.today else None
    flagged = 0
    for entry in registry.sources:
        problems = registry_entry_problems(entry, today=today)
        if not problems:
            continue
        flagged += 1
        print(entry.id)
        for problem in problems:
            print(f"  - {problem}")
    total = len(registry.sources)
    unmeasured = sum(1 for e in registry.sources if e.channel.search_channel is None)
    print(f"-- {total - flagged}/{total} entries clean", file=sys.stderr)
    print(
        f"-- {unmeasured}/{total} have no recorded search channel "
        f"(`registry find --missing-channel`); that is a gap, not a defect",
        file=sys.stderr,
    )
    return 1 if flagged else 0


def cmd_set_channel(args: argparse.Namespace) -> int:
    path = Path(args.registry)
    registry = load_registry(path)
    entry = registry.get(args.source_id)
    if entry is None:
        print(
            f"{args.source_id!r} is not registered yet; an outlet enters the registry "
            "through a staged article's registration block, not through set-channel",
            file=sys.stderr,
        )
        return 1

    # ``fetch_notes`` is accumulated knowledge, not a slot: the huanqiu entry alone holds
    # seven measured facts one worker's overwrite once nearly destroyed.  A new note is
    # therefore *appended* as a dated line; replacing the accumulation is a separate,
    # deliberate flag.
    fetch_notes = args.fetch_notes
    if (
        fetch_notes is not None
        and not args.replace_fetch_notes
        and entry.channel.fetch_notes
    ):
        stamp = args.checked_at or date.today().isoformat()
        fetch_notes = f"{entry.channel.fetch_notes}\n[{stamp}] {fetch_notes}"
    updates = {
        "search_channel": args.search_channel,
        "fetch_notes": fetch_notes,
        "rate_limit": args.rate_limit,
        "origin_field": args.origin_field,
        "status": args.status,
    }
    channel = entry.channel.model_copy(
        update={k: v for k, v in updates.items() if v is not None}
    )
    # Recording *when* is not optional: a channel note with no date is a claim about a
    # website that may have been redesigned twice since.
    channel = channel.model_copy(
        update={"checked_at": date.fromisoformat(args.checked_at) if args.checked_at else date.today()}
    )
    updated = entry.model_copy(update={"channel": channel})
    registry = SourceRegistry.model_validate(
        {
            "registry_version": registry.registry_version,
            "updated_at": registry.updated_at,
            "sources": [updated if s.id == entry.id else s for s in registry.sources],
        }
    )
    save_registry(path, registry)
    print("\n".join(_full(updated)))
    return 0


def build_registry_parser(sub: argparse._SubParsersAction) -> None:
    registry_flag = argparse.ArgumentParser(add_help=False)
    registry_flag.add_argument("--registry", default=DEFAULT_REGISTRY)

    p = sub.add_parser(
        "registry",
        parents=[registry_flag],
        help="read and maintain the cross-topic outlet registry",
    )
    inner = p.add_subparsers(dest="registry_command", required=True)

    f = inner.add_parser(
        "find",
        parents=[registry_flag],
        help="print the outlets matching a filter, instead of reading the whole file",
    )
    f.add_argument("--country", action="append", help="ISO alpha-2; repeatable")
    f.add_argument("--lang", action="append", help="BCP-47; repeatable")
    f.add_argument("--category", action="append", choices=["serious", "other"])
    f.add_argument("--beat-scope", action="append", choices=["general", "vertical"])
    f.add_argument("--host", help="match by homepage host, e.g. smm.cn")
    f.add_argument("--id", action="append", help="substring of source_id; repeatable")
    f.add_argument(
        "--has-channel", action="store_true", help="only outlets with a recorded search channel"
    )
    f.add_argument(
        "--missing-channel",
        action="store_true",
        help="only outlets nobody has worked out how to search yet",
    )
    f.add_argument("--brief", action="store_true", help="one line per outlet")
    f.set_defaults(func=cmd_find)

    c = inner.add_parser(
        "check", parents=[registry_flag], help="audit every entry against the quality rules"
    )
    c.add_argument("--today", help="YYYY-MM-DD, for reproducible staleness checks")
    c.set_defaults(func=cmd_check)

    s = inner.add_parser(
        "set-channel",
        parents=[registry_flag],
        help="record what you measured about an outlet's collection channel",
    )
    s.add_argument("source_id")
    s.add_argument("--search-channel", help="URL template with {query} / {page}")
    s.add_argument(
        "--fetch-notes",
        help=(
            "encoding quirks, body selector, browser needed? Appended to the existing "
            "notes as a dated line; the accumulation is other workers' measured facts"
        ),
    )
    s.add_argument(
        "--replace-fetch-notes",
        action="store_true",
        help=(
            "overwrite the accumulated fetch notes with --fetch-notes instead of "
            "appending; only when the old notes are measured to be wrong, not merely old"
        ),
    )
    s.add_argument("--rate-limit", help="observed limit, in words a human can act on")
    s.add_argument("--origin-field", help="the page/API field that settles reporting origin")
    s.add_argument("--status", choices=["ok", "discovery_blocked", "ip_blocked", "unknown"])
    s.add_argument("--checked-at", help="YYYY-MM-DD; defaults to today")
    s.set_defaults(func=cmd_set_channel)


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin wrapper
    parser = argparse.ArgumentParser(prog="newsab-registry")
    build_registry_parser(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(argv)
    return args.func(args)
