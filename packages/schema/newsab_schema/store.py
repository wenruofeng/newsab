"""The append-only article store and the corpus-run snapshot (R-2).

§3.2 says records are immutable.  That was once implemented as *no file on
disk may ever change*, which collides with two things the project also decided: the source
frame is open (D19) and a corpus can be extended after the fact.  Every collision ended the
same way — a check failed and the user had to rule on it.

So immutability moved down one level.  What is frozen is **the set of content a run
referenced**, not the state of a directory:

* ``corpus/articles/`` is one append-only store keyed by content-addressed ``article_id``;
* a build writes a :class:`~newsab_schema.models.corpus.CorpusRun` — the members it saw,
  each member's content hash, the cluster assignment, and the fingerprint of the whole set;
* downstream stages cite a ``run_id``; a reviewer restores the set from the run record
  rather than from whatever the directory holds today.

Adding an article is then: one new file, annotate that one article, re-run the
deterministic layers, mint a new run.  Every existing annotation stands.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from .io import ArtifactError, read_yaml, write_json, write_yaml
from .models.corpus import (
    Article,
    CorpusRun,
    SourceRegistry,
    WithdrawnArticle,
    article_content_hash,
    article_sentence_hash,
)
from .paths import TopicPaths

#: What a :func:`put_article` did, and — for the two kinds of change — whether any
#: sentence anchor into the article moved.  ``revised`` is a record that changed while its
#: sentence set did not: a ``splitter_version`` bump, an ``origin`` relabel, a corrected
#: ``access_level``.  Its previous bytes are archived exactly like a ``superseded``, so a
#: run that pinned the old content hash still restores, but every existing annotation
#: still resolves and none of them needs redoing.  Only ``superseded`` means the text a
#: ``{article_id}:P{n}:S{n}`` points at is no longer the same.
PutResult = Literal["new", "unchanged", "revised", "superseded"]


# --- the article store -----------------------------------------------------------------


def _write_article(path: Path, article: Article) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            article.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def read_article(path: Path) -> Article:
    try:
        return Article.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ArtifactError(f"{path}: Article invalid — {exc}") from exc


def store_articles(paths: TopicPaths) -> dict[str, Article]:
    """Everything currently in the store, keyed by ``article_id``."""
    directory = paths.articles_dir
    if not directory.exists():
        return {}
    out: dict[str, Article] = {}
    for file in sorted(directory.glob("*.json")):
        article = read_article(file)
        out[article.article_id] = article
    return out


def put_article(paths: TopicPaths, article: Article) -> PutResult:
    """Add one article to the store, preserving whatever was there before.

    ``unchanged`` is the common case on a rebuild and is why annotations survive: the file
    keeps its original bytes, so its content hash — and every anchor into it — is stable.
    A genuine re-collection with different text is a ``superseded``: the previous bytes move
    to ``articles/_superseded/`` keyed by their content hash, so a run that pinned the old
    hash can still be restored.

    ``revised`` is the third case and it is the common one on a *mechanism* change: the
    record differs but the sentence set does not, so the bytes are archived for
    restorability while every existing anchor keeps resolving.  Separating it from
    ``superseded`` is what keeps an incremental rebuild incremental — see
    :data:`PutResult`.
    """
    target = paths.article_file(article.article_id)
    if not target.exists():
        _write_article(target, article)
        return "new"

    existing = read_article(target)
    if article_content_hash(existing) == article_content_hash(article):
        return "unchanged"

    digest = article_content_hash(existing).split(":", 1)[1][:12]
    archive = paths.superseded_articles_dir / f"{article.article_id}.{digest}.json"
    if not archive.exists():
        _write_article(archive, existing)
    _write_article(target, article)
    if article_sentence_hash(existing) == article_sentence_hash(article):
        return "revised"
    return "superseded"


def find_article(paths: TopicPaths, article_id: str, content_hash: str) -> Optional[Article]:
    """The exact content a run pinned — current file first, then the superseded archive."""
    current = paths.article_file(article_id)
    if current.exists():
        article = read_article(current)
        if article_content_hash(article) == content_hash:
            return article
    archive_dir = paths.superseded_articles_dir
    if archive_dir.exists():
        for file in sorted(archive_dir.glob(f"{article_id}.*.json")):
            article = read_article(file)
            if article_content_hash(article) == content_hash:
                return article
    return None


# --- withdrawals -----------------------------------------------------------------------


def load_withdrawn(paths: TopicPaths) -> list[WithdrawnArticle]:
    path = paths.withdrawn_articles
    if not path.exists():
        return []
    out: list[WithdrawnArticle] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            out.append(WithdrawnArticle.model_validate_json(line))
        except ValueError as exc:
            raise ArtifactError(f"{path}:{lineno}: WithdrawnArticle invalid — {exc}") from exc
    return out


def withdraw_article(paths: TopicPaths, article_id: str, reason: str) -> WithdrawnArticle:
    """Exclude an article from future runs without deleting it.

    Deleting the file would make every earlier run unrestorable, and — before content
    addressing — also shifted every later article's ID.  Withdrawal states the exclusion
    and its reason instead, which is what a reviewer asking "why is this not in the sample"
    actually needs.
    """
    entry = WithdrawnArticle(
        article_id=article_id, reason=reason, at=datetime.now(timezone.utc)
    )
    path = paths.withdrawn_articles
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")
    return entry


# --- corpus runs -----------------------------------------------------------------------


def write_corpus_run(paths: TopicPaths, run: CorpusRun) -> Path:
    path = paths.corpus_run_file(run.run_id)
    if path.exists():
        raise ArtifactError(f"refusing to overwrite an existing corpus run: {path}")
    return write_json(path, json.loads(run.model_dump_json()))


def load_corpus_run(paths: TopicPaths, run_id: Optional[str] = None) -> CorpusRun:
    resolved = run_id or paths.active_run_id("corpus")
    if not resolved:
        raise ArtifactError(
            f"{paths.topic_id} has no active corpus run; run `python -m newsab_corpus build`"
        )
    path = paths.corpus_run_file(resolved)
    if not path.exists():
        raise ArtifactError(f"no corpus run record at {path}")
    try:
        return CorpusRun.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ArtifactError(f"{path}: CorpusRun invalid — {exc}") from exc


def restore_set(paths: TopicPaths, run: CorpusRun) -> tuple[list[Article], list[str]]:
    """Rebuild the exact article set a run saw, with its cluster assignment applied.

    Returns the articles plus the reasons any member could not be restored.  This is the
    replacement for "read whatever is in the corpus directory": a recomputation checks a
    published number against the set that produced it, not against today's disk.
    """
    articles: list[Article] = []
    errors: list[str] = []
    for member in run.articles:
        found = find_article(paths, member.article_id, member.content_hash)
        if found is None:
            errors.append(
                f"{member.article_id}: content {member.content_hash} is not in the store "
                "(neither current nor superseded)"
            )
            continue
        articles.append(
            Article.model_validate(
                {
                    **found.model_dump(mode="json"),
                    "reporting_cluster_id": member.reporting_cluster_id,
                }
            )
        )
    return articles, errors


def load_run_articles(paths: TopicPaths, run_id: Optional[str] = None) -> list[Article]:
    """The active (or named) run's article set, or a hard failure saying what is missing."""
    run = load_corpus_run(paths, run_id)
    articles, errors = restore_set(paths, run)
    if errors:
        raise ArtifactError(
            f"corpus run {run.run_id} cannot be restored:\n  " + "\n  ".join(errors)
        )
    return articles


