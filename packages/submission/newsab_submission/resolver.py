"""Resolve an imported submission namespace the way stage 8 resolves a page run.

This mirrors :func:`newsab_publish.builder.resolve_inputs` with one deliberate
difference: an archive never carries rendered HTML, so the page run's preview files are
represented by their recorded hashes (the envelope's ``hash_only`` members).  The pin
fingerprint of the page run is recomputed from the on-disk bytes *plus* that overlay,
which keeps the closure self-consistent while the actual displayable surface is always
rebuilt by the site's own renderer (G2).

A parity test asserts this resolver and the builder agree on a closure with no
hash-only members, so the two walks cannot drift silently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from newsab_editorial.evidence import AnswerIndex
from newsab_editorial.page_checks import (
    load_analysis_run,
    load_excluded_clusters,
    load_pinned_corpus_run,
)
from newsab_publish.builder import (
    ResolvedInputs,
    _entry,
    _is_ancestor,
    _load_topics_by_article,
    canonical_json_bytes,
)
from newsab_schema.artifacts import load_manifest, manifest_entry_fingerprint
from newsab_schema.io import ArtifactError, load_yaml_text, read_jsonl, read_yaml
from newsab_schema.models.corpus import SourceRegistry, TopicManifest
from newsab_schema.models.manifest import ManifestEntry
from newsab_schema.models.page import ReaderPage
from newsab_schema.models.publication import TopicRunPin
from newsab_schema.models.qa import ClusterAnswer, QuestionSet
from newsab_schema.paths import SOURCE_REGISTRY_SUBPATH, TopicPaths
from newsab_schema.store import empty_registry, load_run_articles


def _entry_fingerprint(
    paths: TopicPaths, entry: ManifestEntry, overlay: Mapping[str, str]
) -> str:
    """One pinned run's fingerprint, honouring hash-only members.

    Runs untouched by the overlay go through the trusted
    :func:`~newsab_schema.artifacts.manifest_entry_fingerprint` unchanged.
    """
    return manifest_entry_fingerprint(paths, entry, hash_only=overlay)


def resolve_submission_inputs(
    topics_root: str | Path,
    topic_id: str,
    page_run_id: str,
    *,
    overlay: Mapping[str, str],
) -> ResolvedInputs:
    paths = TopicPaths.for_topic(topics_root, topic_id)
    entries = tuple(load_manifest(paths))
    entry_by_id = {entry.run_id: entry for entry in entries}
    page_entry = _entry(entry_by_id, page_run_id, "page")
    if page_entry.stage != "editorial":
        raise ArtifactError(f"{page_run_id}: page run must be an editorial-stage artifact")
    page_path = paths.stage_run_dir("editorial", page_run_id) / "page.json"
    if not page_path.is_file():
        raise ArtifactError(f"page artifact is missing: {page_path}")
    page = ReaderPage.model_validate_json(page_path.read_text(encoding="utf-8"))
    if page.topic_id != topic_id or page.provenance.run_id != page_run_id:
        raise ArtifactError("page bytes do not identify the explicit topic/page run")

    manifest = read_yaml(paths.topic_manifest, TopicManifest)
    scope_problem = manifest.scope_approval_problem()
    if scope_problem:
        raise ArtifactError(f"scope approval is invalid: {scope_problem}")

    how = page.how_we_counted
    logical_runs = {
        "corpus": how.corpus_run_id,
        "questions": how.questions_run_id,
        "answers": how.answers_run_id,
        "analysis": how.qa_run_id,
        "page": page_run_id,
    }
    analysis_entry = _entry(entry_by_id, how.qa_run_id, "analysis")
    normalization_run = next(
        (
            run_id
            for run_id in analysis_entry.inputs
            if run_id.startswith("nrm-")
            or (
                entry_by_id.get(run_id) is not None
                and entry_by_id[run_id].skill_id == "normalize"
            )
        ),
        None,
    )
    if normalization_run is None:
        raise ArtifactError(f"analysis run {how.qa_run_id} has no normalization input")
    logical_runs["normalization"] = normalization_run

    for stage, run_id in logical_runs.items():
        _entry(entry_by_id, run_id, stage)
        if stage != "page" and not _is_ancestor(entry_by_id, page_run_id, run_id):
            raise ArtifactError(f"page run {page_run_id} does not depend on {stage} run {run_id}")

    pins = [
        TopicRunPin(
            topic_id=topic_id,
            stage="scope",
            run_id=manifest.provenance.run_id,
            artifact_fingerprint=manifest.scope_hash(),
        )
    ]
    for stage in ("corpus", "questions", "answers", "normalization", "analysis", "page"):
        run_id = logical_runs[stage]
        fingerprint = _entry_fingerprint(paths, entry_by_id[run_id], overlay)
        pins.append(
            TopicRunPin(
                topic_id=topic_id,
                stage=stage,
                run_id=run_id,
                artifact_fingerprint=fingerprint,
            )
        )

    articles = tuple(load_run_articles(paths, how.corpus_run_id))
    qa_dir = paths.a1_run_dir(how.qa_run_id)
    if load_pinned_corpus_run(qa_dir) != how.corpus_run_id:
        raise ArtifactError("analysis run pins a different corpus than the page")
    findings, question_stats = load_analysis_run(qa_dir)
    answers_path = paths.stage_run_dir("answers", how.answers_run_id) / "answers.jsonl"
    questions_path = paths.stage_run_dir("questions", how.questions_run_id) / "questions.yaml"
    answer_index = AnswerIndex(
        read_jsonl(answers_path, ClusterAnswer),
        excluded_clusters=load_excluded_clusters(qa_dir),
    )
    question_set = read_yaml(questions_path, QuestionSet)
    topics_by_article, topics_bytes = _load_shipped_topics_by_article(paths)
    source_registry, source_registry_bytes = _load_namespace_registry(paths.root.parent)

    return ResolvedInputs(
        paths=paths,
        manifest=manifest,
        page=page,
        entries=entries,
        entry_by_id=entry_by_id,
        pins=tuple(pins),
        articles=articles,
        findings=tuple(findings),
        question_stats=question_stats,
        answers=answer_index,
        question_set=question_set,
        topics_by_article=topics_by_article,
        topics_by_article_bytes=topics_bytes,
        source_registry=source_registry,
        source_registry_bytes=source_registry_bytes,
    )


def _load_shipped_topics_by_article(paths: TopicPaths) -> tuple[dict, bytes]:
    """The pack-time derived mapping, shipped instead of its private staging inputs.

    The trusted loader prefers exactly this file when it exists, so both walks read the
    same bytes; an archive without one still resolves to the empty mapping.
    """
    if not (paths.corpus_dir / "topics_by_article.json").is_file():
        mapping: dict = {}
        return mapping, canonical_json_bytes(mapping)
    return _load_topics_by_article(paths)


def _load_namespace_registry(topics_root: Path) -> tuple[object, bytes]:
    """The registry bytes shipped in the archive — never the operator's own registry.

    Deliberately ignores ``$NEWSAB_SOURCE_REGISTRY``: verification must read the
    imported namespace (``<namespace>/sources/registry.yaml`` beside ``topics/``), not
    whatever the running environment points at.
    """
    registry_file = Path(topics_root).resolve().parent / SOURCE_REGISTRY_SUBPATH
    if not registry_file.exists():
        return empty_registry(), b""
    payload = registry_file.read_bytes()
    registry = SourceRegistry.model_validate(load_yaml_text(payload.decode("utf-8")))
    return registry, payload
