"""Command line entry point: ``python -m newsab_schema <command>``.

Skills call these rather than importing Python, so a stage's self-check is one line in
``SKILL.md`` and is runnable by any agent harness (skills/README.md rule 1).

Exit codes: ``0`` clean, ``1`` validation failed, ``2`` usage/IO problem.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .common import GateRecord
from .io import (
    ArtifactError,
    load_articles,
    read_jsonl,
    read_yaml,
)
from .lints import lint_text
from .models import (
    ArticleAnnotation,
    CandidateAngle,
    Claim,
    ClusterAnswer,
    ConceptOntology,
    CorrectionMapping,
    Escalation,
    ManifestEntry,
    Observation,
    QuestionSet,
    SourceRegistry,
    TopicManifest,
)
from .paths import STAGE_NAMES, TopicPaths, source_registry_path
from .sources import registry_entry_problems
from .store import load_corpus_run, load_registry, restore_set
from .validate import (
    ValidationReport,
    validate_angles,
    validate_answers,
    validate_article_annotations,
    validate_claims,
    validate_observations,
)


def _emit(report: ValidationReport, as_json: bool, strict: bool) -> int:
    print(report.to_json() if as_json else report.render())
    return report.exit_code(strict=strict)


def _load_optional(path: Path, loader):
    return loader(path) if path.exists() else None


def cmd_validate_topic(args: argparse.Namespace) -> int:
    """Validate whatever a topic directory currently holds, in pipeline order.

    Missing artifacts are skipped rather than failing: a topic that has only been through
    S4 should still be checkable.  What is present is checked in full.
    """
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    report = ValidationReport()

    if not paths.root.exists():
        print(f"no such topic directory: {paths.root}", file=sys.stderr)
        return 2

    registry_path = Path(args.registry) if args.registry else source_registry_path(args.topics_root)
    try:
        manifest = (
            read_yaml(paths.topic_manifest, TopicManifest)
            if paths.topic_manifest.exists()
            else None
        )
        sources = load_registry(registry_path) if registry_path.exists() else None
        # Validate the set the active run pinned, not whatever the store holds today: a
        # store legitimately contains articles a later run added or an earlier run
        # withdrew (R-2).
        articles = []
        if paths.active_run_id("corpus"):
            corpus_run = load_corpus_run(paths)
            articles, restore_errors = restore_set(paths, corpus_run)
            report.stats["corpus_run_id"] = corpus_run.run_id
            for problem in restore_errors:
                report.error("corpus_run_unrestorable", corpus_run.run_id, problem)
        elif paths.articles_dir.exists():
            articles = load_articles(paths.articles_dir)
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    report.stats["corpus_articles"] = len(articles)

    if manifest is None:
        report.info("stage_not_run", "topic_manifest", "no topic_manifest.yaml yet (S0 not run)")
    elif manifest.topic_id != args.topic_id:
        report.error(
            "wrong_topic", "topic_manifest", f"declares {manifest.topic_id}, not {args.topic_id}"
        )
    elif approval_problem := manifest.scope_approval_problem():
        report.error("scope_not_approved", "topic_manifest", approval_problem)

    if sources is None:
        report.info("stage_not_run", "source_registry", f"no {registry_path} yet")
    else:
        # The registry is cross-topic (R-3), so a thin entry is only *this* topic's
        # business when this topic's corpus actually uses it. Warning every topic about
        # every outlet anywhere is how a warning stops being read.
        used_source_ids = {a.source_id for a in articles}
        for source in sources.sources:
            if source.id not in used_source_ids:
                continue
            for problem in registry_entry_problems(source):
                report.warning("source_entry_thin", source.id, problem)

        by_source = {source.id: source for source in sources.sources}
        for article in articles:
            if article.topic_id != args.topic_id:
                report.error(
                    "wrong_topic", article.article_id, f"article declares {article.topic_id}"
                )
            source = by_source.get(article.source_id)
            if source is None:
                report.error(
                    "article_source_unknown",
                    article.article_id,
                    f"source_id={article.source_id} is absent from {registry_path}",
                )
                continue
            article_group = article.article_id.split("_", 1)[0].lower()
            # The article prefix persists the collector's explicit membership judgement
            # against the scope definition. Source metadata does not re-derive it.
            group = manifest.group_by_id(article_group) if manifest is not None else None
            if manifest is not None and group is None:
                report.error(
                    "source_group_unknown",
                    article.article_id,
                    f"article group={article_group} is absent from topic_manifest.groups",
                )
            if article.lang != source.lang:
                report.error(
                    "article_language_mismatch",
                    article.article_id,
                    f"article.lang={article.lang}, source.lang={source.lang}",
                )
            if manifest is not None and not manifest.period.contains(article.publish_date):
                report.error(
                    "article_outside_period",
                    article.article_id,
                    f"publish_date={article.publish_date} is outside topic period "
                    f"{manifest.period.start}..{manifest.period.end}",
                )

    ontology = _load_optional(paths.concepts, lambda p: read_yaml(p, ConceptOntology))

    if paths.observations.exists():
        observations = read_jsonl(paths.observations, Observation)
        report.extend(validate_observations(observations, articles, ontology))
    else:
        observations = []
        report.info("stage_not_run", "observations", "no observations.jsonl yet (S4 not run)")

    if paths.article_annotations.exists():
        report.extend(
            validate_article_annotations(
                read_jsonl(paths.article_annotations, ArticleAnnotation), articles
            )
        )

    question_set = _load_optional(paths.questions, lambda p: read_yaml(p, QuestionSet))
    if paths.answers.exists():
        if question_set is None:
            report.error(
                "answers_without_questions",
                str(paths.answers),
                "answers exist but no question set artifact is active",
            )
        else:
            cluster_assignment = None
            retexted: list[str] = []
            if paths.active_run_id("corpus"):
                corpus_run = load_corpus_run(paths)
                cluster_assignment = corpus_run.cluster_assignment
                retexted = corpus_run.retexted_anchors
            report.extend(
                validate_answers(
                    read_jsonl(paths.answers, ClusterAnswer),
                    question_set,
                    articles,
                    cluster_assignment=cluster_assignment,
                    retexted_anchors=retexted,
                )
            )
    elif question_set is not None:
        report.info("stage_not_run", "answers", "questions exist but no answers yet")

    angles: list[CandidateAngle] = []
    if paths.candidate_angles.exists():
        angles = read_jsonl(paths.candidate_angles, CandidateAngle)
        report.extend(
            validate_angles(
                angles,
                args.topic_id,
                known_observation_ids={o.observation_id for o in observations} or None,
            )
        )

    claims_path = paths.dossier_dir / "claims.jsonl"
    if claims_path.exists():
        report.extend(validate_claims(read_jsonl(claims_path, Claim), articles, angles))

    return _emit(report, args.json, args.strict)


_KINDS = {
    "observations": Observation,
    "article_annotations": ArticleAnnotation,
    "answers": ClusterAnswer,
    "angles": CandidateAngle,
    "claims": Claim,
}


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate one artifact file against the corpus."""
    path = Path(args.path)
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    try:
        articles = load_articles(args.corpus) if args.corpus else []
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        if args.kind == "observations":
            ontology = read_yaml(args.ontology, ConceptOntology) if args.ontology else None
            report = validate_observations(read_jsonl(path, Observation), articles, ontology)
        elif args.kind == "article_annotations":
            report = validate_article_annotations(read_jsonl(path, ArticleAnnotation), articles)
        elif args.kind == "answers":
            if not args.questions:
                print("kind=answers requires --questions <questions.yaml>", file=sys.stderr)
                return 2
            question_set = read_yaml(args.questions, QuestionSet)
            report = validate_answers(
                read_jsonl(path, ClusterAnswer), question_set, articles
            )
        elif args.kind == "angles":
            report = validate_angles(read_jsonl(path, CandidateAngle), args.topic_id)
        elif args.kind == "claims":
            angles = read_jsonl(args.angles, CandidateAngle) if args.angles else None
            report = validate_claims(read_jsonl(path, Claim), articles, angles)
        else:  # pragma: no cover - argparse restricts this
            raise SystemExit(f"unknown kind {args.kind}")
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    return _emit(report, args.json, args.strict)


