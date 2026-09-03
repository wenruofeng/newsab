"""Append-only topic artifact and manifest storage (§3.2, AGENTS.md §7).

Stage implementations use this module instead of open-coded JSONL appends.  It validates
the existing chain under an advisory lock, performs one append, fsyncs it, and only then
atomically advances the mutable active-run selector.

What the manifest asserts changed in the R-4 refactor.  It used to record
``{topic-relative path: sha256}`` and re-check those bytes forever, which made any
*legitimate* evolution of a path — a source added mid-collection under D19, a corpus
extended after the fact — indistinguishable from tampering.  It now records the **content
set** a run produced: ``stage`` + ``run_id`` name the run, ``output_set_hash`` fingerprints
what it contains, and ``inputs`` names the upstream runs by ID.  Verification asks whether
each run's declared set can still be restored with the same fingerprint.  Byte hashes are
still recorded, as historical evidence of what a run touched, and are no longer re-checked.
The mutable ``active`` pointer never enters a hash.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator, Mapping, Optional

from .io import ArtifactError, dump_record, read_jsonl
from .models.manifest import CorrectionMapping, ManifestEntry, content_digest, file_digest
from .paths import STAGE_NAMES, TopicPaths


def topic_relative(paths: TopicPaths, path: str | Path) -> str:
    """Return a stable POSIX key below the topic root, rejecting outside paths."""
    candidate = Path(path).resolve()
    try:
        return candidate.relative_to(paths.root.resolve()).as_posix()
    except ValueError as exc:
        raise ArtifactError(f"artifact is outside topic root: {candidate}") from exc


def artifact_hashes(paths: TopicPaths, files: Iterable[str | Path]) -> dict[str, str]:
    """Hash files under a topic, keyed by their topic-relative paths."""
    result: dict[str, str] = {}
    for raw in files:
        path = Path(raw)
        if not path.is_file():
            raise ArtifactError(f"artifact does not exist or is not a file: {path}")
        result[topic_relative(paths, path)] = file_digest(path)
    return dict(sorted(result.items()))


def tree_hashes(paths: TopicPaths, directory: str | Path) -> dict[str, str]:
    """Hash every file below a run directory in lexical relative-path order."""
    root = Path(directory)
    if not root.is_dir():
        raise ArtifactError(f"artifact run directory does not exist: {root}")
    return artifact_hashes(paths, sorted(path for path in root.rglob("*") if path.is_file()))


@contextmanager
def _locked_append(path: Path) -> Iterator[object]:
    """Open a JSONL log for append while holding an exclusive advisory lock."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield handle
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_set_hash(
    paths: TopicPaths,
    stage: str,
    run_id: str,
    *,
    hash_only: Mapping[str, str] | None = None,
) -> str:
    """Fingerprint the content set one run produced.

    A corpus run is a *set of articles*, so its fingerprint is the ``set_hash`` of its
    :class:`~newsab_schema.models.corpus.CorpusRun` record — restorable from the
    append-only store even after the store has grown.  Every other stage writes files into
    its run directory, so its fingerprint is the digest of that directory's file hashes.
    Either way the key is the run, never a path that content is allowed to move between.

    ``hash_only`` names topic-relative files that legitimately have no bytes here and
    contributes their recorded hashes to the set instead.  A submission archive travels
    that way: the page run's rendered previews are recorded by hash and never shipped,
    because the site rebuilds every displayable surface with its own renderer.  The
    fingerprint is still the run's full declared set, so an absent member cannot be
    quietly dropped from the pin.
    """
    run_dir = paths.stage_run_dir(stage, run_id)
    if not run_dir.is_dir():
        raise ArtifactError(f"run directory is missing: {run_dir}")
    overlaid: dict[str, str] = {}
    if hash_only:
        prefix = run_dir.relative_to(paths.root).as_posix() + "/"
        overlaid = {
            key: value for key, value in hash_only.items() if key.startswith(prefix)
        }
    if stage == "corpus":
        if overlaid:
            raise ArtifactError(
                f"{run_id}: a corpus run has no hash-only members"
            )
        from .store import load_corpus_run, restore_set

        run = load_corpus_run(paths, run_id)
        _, errors = restore_set(paths, run)
        if errors:
            raise ArtifactError(
                f"corpus run {run_id} is no longer restorable: " + "; ".join(errors)
            )
        return run.set_hash
    hashes = tree_hashes(paths, run_dir)
    for key, value in overlaid.items():
        if key in hashes:
            raise ArtifactError(
                f"{run_id}: {key} is both on disk and declared hash-only"
            )
        hashes[key] = value
    return content_digest(dict(sorted(hashes.items())))