# --- the global source registry --------------------------------------------------------


def empty_registry() -> SourceRegistry:
    return SourceRegistry(
        registry_version="0.1.0", updated_at=datetime.now(timezone.utc), sources=[]
    )


def load_registry(path: str | Path) -> SourceRegistry:
    """Read ``sources/registry.yaml``; a missing file is an empty registry, not an error.

    The registry is knowledge, not a gate (R-3) — a topic that has never met an outlet
    should be able to start collecting, and the first collection run fills it in.
    """
    target = Path(path)
    if not target.exists():
        return empty_registry()
    return read_yaml(target, SourceRegistry)


def save_registry(path: str | Path, registry: SourceRegistry) -> Path:
    return write_yaml(path, registry)


# --- site-level publication store ------------------------------------------------------


def write_publication(paths, publication):
    """Write one immutable reviewed release candidate under the site root.

    Kept here, beside the topic store, so stage implementations never invent a second
    directory convention or silently overwrite a publication record.
    """
    from .io import ArtifactError, dump_record
    from .models.publication import PublicationRecord
    from .paths import SitePaths

    if not isinstance(paths, SitePaths):
        raise TypeError("write_publication expects SitePaths")
    record = PublicationRecord.model_validate(publication)
    target = paths.publication_record(record.publication_id)
    if target.exists():
        raise ArtifactError(f"refusing to overwrite publication: {target}")
    # exist_ok tolerates a directory left behind by an earlier crash between mkdir and
    # write; the record itself lands atomically so no reader ever sees partial bytes.
    target.parent.mkdir(parents=True, exist_ok=True)
    _replace_fsynced(target, dump_record(record) + "\n")
    return target