def cmd_lint(args: argparse.Namespace) -> int:
    """Lint a single string — the fast feedback loop while writing a rubric example."""
    text = args.text if args.text is not None else sys.stdin.read().strip()
    findings = lint_text(text, args.lang, profile=args.profile)
    for finding in findings:
        print(finding)
    fails = [f for f in findings if f.verdict.value == "fail"]
    flags = [f for f in findings if f.verdict.value == "flag"]
    print(f"{len(fails)} fail, {len(flags)} flag")
    return 1 if fails or (args.strict and flags) else 0


def cmd_sentence_id(args: argparse.Namespace) -> int:
    from .ids import IdError, SentenceId, make_sentence_id

    try:
        if args.make:
            print(make_sentence_id(args.article_id, args.paragraph, args.sentence))
        else:
            sid = SentenceId.parse(args.value)
            print(f"article_id={sid.article_id} paragraph={sid.paragraph} sentence={sid.sentence} "
                  f"group={sid.group} is_title={sid.is_title}")
    except IdError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def cmd_mint_run_id(args: argparse.Namespace) -> int:
    """Mint a run id off the real clock, so no stage has to hand-type a timestamp."""
    from .ids import IdError, mint_run_id

    try:
        print(mint_run_id(args.prefix))
    except IdError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from .export import check_in_sync, write_all

    if args.check:
        stale = check_in_sync()
        if stale:
            print("stale generated files: " + ", ".join(stale), file=sys.stderr)
            print("run: python -m newsab_schema export", file=sys.stderr)
            return 1
        print("dist/ is in sync")
        return 0
    for path in write_all():
        print(path)
    return 0