#: What may legitimately travel as a recorded hash instead of bytes: rendered surfaces.
#: A submission archive refuses to carry contributor HTML/CSS/JS at all (the site rebuilds
#: every displayable surface with its own renderer), so the page run's previews reach the
#: operator as hashes.  Nothing else may: an overlay that could name ``page.json`` would
#: let a run drop its own evidence and still fingerprint as declared.
HASH_ONLY_SUFFIXES = (".html", ".htm", ".css", ".js", ".mjs")

#: Written at an import namespace's root by the trusted importer, never by a contributor
#: (the archive's closed member table cannot name a path outside ``topic/``).
HASH_ONLY_FILE = "hash_only.json"


def load_hash_only(topics_root: str | Path, topic_id: str) -> dict[str, str]:
    """The overlay a namespace declares for one topic, or ``{}``.

    An imported submission is the only tree that has one, and every command pointed at
    such a tree needs it — so it lives beside the namespace instead of being passed in by
    each caller that happens to remember.  Absent file, absent topic and malformed
    entries are all "no overlay"; a *well-formed* entry naming something other than a
    rendered surface is a refusal, because that is the only shape that could hide
    evidence rather than a re-renderable page.
    """
    path = Path(topics_root).parent / HASH_ONLY_FILE
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArtifactError(f"{path}: unreadable hash-only overlay: {exc}") from exc
    if not isinstance(payload, dict):
        raise ArtifactError(f"{path}: hash-only overlay must be a JSON object")
    entries = payload.get(topic_id)
    if entries is None:
        return {}
    if not isinstance(entries, dict):
        raise ArtifactError(f"{path}: hash-only overlay for {topic_id} must be an object")
    overlay: dict[str, str] = {}
    for key, value in entries.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ArtifactError(f"{path}: hash-only overlay has a non-string entry")
        parts = PurePosixPath(key).parts
        if not parts or PurePosixPath(key).is_absolute() or ".." in parts or "\\" in key:
            raise ArtifactError(f"{path}: hash-only path escapes the topic root: {key!r}")
        if PurePosixPath(key).suffix.lower() not in HASH_ONLY_SUFFIXES:
            raise ArtifactError(
                f"{path}: only a rendered surface may travel by hash, not {key!r}"
            )
        overlay[key] = value
    return overlay


def manifest_entry_fingerprint(
    paths: TopicPaths,
    entry: ManifestEntry,
    *,
    verify_output_bytes: bool = True,
    hash_only: Mapping[str, str] | None = None,
) -> str:
    """Return one manifest run's publication-grade artifact fingerprint.

    New versioned stages already carry ``output_set_hash`` and are restored through
    :func:`run_set_hash`.  Legacy deterministic analysis runs predate that field and pin
    a closed ``output_hashes`` map instead.  Stage 8 still needs one qualified digest for
    those runs, and—unlike routine manifest checking—it must confirm that the exact
    analysis bytes still exist before publication.  Keeping this compatibility rule here
    avoids each bundle builder inventing a subtly different fallback.
    """
    if entry.topic_id != paths.topic_id:
        raise ArtifactError(
            f"manifest entry belongs to {entry.topic_id}, not topic {paths.topic_id}"
        )
    # One overlay covers a whole closure, so keep only the members that name this run.
    # A run nothing was declared absent from must fingerprint exactly as it always did.
    overlaid: dict[str, str] = {}
    if hash_only and entry.stage is not None and entry.stage != "corpus":
        prefix = (
            paths.stage_run_dir(entry.stage, entry.run_id)
            .relative_to(paths.root)
            .as_posix()
            + "/"
        )
        overlaid = {
            key: value for key, value in hash_only.items() if key.startswith(prefix)
        }
    if entry.output_set_hash is not None:
        actual = run_set_hash(
            paths, entry.stage, entry.run_id, hash_only=overlaid or None
        )
        if actual != entry.output_set_hash:
            raise ArtifactError(
                f"{entry.run_id}: declared output_set_hash {entry.output_set_hash} "
                f"but the run fingerprints as {actual}"
            )
        return actual
    if overlaid:
        # A legacy output_hashes run re-checks named bytes, so an absent member has
        # nowhere to be accounted for.  Refuse rather than fingerprint a smaller set.
        raise ArtifactError(
            f"{entry.run_id}: hash-only members are only supported for set-hash runs"
        )
    if not entry.output_hashes:
        raise ArtifactError(f"{entry.run_id}: run has no fingerprintable outputs")
    if verify_output_bytes:
        for relative, expected in sorted(entry.output_hashes.items()):
            # Manifest keys are data; refuse any that would escape the topic root
            # before this publication-grade check digests the file it names.
            parts = PurePosixPath(relative).parts
            if not parts or PurePosixPath(relative).is_absolute() or ".." in parts or "\\" in relative:
                raise ArtifactError(
                    f"{entry.run_id}: output path escapes the topic root: {relative!r}"
                )
            target = paths.root / relative
            if not target.is_file():
                raise ArtifactError(f"{entry.run_id}: output is missing: {relative}")
            actual = file_digest(target)
            if actual != expected:
                raise ArtifactError(
                    f"{entry.run_id}: output changed: {relative} "
                    f"({expected} != {actual})"
                )
    return content_digest(dict(sorted(entry.output_hashes.items())))