def _replace_fsynced(target: Path, text: str) -> None:
    """Write ``text`` durably at ``target`` via a same-directory temp file."""
    temporary = target.parent / f".{target.name}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    directory_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def load_publication(paths, publication_id: str):
    from .io import ArtifactError
    from .models.publication import PublicationRecord

    target = paths.publication_record(publication_id)
    if not target.is_file():
        raise ArtifactError(f"publication record does not exist: {target}")
    try:
        return PublicationRecord.model_validate_json(target.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ArtifactError(f"{target}: PublicationRecord invalid — {exc}") from exc


def load_publications(paths) -> dict[str, object]:
    """Every immutable publication, keyed by id in lexical order."""
    out = {}
    if not paths.publications_dir.exists():
        return out
    import re

    from .models.publication import PUBLICATION_ID_RE

    for directory in sorted(paths.publications_dir.iterdir()):
        if not directory.is_dir():
            continue
        if not re.fullmatch(PUBLICATION_ID_RE, directory.name):
            raise ArtifactError(
                f"unexpected entry under {paths.publications_dir}: {directory.name!r} "
                "is not a publication id"
            )
        record = load_publication(paths, directory.name)
        out[record.publication_id] = record
    return out


def load_publication_events(paths):
    from .io import read_jsonl
    from .models.publication import PublicationEvent, PublicationEventLog

    events = (
        read_jsonl(paths.publication_events, PublicationEvent)
        if paths.publication_events.exists()
        else []
    )
    PublicationEventLog(events=events)
    return events


def derive_publish_selector(publications, events, publication_hashes=None):
    """Rebuild the unique live publication per topic from immutable facts.

    This is the lifecycle state machine's definition site.  The selector written to disk
    is merely this function's atomic cache; callers never edit it to publish or withdraw.
    """
    from .io import ArtifactError
    from .models.manifest import content_digest
    from .models.publication import PublicationEventLog, PublishSelector
    from .enums import PublicationEventType

    records = (
        publications
        if isinstance(publications, dict)
        else {record.publication_id: record for record in publications}
    )
    sequence = list(events)
    byte_hashes = publication_hashes or {}
    PublicationEventLog(events=sequence)
    status: dict[str, str] = {}
    active: dict[str, str] = {}

    def checked(event, publication_id: str, claimed_hash: str):
        record = records.get(publication_id)
        if record is None:
            raise ArtifactError(
                f"{event.event_id}: publication does not exist: {publication_id}"
            )
        # Disk callers provide exact artifact-byte hashes.  In-memory callers use the
        # canonical semantic digest, which makes the pure state machine easy to test.
        actual = byte_hashes.get(publication_id) or content_digest(record.model_dump(mode="json"))
        if actual != claimed_hash:
            raise ArtifactError(
                f"{event.event_id}: publication hash mismatch for {publication_id}"
            )
        return record

    for event in sequence:
        record = checked(event, event.publication_id, event.publication_hash)
        topic_id = record.topic_id
        current = status.get(event.publication_id, "reviewed")
        if event.event_type == PublicationEventType.PUBLISH:
            if current != "reviewed" or topic_id in active:
                raise ArtifactError(
                    f"{event.event_id}: publish requires one reviewed candidate and no live topic version"
                )
            status[event.publication_id] = "published"
            active[topic_id] = event.publication_id
        elif event.event_type == PublicationEventType.SUPERSEDE:
            if current != "published" or active.get(topic_id) != event.publication_id:
                raise ArtifactError(f"{event.event_id}: only the live publication can be superseded")
            replacement = checked(
                event,
                event.replacement_publication_id,
                event.replacement_publication_hash,
            )
            if replacement.topic_id != topic_id:
                raise ArtifactError(f"{event.event_id}: replacement belongs to another topic")
            if status.get(replacement.publication_id, "reviewed") != "reviewed":
                raise ArtifactError(f"{event.event_id}: replacement is not an unused reviewed candidate")
            status[event.publication_id] = "superseded"
            status[replacement.publication_id] = "published"
            active[topic_id] = replacement.publication_id
        elif event.event_type == PublicationEventType.WITHDRAW:
            if current != "published" or active.get(topic_id) != event.publication_id:
                raise ArtifactError(f"{event.event_id}: only the live publication can be withdrawn")
            status[event.publication_id] = "withdrawn"
            del active[topic_id]
        elif event.event_type == PublicationEventType.RESTORE:
            if current != "withdrawn" or topic_id in active:
                raise ArtifactError(
                    f"{event.event_id}: restore requires a withdrawn version and no live replacement"
                )
            status[event.publication_id] = "published"
            active[topic_id] = event.publication_id
        elif event.event_type == PublicationEventType.AUDIT_DELETE:
            if current == "published":
                raise ArtifactError(
                    f"{event.event_id}: withdraw a live publication before audit deletion"
                )
            status[event.publication_id] = "audit_deleted"

    return PublishSelector(
        publications=dict(sorted(active.items())),
        event_count=len(sequence),
        event_log_hash=content_digest(
            [event.model_dump(mode="json") for event in sequence]
        ),
    )


def append_publication_event(paths, event):
    """Validate and fsync one lifecycle event, then atomically rebuild the selector."""
    import fcntl

    from .io import ArtifactError, dump_record
    from .models.manifest import content_digest, file_digest
    from .models.publication import PublicationEvent, PublicationEventLog

    candidate = PublicationEvent.model_validate(event)
    path = paths.publication_events
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            events = []
            for lineno, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    events.append(PublicationEvent.model_validate_json(line))
                except ValueError as exc:
                    raise ArtifactError(f"{path}:{lineno}: invalid publication event — {exc}") from exc
            if any(old.event_id == candidate.event_id for old in events):
                raise ArtifactError(f"duplicate publication event_id: {candidate.event_id}")
            expected_previous = (
                None
                if not events
                else content_digest(events[-1].model_dump(mode="json"))
            )
            if candidate.previous_event_hash != expected_previous:
                raise ArtifactError("publication event does not extend the current hash chain")

            publications = load_publications(paths)
            # Bind disk records to their exact immutable bytes for event verification.
            hashes = {
                publication_id: file_digest(paths.publication_record(publication_id))
                for publication_id in publications
            }
            selector = derive_publish_selector(
                publications, [*events, candidate], publication_hashes=hashes
            )
            PublicationEventLog(events=[*events, candidate])
            handle.seek(0, os.SEEK_END)
            handle.write(dump_record(candidate) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            # The derived selector must be replaced while the event lock is still held:
            # released earlier, a slower appender could overwrite a newer selector with
            # its stale derivation and the cache would contradict the durable log.
            paths.production_dir.mkdir(parents=True, exist_ok=True)
            _replace_fsynced(paths.production_selector, dump_record(selector) + "\n")
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return path
