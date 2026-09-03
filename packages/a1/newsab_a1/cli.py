"""``python -m newsab_a1`` — run the statistics layer over a topic.

    qa         Q×A answers + corpus -> ranked findings with strength marks (value chain
               stage 4; the current pipeline's analyze entry point)
    qa-calibrate  read-only threshold sweep over every topic: the candidate-package
               comparison table the user signs (writes nothing into any topic)
    run        observations + corpus -> feature matrix, candidates, metrics (Phase 0)
    gate       apply the R-gate to a run's candidates (retired from the flow by V-1/V-3;
               kept for auditing Phase 0 runs)
    recompute  re-derive an angle set's metrics from a stored run (§4.4.1 invariant 1)
    show       print a run's summary

A1 is not a skill (D10). It is deterministic code invoked by stage scripts and by anyone
auditing a submission.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from newsab_schema.artifacts import append_manifest, artifact_hashes
from newsab_schema.io import ArtifactError, read_jsonl, read_yaml
from newsab_schema.models.analysis import CandidateAngle
from newsab_schema.models.annotation import ConceptOntology, Observation
from newsab_schema.models.manifest import ManifestEntry
from newsab_schema.paths import TopicPaths, source_registry_path
from newsab_schema.store import load_corpus_run, load_registry, load_run_articles
from newsab_schema.validate import validate_angles

from newsab_schema.models.category_map import CategoryMap
from newsab_schema.models.qa import ClusterAnswer, QuestionSet

from .qa_analyze import PACKAGE_VERSION as PACKAGE_QA_VERSION
from .qa_analyze import QAThresholds, analyse_qa, write_qa_run
from .rgate import RGateThresholds, evaluate_all, summarise
from .run import Recomputer, analyse, write_run
from .scan import ScanConfig


def cmd_qa(args: argparse.Namespace) -> int:
    """Analyze the active Q×A answers into the ranked candidate pool."""
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    try:
        corpus_run = load_corpus_run(paths, args.corpus_run_id)
        # The readable universe comes from the article store's ``access_level``
        # (the corpus run record predates the field; its bytes stay untouched).
        access_levels = {
            a.article_id: a.access_level.value
            for a in load_run_articles(paths, corpus_run.run_id)
        }
        if not paths.questions.exists() or not paths.answers.exists():
            print("missing active questions/answers runs — run the annotate stage first", file=sys.stderr)
            return 2
        question_set = read_yaml(paths.questions, QuestionSet)
        answers = read_jsonl(paths.answers, ClusterAnswer)
        # The active normalize-stage category map, when one exists (value_chain stage
        # 3.5).  Analysis without one uses the identity map — legitimate for a topic
        # that has not been normalized yet.
        category_map = None
        if paths.active_run_id("normalization") and paths.category_map.exists():
            category_map = CategoryMap.model_validate_json(
                paths.category_map.read_text(encoding="utf-8")
            )
    except (ArtifactError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    run = analyse_qa(
        question_set,
        answers,
        corpus_run,
        topic_id=args.topic_id,
        thresholds=QAThresholds(),
        category_map=category_map,
        access_levels=access_levels,
        answers_run_id=paths.active_run_id("answers"),
    )
    run_dir = write_qa_run(run, paths.analysis_dir)

    upstream = [corpus_run.run_id]
    for stage in ("questions", "answers", "normalization"):
        run_id = paths.active_run_id(stage)
        if run_id:
            upstream.append(run_id)
    append_manifest(
        paths,
        ManifestEntry(
            skill_id="analyze",
            skill_version=PACKAGE_QA_VERSION,
            model_id=None,
            run_id=run.qa_run_id,
            topic_id=args.topic_id,
            inputs=upstream,
            input_hashes=artifact_hashes(
                paths,
                [paths.questions, paths.answers]
                + ([paths.category_map] if category_map is not None else []),
            ),
            output_hashes=artifact_hashes(
                paths, sorted(p for p in run_dir.rglob("*") if p.is_file())
            ),
            counters={
                "findings": float(len(run.findings)),
                "supported": float(
                    sum(1 for f in run.findings if f.strength.value == "supported")
                ),
                "questions": float(len(run.question_stats)),
            },
            metadata={
                "groups": list(run.groups),
                "thresholds": run.thresholds.to_dict(),
                **run.inputs,
            },
            timestamp=datetime.now(timezone.utc),
        ),
    )

    print(f"qa_run_id   {run.qa_run_id}")
    print(f"corpus_run  {corpus_run.run_id}")
    print(f"groups      {' vs '.join(run.groups)}")
    unreadable = run.inputs.get("unreadable_clusters_excluded") or []
    print(f"universe    {run.inputs['counted_clusters']} readable clusters"
          f" ({len(unreadable)} sampled-but-unreadable excluded)")
    print(f"findings    {len(run.findings)}")
    for f in run.findings:
        flags = "".join(
            marker
            for marker, on in (("m", f.merge_sensitive), ("s", f.total_silence))
            if on
        )
        print(f"  • #{f.rank:02d} [{f.strength.value:11}] {f.kind.value:13} "
              f"{f.question_id}  p={f.stability:.2f}" + (f"  [{flags}]" if flags else ""))
    print(f"written     {run_dir}")
    print(f"manifest    {paths.manifest}")
    return 0


def cmd_qa_calibrate(args: argparse.Namespace) -> int:
    from .qa_calibrate import main as calibrate_main

    argv = [args.topics_root]
    if args.topics:
        argv += ["--topics", *args.topics]
    if args.json_out:
        argv += ["--json", args.json_out]
    return calibrate_main(argv)


def cmd_run(args: argparse.Namespace) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    if not paths.observations.exists():
        print(f"missing {paths.observations}", file=sys.stderr)
        return 2

    registry_path = Path(args.registry) if args.registry else source_registry_path(args.topics_root)
    sources = load_registry(registry_path)
    # A1 analyses the set a corpus run pinned, never "whatever is in the corpus directory"
    # (R-2).  That is what makes a published number recomputable after the corpus grows:
    # the a1 run names its corpus run, and the corpus run names its members and their
    # content hashes.
    try:
        corpus_run = load_corpus_run(paths, args.corpus_run_id)
        articles = load_run_articles(paths, corpus_run.run_id)
    except ArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    observations = read_jsonl(paths.observations, Observation)
    ontology = (
        read_yaml(paths.concepts, ConceptOntology) if paths.concepts.exists() else None
    )
    if ontology is None:
        print(
            "warning: no ontology/concepts.yaml — surface→concept mapping cannot be "
            "validated and the concept map cannot be built (§4.3, R-4); the Δ scan "
            "itself only needs bare/attr features and will proceed",
            file=sys.stderr,
        )

    config = ScanConfig(
        diversity_method=args.diversity,
        n_resamples=args.resamples,
        seed=args.seed,
        interval_level=args.level,
    )
    run = analyse(
        observations,
        articles,
        sources,
        ontology,
        topic_id=args.topic_id,
        groups=tuple(args.groups) if args.groups else None,
        config=config,
    )
    run_dir = write_run(run, paths.analysis_dir)
    input_files = [paths.observations, paths.corpus_run_file(corpus_run.run_id)]
    if paths.concepts.exists():
        input_files.append(paths.concepts)
    upstream = [corpus_run.run_id]
    observations_run = paths.active_run_id("observations")
    if observations_run:
        upstream.append(observations_run)
    ontology_run = paths.active_run_id("ontology")
    if ontology_run and ontology_run not in upstream:
        upstream.append(ontology_run)
    append_manifest(
        paths,
        ManifestEntry(
            skill_id="a1",
            skill_version=run.run_record()["package_version"],
            model_id=None,
            run_id=run.a1_run_id,
            topic_id=args.topic_id,
            inputs=upstream,
            input_hashes=artifact_hashes(paths, input_files),
            output_hashes=artifact_hashes(
                paths, sorted(p for p in run_dir.rglob("*") if p.is_file())
            ),
            counters={
                "matrix_rows": float(run.storage["rows"]),
                "candidates": float(len(run.candidates)),
                "skipped_observations": float(len(run.matrix.skipped)),
            },
            metadata={
                "groups": list(run.groups),
                "config": run.config.to_dict(),
                "corpus_run_id": corpus_run.run_id,
                "corpus_set_hash": corpus_run.set_hash,
                "source_registry": str(registry_path),
            },
            timestamp=datetime.now(timezone.utc),
        ),
    )

    print(f"a1_run_id   {run.a1_run_id}")
    print(f"corpus_run  {corpus_run.run_id} ({len(articles)} articles, {corpus_run.set_hash})")
    print(f"groups      {' vs '.join(run.groups)}")
    print(f"matrix      {json.dumps(run.matrix.summary(), ensure_ascii=False)}")
    print(f"storage     {run.storage['format']} ({run.storage['rows']} rows)")
    if not run.storage["parquet_available"]:
        print(
            "            pyarrow unavailable; wrote CSV instead. The a1_run_id digest is "
            "computed from canonical JSON, so it is unaffected."
        )
    print(f"candidates  {len(run.candidates)}")
    for observation_id, reason in run.matrix.skipped[:10]:
        print(f"  skipped   {observation_id}: {reason}")
    print(f"written     {run_dir}")
    print(f"manifest    {paths.manifest}")
    return 1 if run.matrix.skipped else 0


def _latest_run(paths: TopicPaths) -> Optional[Path]:
    runs = sorted(p for p in paths.analysis_dir.glob("a1-*") if (p / "run.json").exists())
    return runs[-1] if runs else None


def cmd_gate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    candidates_path = run_dir / "candidates.jsonl"
    if not candidates_path.exists():
        print(f"no candidates.jsonl in {run_dir}", file=sys.stderr)
        return 2

    from .scan import load_candidates

    candidates = load_candidates(candidates_path)
    thresholds = RGateThresholds.load(args.thresholds)
    results = evaluate_all(candidates, thresholds, require_calibrated=args.require_calibrated)
    summary = summarise(results)
    print(
        json.dumps(
            {"summary": summary, "results": [r.to_dict() for r in results]},
            ensure_ascii=False,
            indent=2,
        )
    )
    if not thresholds.calibrated:
        print(
            f"note: threshold set {thresholds.thresholds_version} is PROVISIONAL "
            "(calibrated: false) — calibrate before gating",
            file=sys.stderr,
        )
    return 0


def cmd_recompute(args: argparse.Namespace) -> int:
    recomputer = Recomputer(args.run_dir)
    if not recomputer.matrix_is_intact():
        print(
            f"feature matrix in {args.run_dir} does not match the digest recorded in "
            "run.json — the stored analysis has been altered",
            file=sys.stderr,
        )
        return 1
    angles = read_jsonl(args.angles, CandidateAngle)
    # An angle set can legitimately mix A1 runs: under ``angle_carryover: inherit`` (D21) an
    # angle approved at G2 stays published with the numbers from the run it was gated in,
    # while the rest of the set carries the run being checked.  Invariant 1 says each number
    # is re-derived from the run *the angle names*, so resolve that run per angle — as a
    # sibling of the one passed in — rather than failing every carried angle.  An angle whose
    # run is not on disk still fails, which is the point of the check.
    analysis_dir = Path(args.run_dir).resolve().parent
    recomputers = {recomputer.record["a1_run_id"]: recomputer}

    def recompute_for(angle: CandidateAngle):
        a1_run_id = angle.metrics.a1_run_id
        if a1_run_id not in recomputers:
            stored = analysis_dir / a1_run_id
            if not (stored / "run.json").exists():
                raise ValueError(
                    f"angle names a1_run_id={a1_run_id}, whose immutable run is not in "
                    f"{analysis_dir}; its metrics cannot be re-derived"
                )
            recomputers[a1_run_id] = Recomputer(stored)
        return recomputers[a1_run_id](angle)

    report = validate_angles(
        angles, angles[0].topic_id if angles else "", recompute=recompute_for
    )
    print(report.render())
    return report.exit_code()


def cmd_show(args: argparse.Namespace) -> int:
    print(Path(args.run_dir, "run.json").read_text(encoding="utf-8"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="newsab-a1", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("qa", help="Q×A answers -> ranked findings (value chain analyze)")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("--corpus-run-id", dest="corpus_run_id", help="defaults to the active run")
    p.set_defaults(func=cmd_qa)

    p = sub.add_parser(
        "qa-calibrate",
        help="Read-only threshold sweep: the candidate-package table over every topic",
    )
    p.add_argument("topics_root")
    p.add_argument("--topics", nargs="*")
    p.add_argument("--json", dest="json_out")
    p.set_defaults(func=cmd_qa_calibrate)

    p = sub.add_parser("run", help="build the feature matrix and scan for candidates")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("--corpus-run-id", dest="corpus_run_id", help="defaults to the active run")
    p.add_argument("--registry", help="sources/registry.yaml; defaults to topics_root's sibling")
    p.add_argument("--groups", nargs=2, metavar=("A", "B"))
    p.add_argument("--diversity", default="eff_publishers")
    p.add_argument("--resamples", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20260817)
    p.add_argument("--level", type=float, default=0.95, help="central interval mass")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("gate", help="apply the R-gate to a run's candidates")
    p.add_argument("run_dir")
    p.add_argument("--thresholds", help="defaults to the bundled rgate-0.2.yaml")
    p.add_argument(
        "--require-calibrated",
        action="store_true",
        help="refuse to run against a threshold set still marked calibrated: false",
    )
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("recompute", help="re-derive an angle set's metrics from a stored run")
    p.add_argument("run_dir")
    p.add_argument("angles", help="candidate_angles.jsonl")
    p.set_defaults(func=cmd_recompute)

    p = sub.add_parser("show", help="print a run record")
    p.add_argument("run_dir")
    p.set_defaults(func=cmd_show)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
