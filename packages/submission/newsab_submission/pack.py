"""Closed-list archive assembly (plan §6.1).

``pack`` resolves the candidate page run exactly the way stage 8 does — same manifest
walk, same fingerprint recomputation, same article-set restoration — then writes a
deterministic ``tar.gz``: fixed metadata, lexical member order, envelope first.  Two
packs of the same closure with the same submission id and timestamp are byte-identical,
which is what lets a declared archive hash mean anything.
"""

from __future__ import annotations

import gzip
import io
import json
import secrets
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from newsab_publish.builder import ResolvedInputs, resolve_inputs
from newsab_publish.site_strings import SITE_LOCALES
from newsab_schema.common import LangText, normalize_lang
from newsab_schema.io import ArtifactError
from newsab_schema.models.publication import SponsorAttribution
from newsab_schema.paths import TopicPaths
from newsab_schema.store import load_corpus_run

from . import PACKAGE_VERSION, PROTOCOL_VERSION
from .closure import PlannedMember, manifest_subset_bytes, plan_members, sha256_bytes
from .envelope import (
    ENVELOPE_MEMBER,
    ArchiveMember,
    SubmissionDiagnostics,
    SubmissionEnvelope,
)


def new_submission_id() -> str:
    return f"SUB-{secrets.token_hex(8)}"


def _tar_info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.size = size
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    return info