def cmd_scope_hash(args: argparse.Namespace) -> int:
    """Print the exact scope fingerprint a human approval must bind."""
    try:
        manifest = read_yaml(args.path, TopicManifest)
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(manifest.scope_hash())
    return 0


def cmd_init_topic(args: argparse.Namespace) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id).ensure()
    print(paths.root)
    return 0


def cmd_prepare_run(args: argparse.Namespace) -> int:
    """Create a new, never-before-used stage output directory."""
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id).ensure()
    run_dir = paths.stage_run_dir(args.stage, args.run_id)
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(f"refusing to reuse immutable run directory: {run_dir}", file=sys.stderr)
        return 1
    print(run_dir)
    return 0


def cmd_deactivate_stage(args: argparse.Namespace) -> int:
    """Retire an active routing pointer without deleting its immutable run."""
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    try:
        previous = paths.deactivate(args.stage)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if previous is None:
        print(f"active {args.stage}: already inactive")
    else:
        print(f"deactivated {args.stage}: {previous} (run retained)")
    return 0


def _json_object(raw: str | None, label: str) -> dict:
    if raw is None:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactError(f"{label} must be a JSON object")
    return value


def cmd_finalize_run(args: argparse.Namespace) -> int:
    """Hash a completed run, append its manifest entry, then activate it."""
    from .artifacts import append_manifest, artifact_hashes, run_set_hash
    from .skill_metadata import declared_counters, declared_version, load_skill_frontmatter, skill_md_path

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    # The repo root is derived from the run's own path, never cwd: every caller
    # already passes topics_root, and it is always the repo root's immediate child.
    repo_root = Path(args.topics_root).resolve().parent
    frontmatter = load_skill_frontmatter(repo_root, args.skill_id)
    md_path = skill_md_path(repo_root, args.skill_id)
    try:
        frontmatter_version = declared_version(frontmatter) if frontmatter else None
        if args.skill_version is not None:
            if frontmatter_version is not None and args.skill_version != frontmatter_version:
                raise ValueError(
                    f"--skill-version {args.skill_version!r} does not match "
                    f"{md_path}'s newsab-version {frontmatter_version!r} "
                    f"(skill-id {args.skill_id!r}); pass the frontmatter's value, or "
                    "omit --skill-version to read it automatically, or fix the frontmatter"
                )
            skill_version = args.skill_version
        elif frontmatter_version is not None:
            skill_version = frontmatter_version
        else:
            raise ValueError(
                f"--skill-version is required: no SKILL.md frontmatter found for "
                f"skill-id {args.skill_id!r} (looked for {md_path}); pass --skill-version explicitly"
            )

        counters = _json_object(args.counters_json, "--counters-json")
        if frontmatter is not None:
            known_counters = declared_counters(frontmatter)
            if known_counters is not None:
                unknown = sorted(set(counters) - set(known_counters))
                if unknown:
                    print(
                        f"warning: --counters-json key(s) {unknown} are not listed in "
                        f"{md_path}'s newsab-counters for skill-id {args.skill_id!r}; "
                        "add them there if they are meant to be recomputable/comparable "
                        "across runs, or drop them if they were a one-off",
                        file=sys.stderr,
                    )

        inputs = artifact_hashes(paths, args.input)
        outputs = artifact_hashes(paths, args.output)
        escalations = [Escalation.model_validate(row) for row in _json_object(
            args.escalations_json, "--escalations-json"
        ).get("items", [])]
        gates = [GateRecord.model_validate(row) for row in _json_object(
            args.gates_json, "--gates-json"
        ).get("items", [])]
        stage = args.stage or args.activate
        entry = ManifestEntry(
            skill_id=args.skill_id,
            skill_version=skill_version,
            model_id=args.model_id,
            run_id=args.run_id,
            topic_id=args.topic_id,
            stage=stage,
            status=args.status,
            inputs=list(args.input_run),
            output_set_hash=(
                run_set_hash(paths, stage, args.run_id)
                if stage and args.status == "completed"
                else None
            ),
            input_hashes=inputs,
            output_hashes=outputs,
            counters=counters,
            metadata=_json_object(args.metadata_json, "--metadata-json"),
            escalations=escalations,
            gates=gates,
            timestamp=datetime.now(timezone.utc),
        )
        append_manifest(paths, entry, activate_stage=args.activate)
    except (ArtifactError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"appended {paths.manifest}: {args.run_id}")
    if args.activate:
        print(f"active {args.activate}: {args.run_id}")
    return 0


