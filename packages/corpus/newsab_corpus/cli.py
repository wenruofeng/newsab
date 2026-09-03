"""``python -m newsab_corpus`` — build a Phase 0 corpus from staged articles.

    fetch     take publisher pages honestly: one identity, our robots group, browser retry
    build     staging YAML -> append-only article store + a corpus run (set snapshot)
    withdraw  exclude an article from future runs, with a reason, without deleting it
    stats     recompute the dual-unit statistics for a stored run
    similar   list the most similar article pairs (for tuning the cluster threshold)
    segment   split one text file, to eyeball the sentence boundaries

What ``build`` produces changed in the 2026-08-18 refactor (R-2).  It used to copy the
whole corpus tree into ``corpus/versions/<run_id>/``, so adding one article meant a new
copy of everything and a full re-annotation downstream.  It now writes new articles into
one append-only store and records a :class:`CorpusRun` — which members this build saw, each
member's content hash, the cluster assignment and the fingerprint of the set.  Adding an
article costs one file plus one new run; every existing annotation stands.

Exit codes: ``0`` clean, ``1`` the corpus has a problem a human must resolve, ``2`` usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from pydantic import ValidationError

from newsab_schema.artifacts import (
    append_manifest,
    artifact_hashes,
    load_manifest,
    run_set_hash,
)
from newsab_schema.common import Provenance
from newsab_schema.ids import group_id_of, make_article_id
from newsab_schema.io import ArtifactError, read_yaml, write_json
from newsab_schema.models.corpus import (
    BACKFILL_RETRY_BUDGET,
    Article,
    BackfillDebt,
    CorpusRun,
    RunArticle,
    SourceEntry,
    TopicManifest,
    article_content_hash,
    compute_set_hash,
)
from newsab_schema.models.manifest import Escalation, ManifestEntry
from newsab_schema.paths import TopicPaths, source_registry_path
from newsab_schema.sources import registry_entry_problems
from newsab_schema.store import (
    find_article,
    load_corpus_run,
    load_registry,
    load_withdrawn,
    put_article,
    restore_set,
    save_registry,
    store_articles,
    withdraw_article,
    write_corpus_run,
)

from .build_diagnostics import check_staged_snapshot_verbatim
from .cluster import DEFAULT_THRESHOLD, assign_clusters, similarity_matrix
from .fetch import build_fetch_parser
from .index import build_index, compute_stats
from .registry_cli import build_registry_parser
from .segment import SPLITTER_VERSION, SUPPORTED_LANGS, segment
from .staging import StagingError, build_articles, load_staging, rewrite_clusters

PACKAGE_VERSION = "0.6.0"


def _run_id(prefix: str, payload: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{stamp}-{digest}"


def _previous_debts(paths: TopicPaths) -> list[BackfillDebt]:
    """The newest existing build's ``backfill_debt`` — what this build inherits.

    The newest run rather than the active one: a build that ended ``stopped`` never moved
    the pointer, but the debts it recorded are still owed.  Run ids embed a UTC stamp of
    either 12 or 20 digits, so ordering parses the stamp instead of trusting the name.
    """
    versions = paths.stage_versions_dir("corpus")
    if not versions.is_dir():
        return []
    candidates: list[tuple[datetime, str, Path]] = []
    for run_dir in versions.iterdir():
        record = run_dir / "corpus_run.json"
        parts = run_dir.name.split("-")
        if not record.is_file() or len(parts) != 3 or not parts[1].isdigit():
            continue
        fmt = {12: "%Y%m%d%H%M", 20: "%Y%m%d%H%M%S%f"}.get(len(parts[1]))
        if fmt is None:
            continue
        started = datetime.strptime(parts[1], fmt).replace(tzinfo=timezone.utc)
        candidates.append((started, run_dir.name, record))
    if not candidates:
        return []
    _, _, record = max(candidates)
    return CorpusRun.model_validate_json(record.read_text(encoding="utf-8")).backfill_debt


def _sentence_map(article: "Article") -> dict[str, str]:
    return {
        f"P{paragraph.index:02d}:S{sentence.index:02d}": sentence.text
        for paragraph in article.structured_text
        for sentence in paragraph.sentences
    }


def annotated_baseline(paths: TopicPaths) -> dict[str, "Article"]:
    """The article content the topic's **active answers** were actually written against.

    "Has this anchor moved" is only meaningful relative to the generation the annotations
    were made on, and that is not necessarily the previous file in the store.  Rebuild
    twice before re-annotating — the ordinary shape of a backfill, where the first build
    reveals a defect the second one fixes — and a delta measured against the store reports
    only the second hop, silently dropping the drift the annotations actually suffer from.

    So the baseline is resolved through the dependency edge the manifest already records:
    active answers run -> the corpus run it consumed -> that run's pinned content.  It is
    also self-clearing, which a carried-forward warning would not be: minting an answers
    run against the new corpus moves the baseline and the delta goes empty on its own.
    """
    answers_run = paths.active_run_id("answers")
    if not answers_run:
        return {}
    versions_dir = paths.stage_versions_dir("corpus")
    corpus_versions = {d.name for d in versions_dir.iterdir()} if versions_dir.is_dir() else set()
    pinned: Optional[str] = None
    for entry in load_manifest(paths):
        if entry.stage == "answers" and entry.run_id == answers_run:
            pinned = next((i for i in entry.inputs if i in corpus_versions), None)
            break
    if pinned is None:
        return {}
    run = load_corpus_run(paths, pinned)
    out: dict[str, Article] = {}
    for member in run.articles:
        article = find_article(paths, member.article_id, member.content_hash)
        if article is not None:
            out[member.article_id] = article
    return out


def anchor_delta(before: "Article", after: "Article") -> dict[str, list[str]]:
    """Which sentence IDs a rebuild removed, added, or **kept while changing their text**.

    The third list is the dangerous one and the reason this function exists.  A removed
    anchor is caught downstream — ``validate_answers`` reports ``dangling_anchor`` because
    the ID no longer resolves.  A *retexted* anchor resolves perfectly and now points at a
    different sentence, so every gate in the pipeline passes while a published quote
    silently changes what it says.  Nothing else in the repo can see this: answers store
    bare sentence IDs, never the text they were written against.

    Only the build can compare the two generations, so the build records them.
    """
    old_map, new_map = _sentence_map(before), _sentence_map(after)
    return {
        "removed": sorted(set(old_map) - set(new_map)),
        "added": sorted(set(new_map) - set(old_map)),
        "retexted": sorted(k for k in set(old_map) & set(new_map) if old_map[k] != new_map[k]),
    }


def _write_index(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def _register_from_staging(registry, entry):
    """Add an outlet the collector met but nobody had registered yet (R-3).

    An unknown ``source_id`` used to stop the build and become a decision for the user.
    That made "we found an in-scope article in an outlet not on the list" — the *normal*
    outcome of an open source frame (D19) — an exceptional event.  The *collector*
    classifies it at collection time instead.

    The words come from the collector rather than from the build.  The build used to
    synthesise the entry: the source_id stood in for the masthead, the front page was
    guessed from the article's host, ownership and access got placeholders, and
    ``auto_added: true`` promised a human pass that nobody was ever going to make.  The
    registry has no human tier now, so the entry is assembled from what the collector
    actually wrote in staging, and :class:`StagingArticle` refuses a half-filled
    registration block before the build ever gets here.
    """
    names = {"en": entry.source_name_en, "zh-CN": entry.source_name_zh}
    if entry.source_name_native:
        names[entry.lang] = entry.source_name_native
    new = SourceEntry.model_validate(
        {
            "id": entry.source_id,
            "name": {"values": names},
            "url": entry.source_url,
            "lang": entry.lang,
            "country": entry.source_country,
            "category": entry.source_category.value,
            "beat_scope": entry.source_beat_scope,
            "notes": {"values": {"en": entry.source_notes_en, "zh-CN": entry.source_notes_zh}},
        }
    )
    return registry.with_source(new), new


def cmd_build(args: argparse.Namespace) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id).ensure()
    staging_dir = Path(args.staging or paths.corpus_dir / "staging")
    if not staging_dir.exists():
        print(f"no staging directory: {staging_dir}", file=sys.stderr)
        return 2
    if not paths.topic_manifest.exists():
        print(f"missing {paths.topic_manifest} — define the topic first (S0)", file=sys.stderr)
        return 2

    manifest = read_yaml(paths.topic_manifest, TopicManifest)
    approval_problem = manifest.scope_approval_problem()
    if approval_problem:
        print(
            "collect blocked at human touchpoint #1: " + approval_problem,
            file=sys.stderr,
        )
        return 1
    registry_path = Path(args.registry) if args.registry else source_registry_path(args.topics_root)
    registry = load_registry(registry_path)

    try:
        staged = load_staging(staging_dir)
    except StagingError as exc:
        print(exc, file=sys.stderr)
        return 1
    if not staged:
        print(f"{staging_dir} contains no staged articles", file=sys.stderr)
        return 2

    # --- validate explicit group judgements; register unknown outlets -------------------
    warnings: list[str] = []
    registered: list[str] = []
    for path, entry in staged:
        group = manifest.group_by_id(entry.group_id)
        if group is None:
            print(
                f"{path}: group_id {entry.group_id!r} is absent from "
                f"{paths.topic_manifest}; judge membership against a declared definition",
                file=sys.stderr,
            )
            return 1
        if registry.get(entry.source_id) is None:
            if entry.source_country is None:
                print(
                    f"{path}: source {entry.source_id!r} is not in {registry_path}. Fill "
                    "this staging record's registration block (source_country, source_url, "
                    "source_name_en/zh, source_category, source_beat_scope, "
                    "source_notes_en/zh) — the registry has no human confirmation tier, so "
                    "the agent that meets an outlet is the one that describes it",
                    file=sys.stderr,
                )
                return 1
            try:
                registry, added = _register_from_staging(registry, entry)
            except ValidationError as exc:
                print(f"{path}: cannot register {entry.source_id!r}: {exc}", file=sys.stderr)
                return 1
            registered.append(added.id)
            warnings.append(
                f"{added.id}: registered in {registry_path} as "
                f"{added.category.value}/{added.beat_scope} from this run's staging"
            )
            for problem in registry_entry_problems(added):
                warnings.append(f"{added.id}: {problem}")
    if registered:
        save_registry(registry_path, registry)

    # The topic pins its own threshold when it has one: it sets the D7 denominator, and a
    # rebuild that quietly fell back to the package default would move every prevalence
    # figure without anyone deciding to.
    threshold = args.threshold if args.threshold is not None else (
        manifest.cluster_threshold if manifest.cluster_threshold is not None else DEFAULT_THRESHOLD
    )
    if args.threshold is not None and args.threshold != manifest.cluster_threshold:
        # A CLI override the manifest does not pin is a denominator that exists only in
        # this invocation: the next bare build silently reverts to the pinned/default
        # value and moves every prevalence figure (measured: 0.94 vs the 14-cluster default).
        fallback = (
            manifest.cluster_threshold
            if manifest.cluster_threshold is not None
            else DEFAULT_THRESHOLD
        )
        warnings.append(
            f"cluster_threshold {threshold} came from --threshold and is not pinned in "
            f"topic_manifest.yaml (manifest: {manifest.cluster_threshold}); a rebuild "
            f"without the flag will use {fallback} and move every denominator. Pin it in "
            "the manifest (the field is outside the signed surface — the collecting "
            "agent's call) or drop the flag."
        )

    build_payload = json.dumps(
        {
            "staging": [
                {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path, _ in staged
            ],
            "splitter_version": SPLITTER_VERSION,
            "cluster_threshold": threshold,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    run_id = _run_id("s2s", build_payload)

    articles, build_warnings, residue_removed = build_articles(
        staged, topic_id=args.topic_id, run_id=run_id
    )
    warnings.extend(build_warnings)
    snapshot_verbatim = check_staged_snapshot_verbatim(
        staged, articles, paths.corpus_dir / "raw"
    )
    warnings.extend(snapshot_verbatim.warnings())

    # The collector's topic-centrality judgement, keyed by the article it was made
    # about.  Anything in the store that no staging file claims stays `core` — an unlabelled
    # article is a counted article, so a lost label can never silently shrink a denominator.
    relevance = {
        make_article_id(entry.group_id.upper(), entry.url): entry.topic_relevance
        for _, entry in staged
    }

    # --- the append-only store ---------------------------------------------------------
    # Articles already present keep their bytes, so their content hashes — and every S4
    # anchor into them — survive a rebuild untouched.  That is the whole point of R-2.
    # Read the previous generation before writing, so the two can be compared.  A record
    # can change without any sentence moving — that is the normal effect of a mechanism
    # change — and conflating the two is what turns an incremental rebuild into a full
    # re-annotation (see PutResult).
    previous = store_articles(paths)
    # …but "moved" is relative to what the existing annotations were written against, which
    # is one generation further back whenever a backfill rebuilds more than once.
    baseline = annotated_baseline(paths) or previous
    results = {article.article_id: put_article(paths, article) for article in articles}
    superseded = sorted(aid for aid, kind in results.items() if kind == "superseded")
    revised = sorted(aid for aid, kind in results.items() if kind == "revised")
    deltas: dict[str, dict[str, list[str]]] = {}
    for article in articles:
        was = baseline.get(article.article_id)
        if was is None:
            continue
        delta = anchor_delta(was, article)
        if any(delta.values()):
            deltas[article.article_id] = delta
    # An article the annotations were written against on an older generation can be
    # `unchanged` against the store and still have moved since then.
    superseded = sorted(set(superseded) | set(deltas))
    revised = sorted(aid for aid in revised if aid not in deltas)
    for article_id in superseded:
        delta = deltas.get(article_id) or {"removed": [], "added": [], "retexted": []}
        warnings.append(
            f"{article_id}: re-collected with different sentences "
            f"(-{len(delta['removed'])} +{len(delta['added'])} "
            f"~{len(delta['retexted'])} retexted); the previous content was archived under "
            "corpus/articles/_superseded/ so earlier runs stay restorable"
        )
        if delta["retexted"]:
            warnings.append(
                f"{article_id}: {len(delta['retexted'])} sentence ID(s) kept their address "
                "while their text changed — an anchor on one of these still resolves and "
                "now quotes something else, which no downstream check can see. Re-read "
                "every answer citing: " + " ".join(delta["retexted"])
            )
    if revised:
        warnings.append(
            f"{len(revised)} article record(s) changed without any sentence moving "
            "(splitter version, origin, access level or the like). Their anchors all still "
            "resolve, so no annotation needs redoing"
        )

    stored = store_articles(paths)
    withdrawn = load_withdrawn(paths)
    withdrawn_ids = {w.article_id for w in withdrawn}
    members = [stored[aid] for aid in sorted(stored) if aid not in withdrawn_ids]
    if not members:
        print("every article in the store is withdrawn; nothing to analyse", file=sys.stderr)
        return 1

    assignment = assign_clusters(members, threshold=threshold)
    members = rewrite_clusters(members, assignment.cluster_ids)
    warnings.extend(assignment.warnings)

    cluster_relevance: dict[str, str] = {}
    for article in members:
        label = relevance.get(article.article_id, "core")
        if cluster_relevance.get(article.reporting_cluster_id) != "core":
            cluster_relevance[article.reporting_cluster_id] = label

    stats = compute_stats(
        members,
        registry,
        topic_id=args.topic_id,
        declared_groups=[g.group_id for g in manifest.groups],
        cluster_relevance=cluster_relevance,
    )
    for group, entry in sorted(stats.groups.items()):
        if entry.peripheral_clusters:
            warnings.append(
                f"{group}: {entry.peripheral_clusters} cluster(s) labelled peripheral. "
                "That label excludes nothing — analyze counts every "
                "cluster — so it is a note about how this corpus was judged, not about its "
                "denominator"
            )
    for group in stats.denominator_wipeouts:
        entry = stats.groups[group]
        warnings.append(
            f"DENOMINATOR WIPEOUT — {group}: all {entry.independent_clusters} of this "
            "side's independent clusters are labelled peripheral, so every prevalence "
            "denominator on this side is zero. This is not silence: the media published "
            "and our own labels removed them. A page built on this would report that the "
            "side addressed nothing — a finding manufactured by the labelling. Re-read the "
            "relevance calls against the manifest's include criteria (a whole side going "
            "peripheral usually means the label was judged against the other side's "
            "framing), or change scope — do not proceed on the labels as they stand"
        )
    if stats.peripheral_imbalance:
        rates = ", ".join(f"{g} {rate:.0%}" for g, rate in stats.peripheral_imbalance)
        warnings.append(
            f"the two sides lose very different shares of their sample to the peripheral "
            f"label ({rates}); relevance is a per-side denominator lever, so an asymmetry "
            "here moves every cross-side comparison on the page. Confirm it is a fact "
            "about the samples and not about who judged them"
        )
    if stats.beat_imbalance:
        shares = ", ".join(f"{g} {share:.0%}" for g, share in stats.beat_imbalance)
        warnings.append(
            f"beat composition differs across the sides (vertical/trade share: {shares}); "
            "the two samples are made of different kinds of newsroom. Top up the side that "
            "is missing that kind rather than adding volume anywhere"
        )

    # Debt is a ledger, not a note.  Every debt on the newest previous run rolls
    # forward into this one; the three flags below are the only exits, so an extend or
    # repair run can no longer shed the previous round's debt by simply not restating it
    # (the aabb-garden-wind-2026 failure: search-strategy §1).
    inherited = {d.key: d for d in _previous_debts(paths)}
    closed = set(getattr(args, "close_debt", []))
    retried = set(getattr(args, "retry_debt", []))
    futile = set(getattr(args, "futile_debt", []))

    debts = []
    new_keys: set[str] = set()
    for spec in getattr(args, "backfill_debt", []):
        source_id, _, rest = spec.partition(":")
        cell, _, reason = rest.partition(":")
        if not (source_id and cell and reason):
            print(f"--backfill-debt must be SOURCE:CELL:REASON, got {spec!r}", file=sys.stderr)
            return 2
        key = f"{source_id}:{cell}"
        if key in inherited:
            print(
                f"--backfill-debt {key} is already owed by the previous run; it rolls "
                f"forward on its own — use --retry-debt, --close-debt or --futile-debt",
                file=sys.stderr,
            )
            return 2
        new_keys.add(key)
        debts.append(
            BackfillDebt(source_id=source_id, cell=cell, reason=reason, retry_futile=key in futile)
        )
    for flag, keys in (("--close-debt", closed), ("--retry-debt", retried)):
        for key in sorted(keys - set(inherited)):
            print(f"{flag} {key}: no such debt on the previous run", file=sys.stderr)
            return 2
    for key in sorted(futile - new_keys - set(inherited)):
        print(f"--futile-debt {key}: no such debt, inherited or declared", file=sys.stderr)
        return 2
    for key in sorted(set(inherited) - closed):
        debt = inherited[key]
        update: dict[str, object] = {}
        if key in retried:
            update["retries"] = debt.retries + 1
        if key in futile:
            update["retry_futile"] = True
        debts.append(debt.model_copy(update=update) if update else debt)
    if debts:
        fresh = sum(1 for d in debts if not d.budget_exhausted)
        warnings.append(
            f"backfill debt: {len(debts)} cell(s) still owed, {fresh} with retry budget "
            f"remaining — annotate's preflight refuses this corpus until every budget is "
            f"spent (targeted retries only, search-strategy §1b routing)"
        )

    run = CorpusRun(
        run_id=run_id,
        topic_id=args.topic_id,
        articles=[
            RunArticle(
                article_id=article.article_id,
                source_id=article.source_id,
                content_hash=article_content_hash(article),
                reporting_cluster_id=article.reporting_cluster_id,
                topic_relevance=relevance.get(article.article_id, "core"),
            )
            for article in sorted(members, key=lambda a: a.article_id)
        ],
        withdrawn=withdrawn,
        set_hash=compute_set_hash(
            {a.article_id: article_content_hash(a) for a in members}
        ),
        splitter_version=SPLITTER_VERSION,
        cluster_threshold=assignment.threshold,
        cluster_shingle_n=assignment.shingle_n,
        cluster_han_fold=assignment.han_fold,
        backfill_debt=debts,
        build_report={
            "cluster_members": assignment.members,
            "stats": stats.to_dict(),
            "sources_covered": sorted({a.source_id for a in members}),
            "auto_registered_sources": registered,
            # Report-only extraction audit.  This neither changes the built
            # sentences nor blocks activation; it makes the previously manual Ctrl-F
            # check inspectable per sentence against the retained publisher snapshot.
            "staged_snapshot_verbatim": snapshot_verbatim.to_dict(),
            # Audit trail of residue stripping: {article_id: [[rule, line], ...]}.
            "residue_removed": {
                aid: [[rule, line] for rule, line in removed]
                for aid, removed in sorted(residue_removed.items())
            },
            # Per-article sentence-ID delta for every article whose text actually moved.
            # `retexted` is what `validate_answers` reads to refuse a silently re-pointed
            # anchor; the other two lists are there so a reviewer can see the whole change.
            "anchor_delta": {aid: deltas[aid] for aid in sorted(deltas)},
            "revised_articles": revised,
        },
        warnings=warnings,
        provenance=Provenance(
            skill_version=f"S2build-{PACKAGE_VERSION}",
            model_id=None,
            run_id=run_id,
            timestamp=datetime.now(timezone.utc),
        ),
    )

    run_dir = paths.stage_run_dir("corpus", run_id)
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(f"refusing to overwrite immutable corpus run {run_dir}", file=sys.stderr)
        return 1
    write_corpus_run(paths, run)
    _write_index(run_dir / "index.jsonl", build_index(members, registry))

    blocking = [w for w in warnings if "declared" in w and "origin=original" in w]
    blocking += [w for w in warnings if w.startswith("DENOMINATOR WIPEOUT")]
    append_manifest(
        paths,
        ManifestEntry(
            skill_id="newsab-corpus/build",
            skill_version=PACKAGE_VERSION,
            model_id=None,
            run_id=run_id,
            topic_id=args.topic_id,
            stage="corpus",
            status="stopped" if blocking else "completed",
            output_set_hash=None if blocking else run_set_hash(paths, "corpus", run_id),
            input_hashes=artifact_hashes(
                paths,
                [path for path, _ in staged] + snapshot_verbatim.snapshot_paths,
            ),
            counters={
                "articles": float(len(members)),
                "reporting_clusters": float(assignment.cluster_count),
                "new_articles": float(sum(1 for k in results.values() if k == "new")),
                "revised_articles": float(len(revised)),
                "superseded_articles": float(len(superseded)),
                "withdrawn": float(len(withdrawn)),
                "warnings": float(len(warnings)),
                "raw_snapshots_checked": float(snapshot_verbatim.checked_articles),
                "staged_sentences_checked": float(snapshot_verbatim.checked_sentences),
                "staged_sentences_not_found": float(
                    len(snapshot_verbatim.sentences_not_found)
                ),
            },
            metadata={
                "splitter_version": SPLITTER_VERSION,
                "cluster_threshold": assignment.threshold,
                "cluster_han_fold": assignment.han_fold,
                "source_registry": str(registry_path),
                "sources_covered": run.source_ids,
            },
            escalations=[
                Escalation(kind="origin_consistency", detail=warning) for warning in blocking
            ],
            timestamp=datetime.now(timezone.utc),
        ),
        activate_stage=None if blocking else "corpus",
    )

    print(f"run_id            {run_id}")
    print(f"set_hash          {run.set_hash}")
    print(f"articles          {len(members)} -> {assignment.cluster_count} reporting clusters")
    print(
        f"store             {sum(1 for k in results.values() if k == 'new')} new, "
        f"{sum(1 for k in results.values() if k == 'unchanged')} unchanged, "
        f"{len(revised)} revised (record changed, sentences did not), "
        f"{len(superseded)} superseded, {len(withdrawn)} withdrawn"
    )
    if run.backfill_debt:
        print(f"backfill debt     {len(run.backfill_debt)} cell(s) owed")
        for debt in run.backfill_debt:
            state = (
                "retry_futile" if debt.retry_futile
                else f"retries {debt.retries}/{BACKFILL_RETRY_BUDGET}"
            )
            spent = " — budget spent" if debt.budget_exhausted else ""
            print(f"  {debt.key}: {state}{spent}")
    for group, group_stats in sorted(stats.groups.items()):
        homogeneity = group_stats.homogeneity
        shown = "n/a" if homogeneity is None else f"{homogeneity:.2f}"
        print(
            f"  {group}: {group_stats.publication_instances} instances / "
            f"{group_stats.independent_clusters} clusters, the denominator "
            f"({group_stats.core_clusters} of them labelled core) "
            f"(homogeneity {shown})"
        )
        languages = ", ".join(
            f"{lang} {bucket['instances']} instance(s) / {bucket['clusters']} cluster(s)"
            for lang, bucket in sorted(group_stats.by_language.items())
        )
        if languages:
            print(f"    languages: {languages}")
    # A cluster whose every member is title+lead only cannot answer most questions, so its
    # silence downstream is a retrieval limit, not editorial attention.  Say so here, where
    # it originates, rather than letting annotate meet it as an unexplained low addressed
    # rate (aabb-market-meal-2024: 10 of 38 de clusters, 0 of 30 tr — a 26-point one-sided hole).
    partial_only: dict[str, set[str]] = {}
    full_seen: dict[str, set[str]] = {}
    for member in members:
        level = getattr(member.access_level, "value", member.access_level)
        bucket = full_seen if level != "partial" else partial_only
        bucket.setdefault(group_id_of(member.article_id), set()).add(
            assignment.cluster_ids[member.article_id]
        )
    for group in sorted(partial_only):
        blind = partial_only[group] - full_seen.get(group, set())
        if blind:
            total = len(partial_only[group] | full_seen.get(group, set()))
            print(
                f"  partial: {group} has {len(blind)} of {total} cluster(s) captured as "
                f"title+lead only; their silence is retrieval, not attention"
            )
    for group, category, n, required in stats.thin_categories:
        print(f"  thin: {group}/{category} has {n} cluster(s), needs {required} to be compared")
    for group, lang, n, total, share in stats.thin_languages:
        print(
            f"  thin-language: {group}/{lang} is {n}/{total} publication instance(s) "
            f"({share:.0%}); report-only observed-language heuristic, not a quota or gate"
        )
    for group in stats.silent_groups:
        print(f"  silence: group {group} has no independent reporting in this corpus")
    print(
        f"raw verbatim      {snapshot_verbatim.checked_articles}/"
        f"{snapshot_verbatim.staged_articles} staged article snapshot(s), "
        f"{snapshot_verbatim.checked_sentences} body sentence(s) checked, "
        f"{len(snapshot_verbatim.sentences_not_found)} not found, "
        f"{len(snapshot_verbatim.missing_snapshots)} snapshot(s) missing (report-only)"
    )
    for warning in warnings:
        print(f"  warn: {warning}")
    print(f"written           {paths.corpus_run_file(run_id)}, {run_dir / 'index.jsonl'}")
    print(f"store             {paths.articles_dir} (PRIVATE)")
    print(f"manifest          {paths.manifest}")

    # Extending a corpus that has already been annotated is now routine rather than an
    # error (R-2): existing article records keep their bytes, so existing observations
    # keep their anchors.  Say exactly which articles the next S4 pass has to cover.
    # These two lines used to be gated on `paths.observations.exists()` — the Phase 0 S4
    # artifact that V-2 retired.  No live topic has one, so the pipeline's only statement
    # of what a rebuild costs downstream never printed at all.  The gate is now the
    # annotation layer that actually exists.
    annotated = paths.answers.exists() or paths.observations.exists()
    fresh = sorted(aid for aid, kind in results.items() if kind == "new")
    if fresh and annotated:
        print(
            f"incremental       {len(fresh)} new article(s) need annotating; the rest of "
            f"the existing answers carry over unchanged:\n                  "
            + " ".join(fresh)
        )
    if revised and annotated:
        print(
            f"carry forward     {len(revised)} article record(s) changed but no sentence "
            "moved; every existing anchor still resolves and no answer needs redoing"
        )
    if superseded and annotated:
        print(
            f"re-annotate       {len(superseded)} article(s) changed text; every answer "
            "anchoring into them must be redone: " + " ".join(superseded)
        )
        retexted = {aid: d["retexted"] for aid, d in deltas.items() if d["retexted"]}
        if retexted:
            print(
                "  silent drift    these sentence IDs kept their address and changed their "
                "text; an anchor on one resolves and now quotes something else:"
            )
            for aid, ids in sorted(retexted.items()):
                print(f"                  {aid}: {' '.join(ids)}")

    # Thin categories and silence are findings, not failures — they are what the page
    # reports.  Origin-consistency warnings, however, mean the cluster count is unreliable.
    return 1 if blocking else 0


def cmd_withdraw(args: argparse.Namespace) -> int:
    """Exclude an article from future runs without deleting it (R-2)."""
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    if not paths.article_file(args.article_id).exists():
        print(f"no such article in the store: {args.article_id}", file=sys.stderr)
        return 2
    entry = withdraw_article(paths, args.article_id, args.reason)
    print(f"withdrawn {entry.article_id}: {entry.reason}")
    print("rebuild to mint a run that excludes it; earlier runs keep referencing it")
    return 0


def _run_articles(paths: TopicPaths, run_id: Optional[str]):
    run = load_corpus_run(paths, run_id)
    articles, errors = restore_set(paths, run)
    if errors:
        raise ArtifactError(f"corpus run {run.run_id} cannot be restored: " + "; ".join(errors))
    return run, articles


def cmd_stats(args: argparse.Namespace) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    manifest = read_yaml(paths.topic_manifest, TopicManifest)
    registry_path = Path(args.registry) if args.registry else source_registry_path(args.topics_root)
    _, articles = _run_articles(paths, args.run_id)
    stats = compute_stats(
        articles,
        load_registry(registry_path),
        topic_id=args.topic_id,
        declared_groups=[g.group_id for g in manifest.groups],
    )
    print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_similar(args: argparse.Namespace) -> int:
    paths = TopicPaths.for_topic(args.topics_root, args.topic_id)
    _, articles = _run_articles(paths, args.run_id)
    rows = similarity_matrix(articles)
    print(f"{'a':<14} {'b':<14} {'containment':>12} {'jaccard':>9}")
    for a, b, cont, jac in rows[: args.limit]:
        print(f"{a:<14} {b:<14} {cont:>12.3f} {jac:>9.3f}")
    return 0


def cmd_segment(args: argparse.Namespace) -> int:
    text = Path(args.path).read_text(encoding="utf-8") if args.path else sys.stdin.read()
    result = segment(text, args.lang)
    for pi, paragraph in enumerate(result.paragraphs, start=1):
        for si, sentence in enumerate(paragraph, start=1):
            print(f"P{pi:02d}:S{si:02d}  {sentence}")
    paragraphs = len(result.paragraphs) or 1
    ratio = result.sentence_count / paragraphs
    print(
        f"-- {result.sentence_count} sentences over {paragraphs} paragraph(s) "
        f"({ratio:.1f} per paragraph), splitter {result.splitter_version}"
    )
    if result.used_fallback:
        print(
            f"-- FALLBACK: {args.lang!r} has no tuned rules (tuned: "
            f"{', '.join(SUPPORTED_LANGS)}); splitting on terminator-plus-whitespace"
        )
    if ratio < 1.5:
        # The failure mode this exists to catch: a language whose terminators carry no
        # trailing space comes back one sentence per paragraph, and every downstream
        # artifact stays valid while every quote silently becomes a whole paragraph.
        print(
            "-- WARNING: barely more sentences than paragraphs. If this text is ordinary "
            "news prose the splitter is not splitting it — do not build a corpus on this "
            "language until it has rules."
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="newsab-corpus", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    registry_flag = argparse.ArgumentParser(add_help=False)
    registry_flag.add_argument(
        "--registry", help="sources/registry.yaml; defaults to the sibling of topics_root"
    )
    run_flag = argparse.ArgumentParser(add_help=False)
    run_flag.add_argument("--run-id", dest="run_id", help="defaults to the active corpus run")

    p = sub.add_parser("build", parents=[registry_flag], help="staged YAML -> store + corpus run")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("--staging", help="defaults to topics/<id>/corpus/staging")
    p.add_argument("--threshold", type=float, default=None,
                   help="overrides topic_manifest.cluster_threshold for this run")
    p.add_argument("--backfill-debt", action="append", default=[], metavar="SOURCE:CELL:REASON",
                   help="a search-matrix cell this run did not cover, repeatable; recorded "
                        "on the run so an unsearched cell is a known limit, never silence. "
                        "Unclosed debts from the previous run roll forward on their own")
    p.add_argument("--close-debt", action="append", default=[], metavar="SOURCE:CELL",
                   help="an inherited debt whose cells this round actually searched; "
                        "the query lines are the evidence")
    p.add_argument("--retry-debt", action="append", default=[], metavar="SOURCE:CELL",
                   help="an inherited debt this round retried (targeted, search-strategy "
                        "§1b routing) and still failed: retries +1")
    p.add_argument("--futile-debt", action="append", default=[], metavar="SOURCE:CELL",
                   help="a debt no retry can change (subscription wall with fetch_failure "
                        "logged); counts as budget spent immediately")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("withdraw", help="exclude one article from future runs, with a reason")
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("article_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_withdraw)

    p = sub.add_parser(
        "stats", parents=[registry_flag, run_flag], help="dual-unit statistics for a stored run"
    )
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser(
        "similar", parents=[run_flag], help="most similar article pairs, for threshold tuning"
    )
    p.add_argument("topics_root")
    p.add_argument("topic_id")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_similar)

    build_registry_parser(sub)

    build_fetch_parser(sub)

    p = sub.add_parser("segment", help="split a text file into sentences")
    p.add_argument("path", nargs="?")
    p.add_argument(
        "--lang",
        required=True,
        help=f"tuned rules exist for {', '.join(SUPPORTED_LANGS)}; anything else falls back",
    )
    p.set_defaults(func=cmd_segment)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
