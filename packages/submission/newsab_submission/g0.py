"""G0 — archive safety (plan §7.3, §6.2 steps 2–3).

A streaming structural gate over the raw archive: sizes, counts, compression ratio,
path normalization, member types and the closed extension list are all enforced while
reading, before a single byte lands outside the throwaway work directory and long
before any schema, model or agent sees the content.  Everything here treats the
archive as hostile data; nothing is ever executed, imported or followed.
"""

from __future__ import annotations

import json
import re
import tarfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Optional

from .envelope import ENVELOPE_MEMBER, REGISTRY_MEMBER, TOPIC_ROOT
from .errors import SubmissionIssue, SubmissionRefused, refuse

#: Prototype caps.  Deliberately generous and deliberately not a product contract —
#: plan §10 forbids freezing quota numbers before P2's real-topic measurements; the
#: measured sizes feed P4's deployed limits, which live in deployment config.
@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 256 * 1024 * 1024
    max_total_uncompressed: int = 1024 * 1024 * 1024
    max_member_bytes: int = 256 * 1024 * 1024
    max_members: int = 20_000
    max_envelope_bytes: int = 8 * 1024 * 1024
    #: Uncompressed/compressed ceiling, only enforced past ``ratio_floor_bytes`` so a
    #: tiny well-compressed archive is not punished for being small.
    max_compression_ratio: float = 100.0
    ratio_floor_bytes: int = 1024 * 1024
    max_path_length: int = 300


ALLOWED_SUFFIXES = (".json", ".jsonl", ".yaml", ".yml", ".csv", ".md")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass
class G0Report:
    archive_bytes: int
    member_count: int = 0
    total_uncompressed: int = 0
    envelope_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "archive_bytes": self.archive_bytes,
            "member_count": self.member_count,
            "total_uncompressed": self.total_uncompressed,
            "envelope_bytes": self.envelope_bytes,
            "compression_ratio": (
                round(self.total_uncompressed / self.archive_bytes, 2)
                if self.archive_bytes
                else 0.0
            ),
        }


def _check_path(name: str, limits: ArchiveLimits) -> None:
    if len(name) > limits.max_path_length:
        raise refuse("G0", "G0_PATH_TOO_LONG", f"member path exceeds {limits.max_path_length} chars", name[:80])
    if "\\" in name or any(ord(ch) < 0x20 or ch == "\x7f" for ch in name):
        raise refuse("G0", "G0_PATH_INVALID", "member path carries a backslash or control character", name)
    pure = PurePosixPath(name)
    if pure.is_absolute():
        raise refuse("G0", "G0_PATH_TRAVERSAL", "member path is absolute", name)
    parts = pure.parts
    if not parts or any(part in (".", "..") for part in parts):
        raise refuse("G0", "G0_PATH_TRAVERSAL", "member path escapes the extraction root", name)
    for part in parts:
        if not _SEGMENT_RE.match(part):
            raise refuse("G0", "G0_PATH_INVALID", f"path segment {part!r} is outside the allowed character set", name)
    if name != ENVELOPE_MEMBER and name != REGISTRY_MEMBER and parts[0] != TOPIC_ROOT:
        raise refuse("G0", "G0_PATH_UNEXPECTED_ROOT", "member is outside the archive's fixed roots", name)
    if pure.suffix.lower() not in ALLOWED_SUFFIXES:
        raise refuse(
            "G0",
            "G0_EXTENSION_FORBIDDEN",
            f"member type {pure.suffix or '(none)'!r} is not accepted "
            "(no executables, scripts, HTML/CSS/JS or opaque blobs)",
            name,
        )