def write_archive(
    out_path: Path, envelope_bytes: bytes, members: Sequence[tuple[str, bytes]]
) -> str:
    """Write the deterministic archive; returns its ``sha256:`` digest.

    The envelope is always the first entry so a streaming reader can refuse before
    consuming data members; everything else follows in lexical path order.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as raw:
        # filename="" keeps the sink's path out of the gzip header — the archive's
        # bytes must depend only on its contents, or the declared hash means nothing.
        with gzip.GzipFile(
            fileobj=raw, mode="wb", compresslevel=9, mtime=0, filename=""
        ) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tar:
                info = _tar_info(ENVELOPE_MEMBER, len(envelope_bytes))
                tar.addfile(info, io.BytesIO(envelope_bytes))
                for name, payload in sorted(members, key=lambda pair: pair[0]):
                    tar.addfile(_tar_info(name, len(payload)), io.BytesIO(payload))
    from newsab_schema.models.manifest import file_digest

    return file_digest(out_path)


def _closure_stage_runs(resolved: ResolvedInputs) -> dict[str, str]:
    return {
        pin.stage: pin.run_id for pin in resolved.pins if pin.stage != "scope"
    }


def page_locales(resolved: ResolvedInputs) -> tuple[str, ...]:
    """The site locales a page can be served in: those its title carries, site order."""
    present = {normalize_lang(lang) for lang in resolved.page.title.values}
    locales = tuple(loc for loc in SITE_LOCALES if loc in present)
    if not locales:
        raise ArtifactError(
            f"page title is written in {sorted(present)}, none of which the renderer "
            f"supports (supported: {list(SITE_LOCALES)})"
        )
    return locales


def pack(
    topics_root: str | Path,
    topic_id: str,
    out_path: str | Path,
    *,
    page_run_id: Optional[str] = None,
    operation: str = "create",
    prior_publication_id: Optional[str] = None,
    requested_locales: Optional[Sequence[str]] = None,
    sponsor: Optional[SponsorAttribution] = None,
    terms_version: str = "submission-terms-2",
    source_statement: Optional[LangText] = None,
    submission_id: Optional[str] = None,
    created_at: Optional[datetime] = None,
    toolkit_ref: Optional[str] = None,
) -> dict:
    """Assemble one archive; returns the pack report (ids, sizes, archive hash).

    ``requested_locales`` names the languages the site is asked to publish. Left as
    ``None`` it is derived from the page itself: every site locale the page title is
    written in, in the site's order. A page localized into two languages then asks for
    two, and one carried through every halo language asks for all of them — the trusted
    renderer (G2) refuses a locale the page cannot serve, so asking for the whole
    ``SITE_LOCALES`` set by default would refuse every partially localized page.
    """
    out_path = Path(out_path)
    submission_id = submission_id or new_submission_id()
    created_at = created_at or datetime.now(timezone.utc)
    sponsor = sponsor or SponsorAttribution(anonymous=True, display_name=None)
    source_statement = source_statement or LangText(
        text="The submitter attests the sources were collected as recorded.", lang="en"
    )

    common = dict(
        toolkit_version=PACKAGE_VERSION,
        toolkit_ref=toolkit_ref,
        submission_id=submission_id,
        created_at=created_at,
        operation=operation,
        prior_publication_id=prior_publication_id,
        topic_id=topic_id,
        sponsor=sponsor,
        terms_version=terms_version,
        source_statement=source_statement,
    )

    if operation == "withdraw":
        envelope = SubmissionEnvelope(**common)
        archive_hash = write_archive(out_path, _envelope_bytes(envelope), [])
        return _report(envelope, out_path, archive_hash, members=1, hash_only=0)

    paths = TopicPaths.for_topic(topics_root, topic_id)
    page_run_id = page_run_id or paths.active_run_id("editorial")
    if not page_run_id:
        raise ArtifactError(f"{topic_id} has no active editorial run and none was given")
    if requested_locales is not None:
        locales = tuple(dict.fromkeys(normalize_lang(loc) for loc in requested_locales))
        unsupported = [loc for loc in locales if loc not in SITE_LOCALES]
        if unsupported:
            raise ArtifactError(
                f"requested locales the renderer does not support: {unsupported} "
                f"(supported: {list(SITE_LOCALES)})"
            )
        if not locales:
            raise ArtifactError("requested locales must name at least one site locale")

    # Stage 8's own resolution: manifest walk, pin fingerprints, article restoration.
    resolved = resolve_inputs(topics_root, topic_id, page_run_id)
    if requested_locales is None:
        locales = page_locales(resolved)
    corpus_run = load_corpus_run(paths, _closure_stage_runs(resolved)["corpus"])
    planned = plan_members(
        paths,
        corpus_run,
        _closure_stage_runs(resolved),
        manifest_bytes=manifest_subset_bytes(paths, page_run_id),
        topics_by_article_bytes=resolved.topics_by_article_bytes,
        registry_bytes=resolved.source_registry_bytes,
    )

    table: list[ArchiveMember] = []
    payloads: list[tuple[str, bytes]] = []
    preview_fingerprints: dict[str, str] = {}
    for member in planned:
        payload = member.read()
        digest = sha256_bytes(payload)
        table.append(
            ArchiveMember(
                path=member.archive_path,
                sha256=digest,
                size_bytes=len(payload),
                kind=member.kind,
            )
        )
        if member.kind == "hash_only":
            preview_fingerprints[member.archive_path] = digest
        else:
            payloads.append((member.archive_path, payload))

    envelope = SubmissionEnvelope(
        **common,
        page_run_id=page_run_id,
        requested_locales=locales,
        run_closure=resolved.pins,
        members=tuple(table),
        diagnostics=SubmissionDiagnostics(preview_fingerprints=preview_fingerprints),
    )
    archive_hash = write_archive(out_path, _envelope_bytes(envelope), payloads)
    return _report(
        envelope,
        out_path,
        archive_hash,
        members=len(payloads) + 1,
        hash_only=len(preview_fingerprints),
    )


def _envelope_bytes(envelope: SubmissionEnvelope) -> bytes:
    payload = envelope.model_dump(mode="json", exclude_none=True)
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _report(
    envelope: SubmissionEnvelope,
    out_path: Path,
    archive_hash: str,
    *,
    members: int,
    hash_only: int,
) -> dict:
    return {
        "schema_version": "submission-pack-report-0.1.0",
        "protocol_version": PROTOCOL_VERSION,
        "submission_id": envelope.submission_id,
        "operation": envelope.operation,
        "topic_id": envelope.topic_id,
        "page_run_id": envelope.page_run_id,
        "archive": str(out_path),
        "archive_sha256": archive_hash,
        "archive_bytes": out_path.stat().st_size,
        "members": members,
        "hash_only_members": hash_only,
    }
