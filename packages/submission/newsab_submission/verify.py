"""G1 (protocol / closure) and G2 (trusted recomputation) — plan §6.2, §7.3.

G1 asks: is the archive exactly the closed closure its envelope declares — right
protocol, right member table, right hashes, a manifest chain that resolves and pins
that recompute?  G2 asks: do the deterministic layers reproduce — does the trusted
analyzer regenerate the archived findings from the archived inputs, and does the
trusted renderer deterministically rebuild a candidate page from the closure?

Both gates run entirely on the local machine against an imported throwaway namespace.
Nothing from the archive is executed or imported; model-facing review (G3) and the
human touchpoint (G4) sit outside this package and never start unless G0–G2 passed.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Optional

from pydantic import ValidationError

from newsab_a1.qa_analyze import PACKAGE_VERSION as ANALYZER_VERSION
from newsab_a1.qa_analyze import QAThresholds, analyse_qa
from newsab_publish.builder import (
    directory_fingerprint,
    render_candidate_bundle,
)
from newsab_publish.site_strings import SITE_LOCALES
from newsab_publish.themes import (
    default_theme_registry_path,
    load_theme_registry,
    resolve_theme,
)
from newsab_schema.io import ArtifactError
from newsab_schema.ids import IdError, validate_run_id, validate_topic_id
from newsab_schema.models.corpus import CorpusRun
from newsab_schema.models.findings import QAFinding
from newsab_schema.paths import SOURCE_REGISTRY_SUBPATH, TopicPaths

from . import PACKAGE_VERSION
from .closure import CORPUS_RUN_FILES, sha256_bytes, stage_dir_prefix, topic_member
from .envelope import (
    ENVELOPE_MEMBER,
    REGISTRY_MEMBER,
    SubmissionEnvelope,
    protocol_compatible,
)
from .errors import SubmissionRefused, refuse
from .g0 import ArchiveLimits, extract_archive, read_envelope_json
from .resolver import resolve_submission_inputs

#: Analyzer versions this toolkit reproduces bit-for-bit.  An archive analyzed by any
#: other version gets a structured refusal, never a silently different recomputation.
SUPPORTED_ANALYZER_VERSIONS = frozenset({ANALYZER_VERSION})

_FIXED_CORPUS_FILES = frozenset(
    {
        topic_member("topic_manifest.yaml"),
        topic_member("manifest/manifest.jsonl"),
    }
)
_OPTIONAL_FILES = frozenset(
    {
        topic_member("corpus/topics_by_article.json"),
        topic_member("corpus/collection_log.jsonl"),
        topic_member("corpus/withdrawn.jsonl"),
        REGISTRY_MEMBER,
    }
)


def parse_envelope(payload: dict) -> SubmissionEnvelope:
    try:
        envelope = SubmissionEnvelope.model_validate(payload)
    except ValidationError as exc:
        raise refuse("G1", "G1_ENVELOPE_SCHEMA", f"envelope does not match the protocol schema: {exc}") from exc
    if not protocol_compatible(envelope.protocol_version):
        raise refuse(
            "G1",
            "G1_PROTOCOL_UNSUPPORTED",
            f"archive protocol {envelope.protocol_version} is not verifiable by "
            f"{PACKAGE_VERSION} — repack with a compatible toolkit",
        )
    return envelope


def _extracted_files(extracted: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in sorted(candidate for candidate in extracted.rglob("*") if candidate.is_file()):
        out[path.relative_to(extracted).as_posix()] = path
    return out


def check_members(envelope: SubmissionEnvelope, extracted: Path) -> None:
    """Declared member table == extracted bytes, exactly and with matching hashes."""
    on_disk = _extracted_files(extracted)
    on_disk.pop(ENVELOPE_MEMBER, None)
    declared_included = {m.path: m for m in envelope.members if m.kind == "included"}
    declared_hash_only = [m for m in envelope.members if m.kind == "hash_only"]

    for path in sorted(set(on_disk) - set(declared_included)):
        raise refuse("G1", "G1_MEMBER_UNDECLARED", "archive carries a file its envelope does not declare", path)
    for path in sorted(set(declared_included) - set(on_disk)):
        raise refuse("G1", "G1_MEMBER_MISSING", "envelope declares a member the archive does not carry", path)
    for path, member in sorted(declared_included.items()):
        payload = on_disk[path].read_bytes()
        if len(payload) != member.size_bytes or sha256_bytes(payload) != member.sha256:
            raise refuse("G1", "G1_MEMBER_HASH_MISMATCH", "member bytes do not match their declared hash", path)

    if envelope.page_run_id is None:
        if declared_hash_only:
            raise refuse("G1", "G1_HASH_ONLY_DISALLOWED", "withdraw archives declare no members")
        return
    page_prefix = stage_dir_prefix("page", envelope.page_run_id)
    for member in declared_hash_only:
        if member.path in on_disk:
            raise refuse(
                "G1", "G1_HASH_ONLY_DISALLOWED",
                "hash-only member is also present as bytes", member.path,
            )
        suffix = PurePosixPath(member.path).suffix.lower()
        if not member.path.startswith(page_prefix) or suffix not in (".html", ".htm"):
            raise refuse(
                "G1", "G1_HASH_ONLY_DISALLOWED",
                "only the page run's rendered previews may be hash-only", member.path,
            )


def check_closed_list(envelope: SubmissionEnvelope, extracted: Path) -> None:
    """Every declared member must be a file the closure calls for — nothing else rides."""
    stage_runs = {pin.stage: pin.run_id for pin in envelope.run_closure}
    prefixes = {
        stage: stage_dir_prefix(stage, run_id)
        for stage, run_id in stage_runs.items()
        if stage != "scope"
    }
    corpus_pin = stage_runs["corpus"]
    corpus_run_file = extracted / PurePosixPath(
        prefixes["corpus"] + "corpus_run.json"
    )
    if not corpus_run_file.is_file():
        raise refuse(
            "G1", "G1_CLOSURE_INCOMPLETE",
            "the pinned corpus run record is missing",
            prefixes["corpus"] + "corpus_run.json",
        )
    try:
        corpus_run = CorpusRun.model_validate_json(corpus_run_file.read_text(encoding="utf-8"))
    except (ValidationError, UnicodeDecodeError) as exc:
        raise refuse("G1", "G1_SCHEMA_INVALID", f"corpus run record is invalid: {exc}") from exc
    if corpus_run.run_id != corpus_pin:
        raise refuse("G1", "G1_CLOSURE_PIN_MISMATCH", "corpus run record names a different run id")
    expected_articles = {
        topic_member(f"corpus/articles/{member.article_id}.json")
        for member in corpus_run.articles
    }

    seen_articles: set[str] = set()
    for member in envelope.members:
        path = member.path
        if path in _FIXED_CORPUS_FILES or path in _OPTIONAL_FILES:
            continue
        if path in expected_articles:
            seen_articles.add(path)
            continue
        prefix = next((p for p in prefixes.values() if path.startswith(p)), None)
        if prefix is None:
            raise refuse("G1", "G1_MEMBER_OUTSIDE_CLOSURE", "member is not part of the pinned closure", path)
        if prefix == prefixes["corpus"] and PurePosixPath(path).name not in CORPUS_RUN_FILES:
            raise refuse("G1", "G1_MEMBER_OUTSIDE_CLOSURE", "unexpected file in the corpus run directory", path)
    missing_articles = expected_articles - seen_articles
    if missing_articles:
        raise refuse(
            "G1", "G1_CLOSURE_INCOMPLETE",
            f"{len(missing_articles)} pinned article(s) missing, e.g. {sorted(missing_articles)[0]}",
        )
    for required in sorted(_FIXED_CORPUS_FILES):
        if not (extracted / PurePosixPath(required)).is_file():
            raise refuse("G1", "G1_CLOSURE_INCOMPLETE", "required closure file is missing", required)


def import_namespace(envelope: SubmissionEnvelope, extracted: Path, work: Path) -> Path:
    """Materialize the throwaway namespace: ``<work>/namespace/topics/<topic_id>``.

    The topic directory name comes from the validated envelope, never from archive
    member paths; the archive's fixed ``topic/`` root is renamed on import (plan §6.1:
    no contributor-chosen directory names).
    """
    try:
        validate_topic_id(envelope.topic_id)
        if envelope.page_run_id is not None:
            validate_run_id(envelope.page_run_id)
    except IdError as exc:
        raise refuse("G1", "G1_ENVELOPE_SCHEMA", str(exc)) from exc
    namespace = work / "namespace"
    topics_root = namespace / "topics"
    topics_root.mkdir(parents=True)
    shutil.copytree(extracted / "topic", topics_root / envelope.topic_id)
    registry = extracted / PurePosixPath(REGISTRY_MEMBER)
    if registry.is_file():
        target = namespace / PurePosixPath(SOURCE_REGISTRY_SUBPATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(registry, target)
    return topics_root


def run_g1(envelope: SubmissionEnvelope, extracted: Path, work: Path):
    """Full protocol/closure verification; returns ``(topics_root, resolved)``."""
    check_members(envelope, extracted)
    if envelope.operation == "withdraw":
        return None, None
    unsupported = [loc for loc in envelope.requested_locales if loc not in SITE_LOCALES]
    if unsupported:
        raise refuse(
            "G1", "G1_LOCALE_UNSUPPORTED",
            f"requested locales {unsupported} are outside the renderer's set {list(SITE_LOCALES)}",
        )
    check_closed_list(envelope, extracted)
    topics_root = import_namespace(envelope, extracted, work)
    overlay = {
        str(PurePosixPath(m.path).relative_to("topic")): m.sha256
        for m in envelope.members
        if m.kind == "hash_only"
    }
    try:
        resolved = resolve_submission_inputs(
            topics_root, envelope.topic_id, envelope.page_run_id, overlay=overlay
        )
    except (ArtifactError, ValidationError, ValueError) as exc:
        raise refuse("G1", "G1_CLOSURE_RESOLUTION", str(exc)) from exc
    if tuple(resolved.pins) != tuple(envelope.run_closure):
        raise refuse(
            "G1", "G1_CLOSURE_PIN_MISMATCH",
            "the archive's recomputed run closure differs from the envelope's claim",
        )
    return topics_root, resolved


def _semantic_finding(finding: QAFinding) -> dict:
    return finding.model_dump(mode="json", exclude={"provenance"}, exclude_none=True)


def run_g2(envelope: SubmissionEnvelope, resolved, work: Path) -> dict:
    """Trusted recomputation: analyzer reproduction plus deterministic re-render."""
    paths: TopicPaths = resolved.paths
    qa_dir = paths.a1_run_dir(envelope.run_closure[-2].run_id)
    stored_record = json.loads((qa_dir / "run.json").read_text(encoding="utf-8"))
    stored_version = stored_record.get("package_version")
    if stored_version not in SUPPORTED_ANALYZER_VERSIONS:
        raise refuse(
            "G2", "G2_ANALYZER_UNSUPPORTED",
            f"analysis was produced by {stored_version!r}; this toolkit reproduces "
            f"{sorted(SUPPORTED_ANALYZER_VERSIONS)} — re-run the analyze stage and repack",
        )
    try:
        thresholds = QAThresholds(**stored_record.get("thresholds", {}))
    except TypeError as exc:
        raise refuse("G2", "G2_THRESHOLDS_UNSUPPORTED", f"recorded thresholds do not load: {exc}") from exc

    from newsab_schema.io import read_jsonl
    from newsab_schema.models.qa import ClusterAnswer
    from newsab_schema.store import load_corpus_run

    corpus_run = load_corpus_run(paths, envelope.run_closure[1].run_id)
    stored_inputs = stored_record.get("inputs") or {}
    answers_run_id = stored_inputs.get("answers_run_id") or envelope.run_closure[3].run_id
    # The full answers file, not the page-facing AnswerIndex: the analyzer decides its
    # own exclusions, exactly as the annotate → analyze pipeline feeds it.
    all_answers = read_jsonl(
        paths.stage_run_dir("answers", envelope.run_closure[3].run_id) / "answers.jsonl",
        ClusterAnswer,
    )
    category_map = None
    nrm_run = envelope.run_closure[4].run_id
    category_map_path = paths.stage_run_dir("normalization", nrm_run) / "category_map.json"
    if category_map_path.is_file():
        from newsab_schema.models.category_map import CategoryMap

        category_map = CategoryMap.model_validate_json(
            category_map_path.read_text(encoding="utf-8")
        )
    recomputed = analyse_qa(
        resolved.question_set,
        all_answers,
        corpus_run,
        topic_id=envelope.topic_id,
        thresholds=thresholds,
        category_map=category_map,
        access_levels={
            article.article_id: article.access_level.value for article in resolved.articles
        },
        answers_run_id=answers_run_id,
    )
    stored_semantic = [_semantic_finding(finding) for finding in resolved.findings]
    recomputed_semantic = [_semantic_finding(finding) for finding in recomputed.findings]
    if stored_semantic != recomputed_semantic:
        raise refuse(
            "G2", "G2_ANALYSIS_MISMATCH",
            "the trusted analyzer does not reproduce the archived findings from the archived inputs",
        )
    if json.loads(json.dumps(recomputed.question_stats)) != resolved.question_stats:
        raise refuse(
            "G2", "G2_ANALYSIS_MISMATCH",
            "the trusted analyzer does not reproduce the archived question statistics",
        )
    expected_inputs = {
        key: value for key, value in recomputed.inputs.items() if key in stored_inputs
    }
    if expected_inputs != stored_inputs:
        raise refuse(
            "G2", "G2_ANALYSIS_MISMATCH",
            "the archived analysis input record disagrees with the recomputation",
        )

    theme = resolve_theme(None, load_theme_registry(default_theme_registry_path()))
    fingerprints = []
    for attempt in ("render-a", "render-b"):
        out = work / attempt
        out.mkdir()
        try:
            render_candidate_bundle(
                resolved, envelope.requested_locales, out, m2=True, theme=theme
            )
        except (ArtifactError, ValueError) as exc:
            raise refuse("G2", "G2_RENDER_FAILED", f"trusted renderer refused the closure: {exc}") from exc
        fingerprints.append(directory_fingerprint(out))
    if fingerprints[0] != fingerprints[1]:
        raise refuse("G2", "G2_RENDER_NONDETERMINISTIC", "two trusted renders disagree")
    return {
        "analyzer_version": stored_version,
        "findings": len(stored_semantic),
        "render_locales": list(envelope.requested_locales),
        "candidate_fingerprint": fingerprints[0],
        "declared_preview_fingerprints": dict(envelope.diagnostics.preview_fingerprints),
    }


def verify_archive(
    archive: str | Path,
    *,
    work_dir: Optional[Path] = None,
    limits: ArchiveLimits = ArchiveLimits(),
    keep_work: bool = False,
) -> dict:
    """G0 → G1 → G2 over one archive; returns the structured verification report.

    On refusal the raised :class:`SubmissionRefused` carries the structured issues;
    the caller renders them.  The throwaway work directory is removed unless
    ``keep_work`` (or an explicit ``work_dir``) says otherwise.
    """
    own_work = work_dir is None
    work = Path(tempfile.mkdtemp(prefix="newsab-submission-")) if own_work else Path(work_dir)
    report: dict = {
        "schema_version": "submission-verify-report-0.1.0",
        "toolkit_version": PACKAGE_VERSION,
        "archive": str(archive),
        "gates": {},
    }
    try:
        extracted = work / "extracted"
        g0 = extract_archive(archive, extracted, limits)
        report["gates"]["g0"] = g0.to_dict()
        envelope = parse_envelope(read_envelope_json(extracted))
        report["submission_id"] = envelope.submission_id
        report["operation"] = envelope.operation
        report["topic_id"] = envelope.topic_id
        _, resolved = run_g1(envelope, extracted, work)
        report["gates"]["g1"] = {
            "members": len(envelope.members),
            "run_closure": [
                {"stage": pin.stage, "run_id": pin.run_id} for pin in envelope.run_closure
            ],
        }
        if envelope.operation != "withdraw":
            report["gates"]["g2"] = run_g2(envelope, resolved, work)
        report["ok"] = True
        return report
    finally:
        if own_work and not keep_work:
            shutil.rmtree(work, ignore_errors=True)
        elif own_work:
            report["work_dir"] = str(work)