def _iter_members(archive: Path, limits: ArchiveLimits, dest: Optional[Path]) -> G0Report:
    report = G0Report(archive_bytes=archive.stat().st_size)
    if report.archive_bytes > limits.max_archive_bytes:
        raise refuse(
            "G0", "G0_ARCHIVE_TOO_LARGE",
            f"archive is {report.archive_bytes} bytes (limit {limits.max_archive_bytes})",
        )
    seen: set[str] = set()
    try:
        with open(archive, "rb") as raw, tarfile.open(fileobj=raw, mode="r|gz") as tar:
            for info in tar:
                report.member_count += 1
                if report.member_count > limits.max_members:
                    raise refuse("G0", "G0_TOO_MANY_MEMBERS", f"more than {limits.max_members} members")
                if not info.isreg():
                    raise refuse(
                        "G0", "G0_MEMBER_TYPE",
                        "only regular files are accepted (no symlinks, links, devices or directories)",
                        info.name,
                    )
                _check_path(info.name, limits)
                if info.name in seen:
                    raise refuse("G0", "G0_PATH_DUPLICATE", "member path appears twice", info.name)
                seen.add(info.name)
                if report.member_count == 1 and info.name != ENVELOPE_MEMBER:
                    raise refuse(
                        "G0", "G0_ENVELOPE_FIRST",
                        f"the first member must be {ENVELOPE_MEMBER}, got {info.name!r}",
                    )
                if info.name == ENVELOPE_MEMBER:
                    if report.member_count != 1:
                        raise refuse("G0", "G0_ENVELOPE_FIRST", "the envelope must be the first member")
                    if info.size > limits.max_envelope_bytes:
                        raise refuse("G0", "G0_ENVELOPE_TOO_LARGE", f"envelope claims {info.size} bytes")
                if info.size > limits.max_member_bytes:
                    raise refuse(
                        "G0", "G0_MEMBER_TOO_LARGE",
                        f"member claims {info.size} bytes (limit {limits.max_member_bytes})",
                        info.name,
                    )
                stream = tar.extractfile(info)
                if stream is None:
                    raise refuse("G0", "G0_MEMBER_UNREADABLE", "member carries no readable data", info.name)
                target = None
                if dest is not None:
                    target = dest / PurePosixPath(info.name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                consumed = 0
                sink = open(target, "wb") if target is not None else None
                try:
                    while True:
                        chunk = stream.read(1 << 20)
                        if not chunk:
                            break
                        consumed += len(chunk)
                        report.total_uncompressed += len(chunk)
                        if report.total_uncompressed > limits.max_total_uncompressed:
                            raise refuse(
                                "G0", "G0_TOTAL_TOO_LARGE",
                                f"uncompressed content exceeds {limits.max_total_uncompressed} bytes",
                            )
                        if (
                            report.total_uncompressed > limits.ratio_floor_bytes
                            and report.total_uncompressed
                            > limits.max_compression_ratio * report.archive_bytes
                        ):
                            raise refuse(
                                "G0", "G0_COMPRESSION_RATIO",
                                "uncompressed content exceeds "
                                f"{limits.max_compression_ratio}x the archive size",
                            )
                        if sink is not None:
                            sink.write(chunk)
                finally:
                    if sink is not None:
                        sink.close()
                if consumed != info.size:
                    raise refuse(
                        "G0", "G0_MEMBER_TRUNCATED",
                        f"member declared {info.size} bytes but carried {consumed}",
                        info.name,
                    )
                if info.name == ENVELOPE_MEMBER:
                    report.envelope_bytes = consumed
    except SubmissionRefused:
        raise
    except (tarfile.TarError, EOFError, OSError, ValueError) as exc:
        raise refuse("G0", "G0_ARCHIVE_UNREADABLE", f"not a readable tar.gz archive: {exc}") from exc
    if ENVELOPE_MEMBER not in seen:
        raise refuse("G0", "G0_ENVELOPE_MISSING", f"archive has no {ENVELOPE_MEMBER}")
    return report


def inspect_archive(archive: str | Path, limits: ArchiveLimits = ArchiveLimits()) -> G0Report:
    """Stream every check without writing anything to disk."""
    return _iter_members(Path(archive), limits, None)


def extract_archive(
    archive: str | Path, dest: str | Path, limits: ArchiveLimits = ArchiveLimits()
) -> G0Report:
    """Stream the same checks and materialize members under ``dest``.

    ``dest`` must be a fresh directory: extraction refuses to touch a non-empty one.
    Every parent directory and file is newly created; nothing is executable and no
    member can name a path outside ``dest`` (checked before any write).
    """
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise refuse("G0", "G0_DEST_NOT_EMPTY", f"extraction target is not empty: {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    return _iter_members(Path(archive), limits, dest)


def read_envelope_json(dest: Path) -> dict:
    """The extracted envelope as a plain JSON object; structural errors are G0's."""
    path = dest / ENVELOPE_MEMBER
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise refuse("G0", "G0_ENVELOPE_INVALID", f"envelope is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("magic") != "newsab-submission":
        raise refuse("G0", "G0_ENVELOPE_INVALID", "envelope does not declare a newsab-submission")
    return payload