def cmd_manifest_check(args: argparse.Namespace) -> int:
    from .artifacts import verify_manifest

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    errors = verify_manifest(paths)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"manifest valid: {paths.manifest}")
    return 0


def cmd_record_correction(args: argparse.Namespace) -> int:
    from .artifacts import append_correction

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    try:
        correction = CorrectionMapping.model_validate_json(
            Path(args.mapping).read_text(encoding="utf-8")
        )
        append_correction(paths, correction)
    except (OSError, ValueError, ArtifactError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"appended {paths.corrections}: {correction.correction_id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="newsab-schema",
        description="Validate pipeline artifacts against the blueprint ④ schemas.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable report")
    common.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as failures (use when no judge or human will review this run)",
    )

    p = sub.add_parser("validate-topic", parents=[common], help="validate a whole topic directory")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("--registry", help="sources/registry.yaml; defaults to topics_root's sibling")
    p.set_defaults(func=cmd_validate_topic)

    p = sub.add_parser("validate", parents=[common], help="validate one artifact file")
    p.add_argument("kind", choices=sorted(_KINDS))
    p.add_argument("path")
    p.add_argument("--corpus", help="directory of article JSON files (needed for anchor checks)")
    p.add_argument("--ontology", help="concepts.yaml, to check surface mapping")
    p.add_argument("--angles", help="candidate_angles.jsonl, when validating claims")
    p.add_argument("--questions", help="questions.yaml, required for kind=answers")
    p.add_argument("--topic-id", dest="topic_id", default="", help="required for kind=angles")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("lint", help="lint one string")
    p.add_argument("--text", help="text to lint; omit to read stdin")
    p.add_argument("--lang", required=True)
    p.add_argument("--profile", default="observation_proposition")
    p.add_argument("--strict", action="store_true")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("sentence-id", help="parse or mint a sentence ID")
    p.add_argument("value", nargs="?", default="")
    p.add_argument("--make", action="store_true")
    p.add_argument("--article-id", dest="article_id", default="")
    p.add_argument("--paragraph", type=int, default=0)
    p.add_argument("--sentence", type=int, default=1)
    p.set_defaults(func=cmd_sentence_id)

    p = sub.add_parser(
        "mint-run-id",
        help="mint {prefix}-{UTC microsecond stamp}-{8 hex} for a new stage run",
    )
    p.add_argument("prefix", help="stage run prefix: qst, ans, nrm, edt, rl, …")
    p.set_defaults(func=cmd_mint_run_id)

    p = sub.add_parser("export", help="regenerate dist/ (JSON Schema + enum tables)")
    p.add_argument("--check", action="store_true", help="fail if dist/ is stale instead of writing")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("scope-hash", help="fingerprint the fields approved at touchpoint #1")
    p.add_argument("path", help="topic_manifest.yaml")
    p.set_defaults(func=cmd_scope_hash)

    p = sub.add_parser("init-topic", help="create the topic directory skeleton")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.set_defaults(func=cmd_init_topic)

    p = sub.add_parser("prepare-run", help="create an immutable stage run directory")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("stage", choices=STAGE_NAMES)
    p.add_argument("run_id")
    p.set_defaults(func=cmd_prepare_run)

    p = sub.add_parser(
        "deactivate-stage",
        help="retire an active stage pointer without deleting its immutable run",
    )
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("stage", choices=STAGE_NAMES)
    p.set_defaults(func=cmd_deactivate_stage)

    p = sub.add_parser("finalize-run", help="hash outputs, append manifest, activate run")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("--skill-id", required=True)
    p.add_argument(
        "--skill-version",
        help=(
            "defaults to skills/<skill-id>/SKILL.md's frontmatter newsab-version; an "
            "explicit value must match it, or the run is refused (T-242). Required only "
            "when that SKILL.md cannot be found (e.g. a retired skills/archive/ id)."
        ),
    )
    p.add_argument("--run-id", required=True)
    p.add_argument("--status", choices=("completed", "no_op", "stopped"), default="completed")
    p.add_argument("--model-id")
    p.add_argument("--input", action="append", default=[], help="input file; repeatable")
    p.add_argument(
        "--input-run",
        action="append",
        default=[],
        dest="input_run",
        help="upstream run_id this run consumed; repeatable (R-4)",
    )
    p.add_argument("--output", action="append", default=[], help="output file; repeatable")
    p.add_argument("--stage", choices=STAGE_NAMES,
                   help="the versioned stage this run wrote; defaults to --activate")
    p.add_argument("--activate", choices=STAGE_NAMES)
    p.add_argument(
        "--counters-json",
        help=(
            "keys outside skills/<skill-id>/SKILL.md's frontmatter newsab-counters list "
            "get a warning on stderr, not a rejection (T-242)"
        ),
    )
    p.add_argument("--metadata-json")
    p.add_argument("--escalations-json", help='JSON object: {"items": [...]}')
    p.add_argument("--gates-json", help='JSON object: {"items": [...]}')
    p.set_defaults(func=cmd_finalize_run)

    p = sub.add_parser("manifest-check", help="verify manifest, corrections, and file hashes")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.set_defaults(func=cmd_manifest_check)

    p = sub.add_parser("record-correction", help="append a validated correction mapping")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("mapping", help="CorrectionMapping JSON file")
    p.set_defaults(func=cmd_record_correction)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