def load_manifest(paths: TopicPaths) -> list[ManifestEntry]:
    return read_jsonl(paths.manifest, ManifestEntry) if paths.manifest.exists() else []


def append_manifest(
    paths: TopicPaths,
    entry: ManifestEntry,
    *,
    activate_stage: Optional[str] = None,
) -> Path:
    """Append one entry and optionally advance a stage selector.

    The declared ``output_set_hash`` is recomputed inside the manifest lock, closing the gap
    in which another writer could alter the run between the producer computing it and the
    append landing.  Later tampering is caught by rerunning :func:`verify_manifest`, which
    re-derives the same fingerprint from the run.
    """
    if entry.topic_id != paths.topic_id:
        raise ArtifactError(
            f"manifest entry belongs to {entry.topic_id}, not topic {paths.topic_id}"
        )
    if activate_stage is not None:
        run_dir = paths.stage_run_dir(activate_stage, entry.run_id)
        if not run_dir.is_dir():
            raise ArtifactError(f"cannot activate missing {activate_stage} run: {run_dir}")
        if entry.stage is not None and entry.stage != activate_stage:
            raise ArtifactError(
                f"entry declares stage {entry.stage!r} but activates {activate_stage!r}"
            )

    with _locked_append(paths.manifest) as handle:
        handle.seek(0)
        entries: list[ManifestEntry] = []
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                entries.append(ManifestEntry.model_validate_json(line))
            except Exception as exc:
                raise ArtifactError(f"{paths.manifest}:{lineno}: invalid manifest entry — {exc}") from exc
        if any(old.run_id == entry.run_id for old in entries):
            raise ArtifactError(f"duplicate manifest run_id: {entry.run_id}")
        known = {old.run_id for old in entries}
        unknown_inputs = sorted(set(entry.inputs) - known)
        if unknown_inputs:
            raise ArtifactError(
                f"{entry.run_id} declares upstream runs absent from the manifest: {unknown_inputs}"
            )
        if entry.output_set_hash is not None:
            actual = run_set_hash(paths, entry.stage, entry.run_id)
            if actual != entry.output_set_hash:
                raise ArtifactError(
                    f"{entry.run_id}: declared output_set_hash {entry.output_set_hash} "
                    f"but the run fingerprints as {actual}"
                )
        handle.seek(0, os.SEEK_END)
        handle.write(dump_record(entry) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    if activate_stage is not None:
        paths.activate(activate_stage, entry.run_id)
    return paths.manifest


def verify_manifest(paths: TopicPaths) -> list[str]:
    """Return integrity errors for the append-only chain and every run it declares.

    What is checked, and what deliberately is not (R-4):

    * every run that declared an ``output_set_hash`` still restores to that fingerprint —
      for a corpus run this means every article it referenced is still findable at the
      content it pinned, even though the store has since grown;
    * every ``inputs`` edge points at a run this manifest knows;
    * the ``active`` selector points at runs that exist.

    ``input_hashes`` / ``output_hashes`` are *not* re-checked.  They record what a run
    touched, which stays true; they are not a promise that a path keeps those bytes, which
    would make every legitimate addition look like tampering.
    """
    errors: list[str] = []
    try:
        entries = load_manifest(paths)
    except ArtifactError as exc:
        return [str(exc)]
    seen: set[str] = set()
    for entry in entries:
        if entry.run_id in seen:
            errors.append(f"duplicate manifest run_id: {entry.run_id}")
        seen.add(entry.run_id)
        for upstream in entry.inputs:
            if upstream not in seen:
                errors.append(
                    f"{entry.run_id}: upstream run {upstream} is absent from (or later than) "
                    "this manifest"
                )
        if entry.output_set_hash is None:
            continue
        try:
            actual = run_set_hash(paths, entry.stage, entry.run_id)
        except ArtifactError as exc:
            errors.append(f"{entry.run_id}: {exc}")
            continue
        if actual != entry.output_set_hash:
            errors.append(
                f"{entry.run_id}: output set changed — declared {entry.output_set_hash}, "
                f"now {actual}"
            )
    if paths.active_versions.exists():
        try:
            active = json.loads(paths.active_versions.read_text(encoding="utf-8"))
            if not isinstance(active, dict):
                raise ValueError("top level is not an object")
            for stage, run_id in active.items():
                if stage not in STAGE_NAMES:
                    errors.append(f"active selector has unknown stage: {stage}")
                    continue
                if run_id not in seen:
                    errors.append(f"active {stage} run absent from manifest: {run_id}")
                elif not paths.stage_run_dir(stage, run_id).is_dir():
                    errors.append(f"active {stage} run directory is missing: {run_id}")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"invalid active selector {paths.active_versions}: {exc}")
    if paths.corrections.exists():
        try:
            corrections = read_jsonl(paths.corrections, CorrectionMapping)
        except ArtifactError as exc:
            errors.append(str(exc))
            corrections = []
        corrected: set[tuple[str, str, Optional[str]]] = set()
        for correction in corrections:
            key = (
                correction.superseded.run_id,
                correction.superseded.path,
                correction.superseded.record_id,
            )
            if key in corrected:
                errors.append(f"duplicate direct correction for {key}")
            corrected.add(key)
            for ref in (correction.superseded, correction.replacement):
                if ref.run_id not in seen:
                    errors.append(
                        f"{correction.correction_id}: run {ref.run_id} absent from manifest"
                    )
                path = paths.root / ref.path
                if not path.is_file() or file_digest(path) != ref.sha256:
                    errors.append(
                        f"{correction.correction_id}: missing or changed artifact {ref.path}"
                    )
                elif ref.record_id is not None and not _record_exists(path, ref.record_id):
                    errors.append(
                        f"{correction.correction_id}: record {ref.record_id} absent from {ref.path}"
                    )
    return errors


