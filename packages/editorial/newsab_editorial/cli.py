"""``python -m newsab_editorial <command>`` — the deterministic half of write and render.

    page-check   <topics_root> <topic_id> --page P --qa-run D [--langs …]  refusals; exit 1
    page-render  <topics_root> <topic_id> --page P --qa-run D -o OUT       one HTML file

Rendering writes the preview file and stops there.  There is no derived file:// index any
more: the one surface that lists previews is ``python -m newsab_publish dev-serve``, which
serves each of them over http (`AGENTS.md` §4).

The retired S5/S7/S8 interface (``brief`` / ``check`` / ``preview``) is gone with the G2
gate it served: the value chain has exactly two human touchpoints, and a tool that demands
a third gate's ruling before it will speak can only ever block a run that is correct.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from newsab_schema.artifacts import load_manifest
from newsab_schema.io import read_jsonl, read_yaml
from newsab_schema.models.corpus import TopicManifest
from newsab_schema.models.page import ReaderPage
from newsab_schema.models.qa import ClusterAnswer, QuestionSet
from newsab_schema.paths import TopicPaths, source_registry_path
from newsab_schema.store import load_registry, load_run_articles

from .evidence import AnswerIndex
from .page_checks import (
    check_page,
    check_rendered_concept_cloud,
    load_analysis_run,
    load_analysis_thresholds,
    load_pinned_corpus_run,
    load_excluded_clusters,
)
from .page_render import render_page, sentence_load
from .provenance import build_page_components
from .topics_raised import load_topics_by_article


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="newsab_editorial", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("page-check", "page-render"):
        p = sub.add_parser(name)
        p.add_argument("topics_root")
        p.add_argument("topic_id")
        p.add_argument("--page", required=True, help="ReaderPage JSON file")
        p.add_argument("--qa-run", required=True, help="analysis/<qa-run-id> directory")
        if name == "page-check":
            p.add_argument(
                "--langs",
                default="en",
                help="comma-separated languages every reader-facing field must carry",
            )
            p.add_argument(
                "--strict-names",
                action="store_true",
                help="also warn when a multi-word proper name in an explanation "
                "paragraph appears in none of that side's anchored sentences. Off by "
                "default: outlet names and acronyms resolve reliably, ordinary proper "
                "names do not survive into a non-Latin anchor's script and this widens "
                "the check to every Latin-script side.",
            )
        if name == "page-render":
            p.add_argument("-o", "--out", required=True)
            p.add_argument("--lang", default="en")
            p.add_argument(
                "--concept-cloud",
                choices=("categories", "topics_raised"),
                default="topics_raised",
                help="what the concept cloud counts: the annotated answer categories "
                "(the original section) or the collect stage's per-article topic phrases, "
                "counted once per independent report",
            )
            p.add_argument(
                "--appendix",
                choices=("full", "off"),
                default="full",
                help="append the annotation data view (every question, every cluster's "
                "annotated answer). 'off' renders the storyline alone.",
            )
            p.add_argument(
                "--data-assets",
                metavar="SUBDIR",
                default=None,
                help="externalize the language-neutral data islands: write "
                "content-hash-named JSON files into SUBDIR beside the output file and "
                "reference them from the page instead of inlining. Previews are served "
                "over http (dev-serve), so relative references resolve. Omit to inline "
                "everything (standalone document).",
            )

    args = parser.parse_args(argv)

    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)

    page = ReaderPage.model_validate_json(Path(args.page).read_text(encoding="utf-8"))
    articles = load_run_articles(paths)
    manifest = read_yaml(paths.topic_manifest, TopicManifest)
    findings, question_stats = load_analysis_run(Path(args.qa_run))
    answers = AnswerIndex(
        read_jsonl(paths.answers, ClusterAnswer),
        excluded_clusters=load_excluded_clusters(Path(args.qa_run)),
    )
    question_set = read_yaml(paths.questions, QuestionSet)
    topics_by_article = load_topics_by_article(paths)
    if args.command == "page-check":
        report = check_page(
            page,
            articles,
            findings,
            question_stats,
            answers=answers,
            required_langs=tuple(x.strip() for x in args.langs.split(",") if x.strip()),
            pinned_corpus_run=load_pinned_corpus_run(Path(args.qa_run)),
            pinned_qa_run=Path(args.qa_run).name,
            manifest=manifest,
            topics_by_article=topics_by_article,
            # Stage-level only (the run-directory provenance check, the named-outlet/
            # number anchor check, and the non-English-quote translation check): the
            # publish package's own call (``builder.render_locales``, the shared
            # re-render/verify path) omits every one of these, so an already-shipped
            # run predating the provenance stamp, a page with an untranslated quote, or
            # an outlet this check would now ask about never fails ``verify-site`` or a
            # candidate rebuild — only a future write/render-localize run must answer
            # them.
            page_path=Path(args.page),
            paths=paths,
            registry=load_registry(source_registry_path(args.topics_root)),
            strict_names=args.strict_names,
            require_quote_en_translation=True,
        )
        print(report.render())
        return 0 if report.ok else 1
    registry = load_registry(source_registry_path(args.topics_root))
    # The collect stage's reading notes: an article's keywords in its record card, and —
    # on the trial source — what the whole cloud counts.  Absent for a corpus built
    # before the artifact existed, in which case both simply do not appear.
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    data_subdir = args.data_assets
    if data_subdir is not None and (
        not data_subdir
        or data_subdir.startswith(("/", "."))
        or "/" in data_subdir
        or "\\" in data_subdir
    ):
        print(f"--data-assets must be a plain subdirectory name: {data_subdir!r}", file=sys.stderr)
        return 1
    collected_assets: dict[str, bytes] = {}
    page_components = build_page_components(page, manifest, load_manifest(paths))
    html, shipped, withheld = render_page(
        page,
        articles,
        manifest,
        question_stats,
        lang=args.lang,
        findings=findings,
        answers=answers,
        question_set=question_set,
        registry=registry,
        thresholds=load_analysis_thresholds(Path(args.qa_run)),
        appendix=args.appendix == "full",
        return_shipped=True,
        topics_by_article=topics_by_article,
        cloud_source=args.concept_cloud,
        page_components=page_components,
        data_assets_base=data_subdir,
        assets_out=collected_assets if data_subdir is not None else None,
    )
    # The concept cloud is the one section whose numbers are computed at render time, so
    # it is the one section no earlier check can have seen.  Recompute it from the pinned
    # run and hold the finished HTML to it — before the file is written, so a mismatch
    # never reaches a reviewer's browser.
    cloud = check_rendered_concept_cloud(
        html,
        question_stats,
        [g.group_id for g in manifest.groups],
        source=args.concept_cloud,
        topics_by_article=topics_by_article,
        articles=articles,
    )
    if not cloud.ok:
        print(cloud.render(), file=sys.stderr)
        return 1
    out.write_text(html, encoding="utf-8")
    if data_subdir is not None:
        data_dir = out.parent / data_subdir
        data_dir.mkdir(parents=True, exist_ok=True)
        for name, blob in sorted(collected_assets.items()):
            island = name.split(".", 1)[0]
            # A fix round legitimately re-renders with changed bytes; the run is not
            # finalized yet, so the superseded same-island file is replaced rather than
            # left to 404 confusion or immortalization in the run fingerprint.
            for stale in sorted(data_dir.glob(f"{island}.*.json")):
                if stale.name != name:
                    stale.unlink()
                    print(f"replaced stale data asset: {stale.name}")
            data_dir.joinpath(name).write_bytes(blob)
            print(data_dir / name)
    print(out)
    for key, value in sorted(cloud.stats.items()):
        print(f"{key}: {value}")
    load = sentence_load(articles, shipped)
    if load:
        article_id, (used, total) = max(
            load.items(), key=lambda kv: (kv[1][0] / kv[1][1] if kv[1][1] else 0, kv[0])
        )
        # Non-negotiable 7 is a rule about full text, not a sentence budget — but an
        # appendix that shows every anchor adds up, so the worst case goes on the
        # record rather than being assumed harmless.
        print(
            f"sentences shipped: {sum(u for u, _ in load.values())} across "
            f"{len(load)} article(s); heaviest {article_id} {used}/{total} "
            f"({100 * used / total:.0f}% of its sentences)"
        )
    if withheld:
        print(
            f"anchors listed by address only (article display budget): "
            f"{sum(withheld.values())} across {len(withheld)} article(s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
