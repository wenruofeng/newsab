"""Reading and writing artifacts.

JSONL for record streams (observations, angles, manifest entries) because it appends
cleanly and diffs line-by-line in a GitHub PR — which is the submission channel (D12).
YAML for the human-edited files (topic manifest, sources, ontology, gold set).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator, Sequence, Type, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from .models import (
    Article,
    ArticleAnnotation,
    CorpusRun,
    CandidateAngle,
    Claim,
    ConceptOntology,
    CorrectionMapping,
    GoldStandardSet,
    ManifestEntry,
    Observation,
    PublicationEvent,
    PublicationRecord,
    CatalogRecord,
    PublishSelector,
    SourceRegistry,
    TopicManifest,
)

T = TypeVar("T", bound=BaseModel)


class ArtifactError(ValueError):
    """A file exists but does not parse or does not validate."""


def _json_default(obj: object) -> object:
    from datetime import date, datetime

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


def dump_record(record: BaseModel) -> str:
    """Canonical single-line JSON for one record.

    ``sort_keys`` and ``ensure_ascii=False`` make the bytes reproducible and keep Chinese
    readable in a diff — both matter when the artifact hash is part of the audit trail.
    """
    return json.dumps(
        record.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def write_jsonl(path: str | Path, records: Iterable[BaseModel]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(dump_record(record) + "\n")
    return target


def read_jsonl(path: str | Path, model: Type[T]) -> list[T]:
    """Parse a JSONL artifact, reporting the line number of the first bad record."""
    out: list[T] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(model.model_validate(json.loads(line)))
            except json.JSONDecodeError as exc:
                raise ArtifactError(f"{path}:{lineno}: not valid JSON — {exc}") from exc
            except ValidationError as exc:
                raise ArtifactError(f"{path}:{lineno}: {model.__name__} invalid — {exc}") from exc
    return out


def iter_jsonl(path: str | Path, model: Type[T]) -> Iterator[T]:
    """Streaming variant, for corpora that outgrow memory."""
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield model.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ArtifactError(f"{path}:{lineno}: {model.__name__} invalid — {exc}") from exc


def write_yaml(path: str | Path, record: BaseModel) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(dump_record(record))
    with open(target, "w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=True, width=100)
    return target


#: The C parser when PyYAML was built against libyaml, else the pure-Python one.  Same
#: safe subset, same objects; the pure-Python scanner is ~9x slower and it dominated
#: ``verify-site`` (129s of a 145s run went into re-parsing YAML).
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load_yaml_text(text: str) -> object:
    """Parse one YAML document from text — the repo's single ``safe_load`` entry point.

    Call this instead of :func:`yaml.safe_load` so every reader gets the fast loader.
    """
    return yaml.load(text, Loader=_LOADER)


def read_yaml(path: str | Path, model: Type[T]) -> T:
    raw = load_yaml_text(Path(path).read_text(encoding="utf-8"))
    if raw is None:
        raise ArtifactError(f"{path}: file is empty")
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise ArtifactError(f"{path}: {model.__name__} invalid — {exc}") from exc


def write_json(path: str | Path, payload: object, indent: int = 2) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=indent, default=_json_default)
        + "\n",
        encoding="utf-8",
    )
    return target


# --- convenience loaders bound to the topic layout ------------------------------------


def load_articles(articles_dir: str | Path) -> list[Article]:
    """Every article record in a directory, sorted by article_id.

    This reads the *store*, i.e. everything ever ingested.  To read the set one analysis
    saw — which is what a recomputation must use — call
    :func:`newsab_schema.store.load_run_articles` with a ``run_id`` instead (R-2).
    """
    directory = Path(articles_dir)
    if not directory.exists():
        raise ArtifactError(f"{directory}: corpus directory does not exist")
    articles: list[Article] = []
    for file in sorted(directory.glob("*.json")):
        try:
            articles.append(Article.model_validate(json.loads(file.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ArtifactError(f"{file}: Article invalid — {exc}") from exc
    return articles


def write_articles(articles_dir: str | Path, articles: Sequence[Article]) -> list[Path]:
    directory = Path(articles_dir)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for article in articles:
        path = directory / f"{article.article_id}.json"
        path.write_text(
            json.dumps(
                article.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                default=_json_default,
            )
            + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


#: Which model each well-known artifact file holds.  Used by the CLI so ``validate`` can be
#: pointed at a path without being told what it contains.
ARTIFACT_MODELS: dict[str, Type[BaseModel]] = {
    "topic_manifest.yaml": TopicManifest,
    "registry.yaml": SourceRegistry,
    "corpus_run.json": CorpusRun,
    "observations.jsonl": Observation,
    "article_annotations.jsonl": ArticleAnnotation,
    "concepts.yaml": ConceptOntology,
    "candidate_angles.jsonl": CandidateAngle,
    "claims.jsonl": Claim,
    "gold_standard.yaml": GoldStandardSet,
    "manifest.jsonl": ManifestEntry,
    "corrections.jsonl": CorrectionMapping,
    "publication.json": PublicationRecord,
    "publication_events.jsonl": PublicationEvent,
    "selector.json": PublishSelector,
}
