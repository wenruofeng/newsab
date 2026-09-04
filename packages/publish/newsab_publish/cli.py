"""Command line entry point for deterministic stage-8 publication."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from newsab_schema.common import LangText, normalize_lang
from newsab_schema.ids import validate_run_id
from newsab_schema.io import ArtifactError
from newsab_schema.models.publication import HumanApproval, PublicationReview
from newsab_schema.paths import SitePaths

from .backfill import backfill_locales
from .cost import (
    DEFAULT_MIN_PATH_MENTIONS,
    DEFAULT_MIN_RUN_IDS,
    Coverage,
    build_report,
    claude_code_projects_dir,
    codex_sessions_dir,
    discover_claude_code_sessions,
    discover_codex_sessions,
    load_rates,
    read_usage_jsonl,
    portable,
    rebuild_index,
    topic_active_run_ids,
    topic_manifest_entries,
    topic_run_ids,
    write_report,
)
from .builder import (
    bundle_files,
    load_submission_provenance,
    paths_fingerprint,
    submission_topics_root,
    activate_publication,
    lifecycle_event,
    prepare_publication,
    rebuild_production,
    render_candidate_bundle,
    render_locales,
    resolve_inputs,
    verify_candidate,
    verify_site,
    write_chrome_assets,
)
from .dev_shell import (
    DEFAULT_DASHBOARD_PORT,
    consumed_intent,
    promote_intent,
    run_dev_shell,
    write_review_manifest,
)
from .metadata import default_metadata_path, load_site_metadata
from .taxonomy import adopt_taxonomy
from .themes import load_theme_registry, render_theme_panel, resolve_theme
from .web_gate import run_web_gate


def _record(path: str | Path, model):
    try:
        return model.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArtifactError(f"{path}: invalid {model.__name__} — {exc}") from exc


def _production(args) -> Path:
    return Path(args.production) if args.production else Path(args.site_root) / "public"


def _metadata(args):
    path = Path(args.site_metadata)
    return load_site_metadata(path), path


def _build_date(raw: Optional[str], fallback) -> date:
    return date.fromisoformat(raw) if raw else fallback


def _locales(args) -> tuple[str, ...]:
    """The explicit ``--locales`` override, or empty when the site set should be used."""
    return tuple(item.strip() for item in args.locales.split(",") if item.strip())


def _hash_only_overlay(path: Optional[str]) -> Optional[dict[str, str]]:
    """Read a submission envelope's ``hash_only`` members as a topic-relative overlay.

    The envelope is untrusted data that G0-G2 already accepted; nothing here executes or
    imports it.  Member paths are archive-relative (``topic/...``); the resolver keys on
    the topic root, so the prefix is stripped and anything outside it is refused rather
    than silently ignored.
    """
    if not path:
        return None
    envelope = json.loads(Path(path).read_text(encoding="utf-8"))
    members = envelope.get("members")
    if not isinstance(members, list):
        raise ArtifactError(f"{path}: envelope has no member table")
    overlay: dict[str, str] = {}
    for member in members:
        if not isinstance(member, dict) or member.get("kind") != "hash_only":
            continue
        key, digest = member.get("path"), member.get("sha256")
        if not isinstance(key, str) or not isinstance(digest, str):
            raise ArtifactError(f"{path}: hash-only member has no path/sha256")
        parts = key.split("/")
        if parts[0] != "topic" or len(parts) < 2 or ".." in parts or key.startswith("/"):
            raise ArtifactError(f"{path}: hash-only member is outside the topic: {key!r}")
        overlay["/".join(parts[1:])] = digest
    return overlay or None


def _expected_candidate(path: Optional[str], locales: tuple[str, ...]) -> Optional[str]:
    """The G2 candidate fingerprint a submission preview must reproduce, or ``None``.

    The submission verifier renders the archived closure twice with the trusted renderer
    and records the fingerprint of what it got (``gates.g2.candidate_fingerprint``).
    ``review-preview`` then renders a *third* time, out of the imported namespace, and
    those are the bytes a human actually approves — so without this comparison a renderer
    that read the imported tree differently from the archived one would silently put
    un-recomputed bytes in front of the reviewer.  That is not hypothetical: it is exactly
    how a whole concept cloud once went missing, caught by eye.

    The comparison is only meaningful when both renders name the same locale set (a page
    states which languages it exists in, so its bytes move with the set), so a disagreeing
    set is refused here rather than reported later as a fingerprint mismatch nobody can
    read.
    """
    if not path:
        return None
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArtifactError(f"{path}: unreadable submission verification report — {exc}") from exc
    gate = ((report or {}).get("gates") or {}).get("g2") or {}
    fingerprint = gate.get("candidate_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ArtifactError(
            f"{path}: no gates.g2.candidate_fingerprint to compare against. A withdraw "
            "archive has no G2 render and no page to review; a create archive that "
            "reached import has one."
        )
    recomputed = tuple(normalize_lang(str(value)) for value in gate.get("render_locales") or ())
    if recomputed != tuple(normalize_lang(locale) for locale in locales):
        raise ArtifactError(
            "the preview's locale set differs from the one the submission verifier "
            f"rendered, so their bytes are not comparable: {list(locales)} != "
            f"{list(recomputed)}. Render the archive's requested locales "
            "(--locales " + ",".join(recomputed) + ")."
        )
    return fingerprint


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="newsab_publish", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("review-preview", help="render exact production pages for human review")
    preview.add_argument("topics_root")
    preview.add_argument("topic_id")
    preview.add_argument("--page-run", required=True)
    preview.add_argument(
        "--locales",
        default="",
        help="override the site's localization set (default: every locale in site metadata)",
    )
    preview.add_argument("-o", "--out", required=True)
    preview.add_argument(
        "--hash-only",
        help=(
            "a submission envelope.json whose hash_only members name run files that are "
            "legitimately absent here; their recorded hashes complete the pin"
        ),
    )
    preview.add_argument(
        "--expect-candidate",
        help=(
            "a submission verification.json; the pages rendered here for the human must "
            "reproduce its G2 candidate fingerprint byte for byte (required whenever "
            "--hash-only says these are submitted pages)"
        ),
    )
    preview.add_argument("--theme-token")
    preview.add_argument("--theme-registry")
    preview.add_argument(
        "--merge",
        action="store_true",
        help="add this topic to an existing review root (one sitting, several topics)",
    )
    preview.add_argument(
        "--categories",
        default="",
        help=(
            "comma-separated site categories proposed for this topic; shown on the review "
            "card so touchpoint two settles them with the page instead of asking after"
        ),
    )

    prepare = sub.add_parser("prepare", help="write an immutable reviewed release candidate")
    prepare.add_argument("topics_root")
    prepare.add_argument("site_root")
    prepare.add_argument("topic_id")
    prepare.add_argument("--page-run", required=True)
    prepare.add_argument("--review", required=True)
    prepare.add_argument("--site-metadata", required=True)
    prepare.add_argument(
        "--submission",
        help=(
            "the SUB-… this topic was imported from: the record then names the archive, "
            "the clean G3 audit and the contributor's sponsor choice, and every later "
            "rebuild finds the topic tree from the record instead of a flag"
        ),
    )
    prepare.add_argument(
        "--locales",
        default="",
        help=(
            "override the site's localization set (default: every locale in site "
            "metadata); never below the English pivot plus the reviewer's own language"
        ),
    )
    prepare.add_argument(
        "--reviewed-locales",
        default="",
        help=(
            "the locale set the reviewed bytes were rendered under, for review records "
            "written before PublicationReview.reviewed_locales existed; read it off the "
            "publication that review was bound into, never from memory"
        ),
    )
    prepare.add_argument(
        "--default-locale",
        default=None,
        help="the locale whose page a reader asking for a language this publication "
             "does not ship is shown (default: en)",
    )
    prepare.add_argument("--theme-token")
    prepare.add_argument("--theme-registry")

    backfill = sub.add_parser(
        "backfill-locales",
        help=(
            "after the site's locale set changes, or a topic's editorial run gets a "
            "content-only rerun on its non-reviewed languages: re-prepare + supersede "
            "every live publication that drifted, reusing each content approval (no "
            "human reviewer on this path — the localization gate is the AI check in "
            "render-localize)"
        ),
    )
    backfill.add_argument("topics_root")
    backfill.add_argument("site_root")
    backfill.add_argument("--site-metadata", required=True)
    backfill.add_argument("--production")
    backfill.add_argument("--base-url", required=True)
    backfill.add_argument(
        "--reason",
        required=True,
        help="why the locale set changed; goes into every supersede event",
    )
    backfill.add_argument("--reason-lang", default="en")
    backfill.add_argument("--reviewer", default="founder")
    backfill.add_argument("--build-date")
    backfill.add_argument(
        "--topic",
        action="append",
        default=[],
        help="limit to these topic ids (repeatable); default: every live publication",
    )
    backfill.add_argument(
        "--page-run",
        action="append",
        default=[],
        metavar="TOPIC=RUN",
        help=(
            "editorial run override per topic (repeatable); default: the topic's "
            "active editorial run"
        ),
    )

    adopt = sub.add_parser(
        "adopt-taxonomy",
        help="fold one founder-approved topic-categories decision into site metadata",
    )
    adopt.add_argument("site_root")
    adopt.add_argument("topic_id")
    adopt.add_argument(
        "--approval",
        help=(
            "the topic-categories-<topic>-<hash8>.json to adopt (default: the sole "
            "matching file under site/private/approvals/; multiple matches require "
            "this to be explicit)"
        ),
    )
    adopt.add_argument(
        "--site-metadata",
        help="metadata revision to update in place (default: the checked-in site_metadata.v1.json)",
    )

    theme_panel = sub.add_parser("theme-panel", help="render the controlled visual theme chooser")
    theme_panel.add_argument("-o", "--out", required=True)
    theme_panel.add_argument("--theme-registry")

    web_gate = sub.add_parser("web-gate", help="run browser-level mobile/keyboard/touch gates")
    web_gate.add_argument("public_root")
    web_gate.add_argument("--screenshots")
    web_gate.add_argument(
        "--full",
        action="store_true",
        help=(
            "open a browser for every page instead of skipping bytes already proved and "
            "sampling the ones only a chrome change invalidated; the release setting"
        ),
    )
    web_gate.add_argument(
        "--workers", type=int, help="browser shards to run in parallel (default: half the cores, max 8)"
    )
    web_gate.add_argument(
        "--no-cache",
        action="store_true",
        help="ignore and do not write .newsab/web_gate_verified.json",
    )
    web_gate.add_argument(
        "--sample",
        type=int,
        default=1,
        help="pages per (page shape x typography stratum) when only the chrome moved",
    )

    verify = sub.add_parser("verify-candidate")
    verify.add_argument("topics_root")
    verify.add_argument("site_root")
    verify.add_argument("publication_id")

    activate = sub.add_parser("activate")
    activate.add_argument("topics_root")
    activate.add_argument("site_root")
    activate.add_argument("publication_id")
    activate.add_argument("--approval", required=True)
    activate.add_argument("--site-metadata", required=True)
    activate.add_argument("--production")
    activate.add_argument("--base-url", required=True)
    activate.add_argument("--build-date")
    activate.add_argument("--reason")
    activate.add_argument("--reason-lang", default="en")

    lifecycle = sub.add_parser("lifecycle")
    lifecycle.add_argument("topics_root")
    lifecycle.add_argument("site_root")
    lifecycle.add_argument("publication_id")
    lifecycle.add_argument("--operation", choices=("withdraw", "restore", "audit_delete"), required=True)
    lifecycle.add_argument("--approval", required=True)
    lifecycle.add_argument("--reason", required=True)
    lifecycle.add_argument("--reason-lang", default="en")
    lifecycle.add_argument("--site-metadata", required=True)
    lifecycle.add_argument("--production")
    lifecycle.add_argument("--base-url", required=True)
    lifecycle.add_argument("--build-date")

    rebuild = sub.add_parser("rebuild", help="rebuild derived catalogs/home for an explicit day")
    rebuild.add_argument("topics_root")
    rebuild.add_argument("site_root")
    rebuild.add_argument("--site-metadata", required=True)
    rebuild.add_argument("--production")
    rebuild.add_argument("--base-url", required=True)
    rebuild.add_argument("--build-date", required=True)

    site = sub.add_parser("verify-site")
    site.add_argument("topics_root")
    site.add_argument("site_root")
    site.add_argument("--site-metadata", required=True)
    site.add_argument("--production")

    cost = sub.add_parser(
        "cost-report",
        help="write this publication's agent wall clock and token spend to site/audit/cost/",
    )
    cost.add_argument("site_root")
    cost.add_argument(
        "publication_id",
        nargs="?",
        help=(
            "a live publication id, read for its topic_id/submission_id (mutually "
            "exclusive with --topic-id, which works before any publication exists)"
        ),
    )
    cost.add_argument(
        "--topic-id",
        help=(
            "report on a topic directly, without a publication — costs to date, before "
            "touchpoint two ever runs. Defaults to the topic's currently active run per "
            "stage (manifest/active.json); pass --run-id to scope it explicitly instead"
        ),
    )
    cost.add_argument(
        "--run-id",
        action="append",
        default=[],
        metavar="RUN_ID",
        help=(
            "scope the report to exactly these run ids (repeatable), instead of every run "
            "id the topic's artifacts mention (with PUBLICATION_ID) or its active pointers "
            "(with --topic-id). Also the only way to see one specific run in isolation."
        ),
    )
    cost.add_argument(
        "--projects-dir",
        help="Claude Code transcript directory (default: discovered from --repo-root)",
    )
    cost.add_argument(
        "--codex-sessions-dir",
        help="Codex rollout root (default: ~/.codex/sessions)",
    )
    cost.add_argument("--repo-root", default=".")
    cost.add_argument(
        "--usage-jsonl",
        action="append",
        default=[],
        help="explicit topic-bound neutral usage records (repeatable; combined with discovery)",
    )
    cost.add_argument(
        "--no-auto-discovery",
        action="store_true",
        help="read only explicit --usage-jsonl sources",
    )
    cost.add_argument(
        "--dry-run",
        action="store_true",
        help="compute and print coverage without writing site/audit/cost",
    )
    cost.add_argument("--topics-root", default="topics")
    cost.add_argument("--rates", help="rate table (default: the checked-in one)")
    cost.add_argument(
        "--min-path-mentions",
        type=int,
        default=DEFAULT_MIN_PATH_MENTIONS,
        help="times a session must open topics/<topic_id> to count as having worked on it",
    )
    cost.add_argument(
        "--min-run-ids",
        type=int,
        default=DEFAULT_MIN_RUN_IDS,
        help="how many of the topic's run ids a session must name, as the other way in",
    )
    cost.add_argument("--include-session", action="append", default=[], metavar="ID")
    cost.add_argument("--exclude-session", action="append", default=[], metavar="ID")

    dev = sub.add_parser(
        "dev-serve",
        help="loopback review dashboard: production, candidates, previews and both touchpoints",
    )
    dev.add_argument("--topics-root", default="topics")
    dev.add_argument("--site-root", default="site")
    dev.add_argument("--production")
    dev.add_argument(
        "--preview",
        action="append",
        default=[],
        metavar="DIR",
        help="a review-preview output directory to index (repeatable)",
    )
    dev.add_argument("--reviewer", default="founder")
    dev.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            f"dashboard port; roots take the next ones. Default {DEFAULT_DASHBOARD_PORT}, "
            "auto-probed upward if busy (e.g. a second review session already running). "
            "An explicit --port is never moved: it fails loudly if occupied."
        ),
    )
    dev.add_argument("--repo-root", default=".")
    dev.add_argument("--once", action="store_true", help="bind, print the map and exit (for checks)")

    args = parser.parse_args(argv)
    try:
        if args.command == "review-preview":
            # One file names the languages this site ships; the preview renders the same
            # set the publication will, so the reviewer's approval covers what ships.
            site_metadata = load_site_metadata(default_metadata_path())
            # The category vocabulary is closed: the same metadata file that names the
            # locales names every filter the home page offers.  A proposal outside it
            # would sail through review as a string and then match no filter, so it is
            # refused here, where the proposing agent still holds the context.
            proposed_categories = [
                c.strip() for c in (args.categories or "").split(",") if c.strip()
            ]
            known_categories = {c.category_id for c in site_metadata.categories}
            unknown_categories = [
                c for c in proposed_categories if c not in known_categories
            ]
            if unknown_categories:
                raise ArtifactError(
                    "unknown site categories "
                    + ", ".join(unknown_categories)
                    + "; the closed vocabulary is site_metadata.v1.json -> categories ("
                    + ", ".join(sorted(known_categories))
                    + ") and adding to it is the site operator's decision, not a flag"
                )
            # An imported submission namespace has no rendered previews: the archive
            # records them by hash and never ships the bytes, because this renderer
            # rebuilds every displayable surface itself.  The envelope's hashes complete
            # the page run's declared set so the pin still verifies in full.
            resolved = resolve_inputs(
                args.topics_root,
                args.topic_id,
                args.page_run,
                hash_only=_hash_only_overlay(args.hash_only),
            )
            locales = _locales(args) or tuple(site_metadata.locales)
            # A submitted page is one this repo only reviews, and the reviewer's bytes
            # are the only thing touchpoint two binds — so on that path the comparison
            # against the verifier's own recomputation is not optional.
            if args.hash_only and not args.expect_candidate:
                raise ArtifactError(
                    "--hash-only says these are submitted pages, so --expect-candidate "
                    "<imported>/verification.json is required: the bytes a human "
                    "approves must be the bytes the submission verifier recomputed"
                )
            expected_candidate = _expected_candidate(args.expect_candidate, locales)
            output = Path(args.out)
            # A stale page beside a fresh one is a review hazard, so a non-empty target is
            # refused unless the caller says it is deliberately assembling one review root
            # out of several topics.  Colliding bytes are still refused by the closed-list
            # writer either way.
            if output.exists() and any(output.iterdir()) and not args.merge:
                raise ArtifactError(
                    f"review-preview output must be empty (use --merge to add a topic): {output}"
                )
            output.mkdir(parents=True, exist_ok=True)
            registry = load_theme_registry(args.theme_registry)
            # Fingerprint what *this* render writes, not the directory: a --merge root
            # already holds other topics, and the chrome and review manifest written
            # below are review scaffolding the candidate bundle never contains.
            before = bundle_files(output)
            bundles, data_assets, assets = render_candidate_bundle(
                resolved,
                locales,
                output,
                m2=True,
                theme=resolve_theme(args.theme_token, registry),
            )
            candidate_fingerprint = paths_fingerprint(output, bundle_files(output) - before)
            if expected_candidate is not None and candidate_fingerprint != expected_candidate:
                raise ArtifactError(
                    "the pages rendered for review are not the pages the submission "
                    f"verifier recomputed: {candidate_fingerprint} != "
                    f"{expected_candidate}. Both renders read the same pinned closure, "
                    "so this repo's renderer is reading the imported namespace "
                    "differently from the archived one — fix that before a human reads "
                    "anything; do not approve these bytes."
                )
            # Production pages link the site chrome at a stable root-relative URL, so a
            # preview directory is only reviewable when served as a root with the chrome
            # beside it.  Write it here and say so.
            chrome_assets = write_chrome_assets(output, registry)
            # Record which pinned run each page came from.  Without it a reviewer who
            # approves a page in the browser is told nothing about what to do next, and
            # the review shell would have to guess the `prepare` arguments.
            write_review_manifest(
                output,
                topic_id=args.topic_id,
                page_run_id=args.page_run,
                theme_token=resolve_theme(args.theme_token, registry).token,
                categories=proposed_categories,
                locales=locales,
                bundles=bundles,
                review_locale=resolved.manifest.review_locale or "",
                candidate_fingerprint=candidate_fingerprint,
            )
            print(json.dumps({
                "candidate_fingerprint": candidate_fingerprint,
                "candidate_recomputed": expected_candidate is not None,
                "locales": [bundle.model_dump(mode="json") for bundle in bundles],
                "data_assets": [asset.model_dump(mode="json") for asset in data_assets],
                "share_assets": [asset.model_dump(mode="json") for asset in assets],
                "chrome_assets": chrome_assets,
                "serve": f"python -m newsab_publish dev-serve --preview {output}",
            }, ensure_ascii=False, indent=2))
            return 0
        if args.command == "prepare":
            metadata, metadata_path = _metadata(args)
            review = _record(args.review, PublicationReview)
            stated = tuple(
                item.strip() for item in args.reviewed_locales.split(",") if item.strip()
            )
            if stated:
                if review.reviewed_locales and list(stated) != review.reviewed_locales:
                    raise ArtifactError(
                        "--reviewed-locales contradicts the review record: "
                        f"{list(stated)} != {review.reviewed_locales}"
                    )
                # Revalidate rather than model_copy: the stated set still has to contain
                # the locale the user signed.
                review = PublicationReview.model_validate(
                    review.model_dump(mode="json") | {"reviewed_locales": list(stated)}
                )
            submission = (
                load_submission_provenance(
                    SitePaths.at(args.site_root), args.submission, args.topic_id
                )
                if args.submission
                else None
            )
            record = prepare_publication(
                args.topics_root,
                args.site_root,
                args.topic_id,
                page_run_id=args.page_run,
                review=review,
                metadata=metadata,
                metadata_path=metadata_path,
                locales=_locales(args) or None,
                default_locale=args.default_locale,
                theme_token=args.theme_token,
                theme_registry_path=args.theme_registry,
                submission=submission,
            )
            # If the reviewer took touchpoint two in the review shell, they authorized the
            # lifecycle move in the same click — before this id existed.  Promote that
            # intent now that the bytes they signed have one.
            promoted = promote_intent(
                SitePaths.at(args.site_root).ensure(),
                topic_id=record.topic_id,
                publication_id=record.publication_id,
                page_hash=record.review.page_hash,
            )
            print(record.publication_id)
            print(record.public_bundle_fingerprint)
            if promoted is not None:
                print(f"authorization {promoted}")
            else:
                spent = consumed_intent(
                    SitePaths.at(args.site_root).ensure(),
                    topic_id=record.topic_id,
                    page_hash=record.review.page_hash,
                )
                if spent is not None:
                    # The signature on these bytes was spent on an earlier operation;
                    # say so instead of leaving the operator to notice the missing
                    # authorization at activate time.
                    print(
                        "authorization none: the intent for these bytes was consumed by "
                        f"{spent.get('publication_id', '?')}; this candidate needs its "
                        "own approval"
                    )
            return 0
        if args.command == "backfill-locales":
            metadata, metadata_path = _metadata(args)
            page_runs = {}
            for item in args.page_run:
                topic, sep, run = item.partition("=")
                if not sep or not topic or not run:
                    raise ArtifactError(f"--page-run wants TOPIC=RUN, got {item!r}")
                page_runs[topic] = run
            outcomes = backfill_locales(
                args.topics_root,
                args.site_root,
                metadata=metadata,
                metadata_path=metadata_path,
                production_dir=_production(args),
                base_url=args.base_url,
                reason=args.reason,
                reason_lang=args.reason_lang,
                reviewer_id=args.reviewer,
                build_date=date.fromisoformat(args.build_date) if args.build_date else None,
                only_topics=args.topic or None,
                page_runs=page_runs or None,
            )
            for outcome in outcomes:
                print(outcome.render())
            failed = [o for o in outcomes if o.status == "failed"]
            print(
                f"backfill: {sum(o.status == 'superseded' for o in outcomes)} superseded, "
                f"{sum(o.status == 'skipped' for o in outcomes)} skipped, "
                f"{len(failed)} failed"
            )
            return 1 if failed else 0
        if args.command == "adopt-taxonomy":
            result = adopt_taxonomy(
                args.site_root,
                args.topic_id,
                approval_path=args.approval,
                metadata_path=args.site_metadata,
            )
            print(json.dumps({
                "status": result.status,
                "metadata_path": str(result.metadata_path),
                "topic_id": result.topic_id,
                "category_ids": list(result.category_ids),
                "approval": str(result.approval_path),
            }, ensure_ascii=False, indent=2))
            return 0
        if args.command == "theme-panel":
            target = Path(args.out)
            if target.exists():
                raise ArtifactError(f"theme panel output already exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                render_theme_panel(load_theme_registry(args.theme_registry)), encoding="utf-8"
            )
            print(target)
            return 0
        if args.command == "web-gate":
            print(
                json.dumps(
                    run_web_gate(
                        args.public_root,
                        screenshots=args.screenshots,
                        full=args.full,
                        workers=args.workers,
                        use_cache=not args.no_cache,
                        per_stratum=args.sample,
                    ),
                    indent=2,
                )
            )
            return 0
        if args.command == "verify-candidate":
            record = verify_candidate(args.topics_root, args.site_root, args.publication_id)
            print(record.publication_id)
            print(record.public_bundle_fingerprint)
            return 0
        if args.command == "activate":
            metadata, _ = _metadata(args)
            approval = _record(args.approval, HumanApproval)
            reason = LangText(text=args.reason, lang=args.reason_lang) if args.reason else None
            event = activate_publication(
                args.topics_root,
                args.site_root,
                args.publication_id,
                approval=approval,
                metadata=metadata,
                production_dir=_production(args),
                base_url=args.base_url,
                build_date=_build_date(args.build_date, approval.decided_at.date()),
                reason=reason,
            )
            print(event.event_id)
            return 0
        if args.command == "lifecycle":
            metadata, _ = _metadata(args)
            approval = _record(args.approval, HumanApproval)
            event = lifecycle_event(
                args.topics_root,
                args.site_root,
                args.publication_id,
                operation=args.operation,
                approval=approval,
                reason=LangText(text=args.reason, lang=args.reason_lang),
                metadata=metadata,
                production_dir=_production(args),
                base_url=args.base_url,
                build_date=_build_date(args.build_date, approval.decided_at.date()),
            )
            print(event.event_id)
            return 0
        if args.command == "rebuild":
            metadata, _ = _metadata(args)
            fingerprint = rebuild_production(
                args.topics_root,
                args.site_root,
                metadata=metadata,
                production_dir=_production(args),
                base_url=args.base_url,
                build_date=date.fromisoformat(args.build_date),
            )
            print(fingerprint)
            return 0
        if args.command == "dev-serve":
            run_dev_shell(
                repo_root=Path(args.repo_root),
                topics_root=Path(args.topics_root),
                site_root=Path(args.site_root),
                production_dir=Path(args.production)
                if args.production
                else Path(args.site_root) / "public",
                preview_dirs=[Path(item) for item in args.preview],
                reviewer_id=args.reviewer,
                base_port=args.port if args.port is not None else DEFAULT_DASHBOARD_PORT,
                port_explicit=args.port is not None,
                once=args.once,
            )
            return 0
        if args.command == "cost-report":
            if bool(args.publication_id) == bool(args.topic_id):
                raise ArtifactError(
                    "cost-report needs exactly one of PUBLICATION_ID (a live publication) "
                    "or --topic-id (works before activation, before touchpoint two ever "
                    "runs) — pass one, not both, not neither"
                )
            site_paths = SitePaths.at(args.site_root)
            rates = load_rates(args.rates)
            explicit_run_ids = {validate_run_id(rid) for rid in args.run_id}
            if args.publication_id:
                record = json.loads(
                    (
                        site_paths.publications_dir / args.publication_id / "publication.json"
                    ).read_text(encoding="utf-8")
                )
                topic_id = record["topic_id"]
                # A publication that came from a submission keeps its topic tree in the
                # import namespace, and says so in its own record.
                report_topics_root = (
                    submission_topics_root(site_paths, record["submission_id"])
                    if record.get("submission_id")
                    else args.topics_root
                )
                # Every run id the topic's artifacts mention, unchanged from before
                # --run-id existed — a live publication has a settled history to sum.
                run_ids = explicit_run_ids or topic_run_ids(report_topics_root, topic_id)
            else:
                topic_id = args.topic_id
                report_topics_root = args.topics_root
                if explicit_run_ids:
                    run_ids = explicit_run_ids
                else:
                    active = topic_active_run_ids(report_topics_root, topic_id)
                    run_ids = set(active.values())
                    if not run_ids:
                        raise ArtifactError(
                            f"{topic_id}: manifest/active.json has no active run for any "
                            "stage yet — pass --run-id explicitly, or run a stage first"
                        )
            manifest_entries = topic_manifest_entries(report_topics_root, topic_id)
            sessions = []
            configured: set[str] = set()
            observed: set[str] = set()
            missing: set[str] = set()
            source_notes: list[str] = []
            if not args.no_auto_discovery:
                projects = (
                    Path(args.projects_dir)
                    if args.projects_dir
                    else claude_code_projects_dir(args.repo_root)
                )
                configured.add("claude-code")
                if projects.is_dir():
                    sessions.extend(
                        discover_claude_code_sessions(
                            projects,
                            topic_id,
                            run_ids=run_ids,
                            min_path_mentions=args.min_path_mentions,
                            min_run_ids=args.min_run_ids,
                            include=args.include_session,
                            exclude=args.exclude_session,
                        )
                    )
                    source_notes.append(f"claude-code:{portable(projects)}")
                else:
                    missing.add("claude-code")

                codex_root = (
                    Path(args.codex_sessions_dir)
                    if args.codex_sessions_dir
                    else codex_sessions_dir()
                )
                configured.add("codex")
                if codex_root.is_dir():
                    sessions.extend(
                        discover_codex_sessions(
                            codex_root,
                            args.repo_root,
                            topic_id,
                            run_ids=run_ids,
                            min_path_mentions=args.min_path_mentions,
                            min_run_ids=args.min_run_ids,
                            include=args.include_session,
                            exclude=args.exclude_session,
                        )
                    )
                    source_notes.append(f"codex:{portable(codex_root)}")
                else:
                    missing.add("codex")

            for usage_path in args.usage_jsonl:
                explicit = read_usage_jsonl(Path(usage_path), topic_id)
                sessions.extend(explicit)
                harnesses = {session.harness for session in explicit} or {"generic"}
                configured.update(harnesses)
                source_notes.append(f"usage-jsonl:{portable(usage_path)}")
            if not sessions:
                raise ArtifactError(
                    f"no configured source yielded a session candidate for {topic_id}"
                )
            observed = {
                session.harness
                for session in sessions
                if session.included and bool(session.rows)
            }
            coverage = Coverage(
                configured_harnesses=tuple(sorted(configured)),
                observed_harnesses=tuple(sorted(observed)),
                missing_harnesses=tuple(sorted(missing)),
                notes=tuple(source_notes),
            )
            report = build_report(
                args.publication_id,
                topic_id,
                sessions,
                rates,
                reader="combined",
                coverage=coverage,
                target_run_ids=run_ids,
                manifest_entries=manifest_entries,
            )
            if args.dry_run:
                included = sum(candidate["included"] for candidate in report.candidates)
                serial_harness = report.to_json()["by_harness"]
                partial_sessions = [
                    {
                        "session": candidate["session"],
                        "note": candidate["usage_note"],
                    }
                    for candidate in report.candidates
                    if candidate["included"] and not candidate["usage_complete"]
                ]
                print(
                    json.dumps(
                        {
                            "topic_id": topic_id,
                            "coverage": report.to_json()["coverage"],
                            "candidate_sessions": len(report.candidates),
                            "included_sessions": included,
                            "wall_clock_minutes": report.wall_clock_minutes,
                            "total_tokens": sum(
                                usage.total_tokens for usage in report.totals_by_model.values()
                            ),
                            "priced_usd": round(report.priced_usd, 4),
                            "total_usd": report.total_usd,
                            "models": sorted(report.totals_by_model),
                            "by_harness": serial_harness,
                            "partial_sessions": partial_sessions,
                            "by_run": report.by_run,
                            "by_skill": report.by_skill,
                            "cross_stage": report.cross_stage,
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            csv_path, _ = write_report(args.site_root, report)
            index = rebuild_index(args.site_root)
            print(csv_path)
            print(index)
            price = (
                f"${report.total_usd:,.2f}"
                if report.total_usd is not None
                else f"${report.priced_usd:,.2f} priced + unpriced usage"
            )
            print(f"{report.wall_clock_minutes:.0f} min  {price}  ({report.pricing_status})")
            for skill in report.by_skill:
                skill_tokens = skill["total_tokens"]
                skill_wall = (
                    f"{skill['wall_clock_minutes']:.0f} min"
                    if skill["wall_clock_minutes"] is not None
                    else "n/a"
                )
                skill_usd = f"${skill['usd']:,.2f}" if skill["usd"] is not None else "n/a"
                print(
                    f"  {skill['skill_id']}: {skill_tokens} tok  {skill_wall}  {skill_usd}  "
                    f"({skill['pricing_status']}, {skill['runs_with_data']}/{skill['runs']} "
                    "runs with an exclusive session)"
                )
            if report.cross_stage["sessions"]:
                print(
                    f"  cross-stage (unsplit): {report.cross_stage['total_tokens']} tok across "
                    f"{len(report.cross_stage['sessions'])} session(s) touching more than one "
                    "queried run — see cross_stage.note in the JSON report"
                )
            return 0
        if args.command == "verify-site":
            metadata, _ = _metadata(args)
            print(
                verify_site(
                    args.topics_root,
                    args.site_root,
                    _production(args),
                    metadata=metadata,
                )
            )
            return 0
    except (ArtifactError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