def _record_exists(path: Path, record_id: str) -> bool:
    """Look for an ID as a top-level JSON/JSONL value without guessing its field name."""
    try:
        payloads = (
            [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
            if path.suffix == ".jsonl"
            else [json.loads(path.read_text(encoding="utf-8"))]
        )
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return any(isinstance(payload, dict) and record_id in payload.values() for payload in payloads)


def append_correction(paths: TopicPaths, correction: CorrectionMapping) -> Path:
    """Validate and append one correction link; never changes either artifact."""
    if correction.topic_id != paths.topic_id:
        raise ArtifactError(
            f"correction belongs to {correction.topic_id}, not topic {paths.topic_id}"
        )
    manifest_run_ids = {entry.run_id for entry in load_manifest(paths)}
    for ref in (correction.superseded, correction.replacement):
        if ref.run_id not in manifest_run_ids:
            raise ArtifactError(f"correction references run absent from manifest: {ref.run_id}")
        path = paths.root / ref.path
        if not path.is_file() or file_digest(path) != ref.sha256:
            raise ArtifactError(f"correction artifact is missing or hash changed: {ref.path}")
        if ref.record_id is not None and not _record_exists(path, ref.record_id):
            raise ArtifactError(f"record {ref.record_id} is absent from {ref.path}")

    key = (
        correction.superseded.run_id,
        correction.superseded.path,
        correction.superseded.record_id,
    )
    with _locked_append(paths.corrections) as handle:
        handle.seek(0)
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                old = CorrectionMapping.model_validate_json(line)
            except Exception as exc:
                raise ArtifactError(f"{paths.corrections}:{lineno}: invalid correction — {exc}") from exc
            old_key = (old.superseded.run_id, old.superseded.path, old.superseded.record_id)
            if old.correction_id == correction.correction_id:
                raise ArtifactError(f"duplicate correction_id: {correction.correction_id}")
            if old_key == key:
                raise ArtifactError(f"superseded reference already has a correction: {key}")
        handle.seek(0, os.SEEK_END)
        handle.write(dump_record(correction) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return paths.corrections
