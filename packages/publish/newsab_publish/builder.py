"""Deterministic stage-8 publication and production-bundle builder.

The builder never follows a topic active pointer.  Every content input comes from the
explicit page run and the run ids pinned inside that page; lifecycle authority comes from
the site event stream.  Public output is assembled from a closed list in a fresh root.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Optional

from newsab_editorial.evidence import AnswerIndex
from newsab_editorial.page_checks import (
    check_page,
    check_rendered_concept_cloud,
    load_analysis_run,
    load_analysis_thresholds,
    load_excluded_clusters,
    load_pinned_corpus_run,
)
from newsab_editorial.page_render import render_page, sentence_load
from newsab_editorial.provenance import build_page_components
from newsab_editorial.render.common import group_text
from newsab_editorial.render.m2 import PageSiteContext
from newsab_schema.artifacts import (
    load_hash_only,
    load_manifest,
    manifest_entry_fingerprint,
)
from newsab_schema.common import LangText, Provenance, normalize_lang
from newsab_schema.io import ArtifactError, dump_record, read_jsonl, read_yaml
from newsab_schema.models.corpus import TopicManifest
from newsab_schema.models.manifest import content_digest, file_digest
from newsab_schema.models.page import ReaderPage
from newsab_schema.models.publication import (
    CatalogAngle,
    CatalogRecord,
    CatalogSide,
    DataAsset,
    HumanApproval,
    LocaleBundle,
    PublicationEvent,
    PublicationRecord,
    PublicationReview,
    ReviewedEquivalence,
    ShareAsset,
    SponsorAttribution,
    TopicRunPin,
    WorkerAttribution,
)
from newsab_schema.models.qa import ClusterAnswer, QuestionSet
from newsab_schema.paths import SitePaths, TopicPaths, source_registry_path
from newsab_schema.readability import readable_clusters_of_articles
from newsab_schema.store import (
    append_publication_event,
    derive_publish_selector,
    load_publication,
    load_publication_events,
    load_publications,
    load_run_articles,
    write_publication,
)

from . import chrome, crawler_meta
from .metadata import PIVOT_LOCALE, SiteMetadata
from .reviewed_equivalence import (
    WHITELIST_VERSION,
    ContentBaseline,
    project_page,
    prove_byte_equivalence,
    prove_content_equivalence,
    redacted_digest,
)
from .share_cards import render_share_assets
from .social_card import ASSET_URL as SHARE_CARD_URL
from .site_strings import SITE_LOCALES, site_strings
from .themes import (
    ThemeDefinition,
    ThemeRegistry,
    check_theme_labels,
    default_theme_registry_path,
    load_theme_registry,
    resolve_theme,
)


#: 0.3.0 was the content/chrome split.  0.4.0 externalizes the language-neutral data
#: islands: a production page carries ``data-src`` references to content-addressed
#: JSON assets shared by every locale, plus a small per-language overlay island; the
#: assets are content, pinned in ``PublicationRecord.data_assets`` and covered by the
#: bundle fingerprint.  Pages minted by an earlier producer keep verifying against their
#: stored bundles, which is exactly why that tier exists.
#: What this string is: **the publish package's own version**, and nothing else.  It
#: moves whenever the bytes this package produces move — including when
#: the move comes from a dependency rather than from code in this package, because a
#: package whose output changed is a new version of that package either way.  An earlier
#: comment here read the field as a "renderer generation"; that second meaning is retired,
#: because it makes the same renderer answer to two names depending on when a record
#: happened to be stamped.
#: 0.5.0: qa-0.5.0 counts only readable clusters and the editorial layer draws a badge's
#: evidence list from that same universe, so a page pinned to a pre-0.5.0 analysis run
#: no longer re-renders to its approved bytes.
#: 0.6.0: the reader-facing copy in ``newsab_editorial.render.strings`` moved (commit
#: 68615dd) — strength/tier/kind chips lost their trailing nouns, the answered-rate
#: label was reworded, the copyright half of the article note was dropped, and
#: ``LANG_LABEL`` gained five languages so an outlet island states a language name instead
#: of its code.  Every page pinned before that re-renders to different bytes than the ones
#: approved.
#: 0.7.0: the badge/answered-rate denominator wording moved again (commit be650df: "the
#: N independent reports we collected" → "the N readable independent reports counted in
#: this analysis"), and page-check began requiring reader wording for
#: every displayed topics_raised pivot.  Live 0.6.0 records keep their approved bytes'
#: authority via the stored bundle and hash chain until each is next superseded; the
#: wording reaches a page at its next review, never by silent re-render.
#: 0.8.0: a candidate no longer draws per-angle SVG share cards.  Its pages and share
#: landings name the site's PNG card as ``og:image`` outright, and its
#: ``share_assets`` pin the landings alone.  Live 0.7.0 records keep their approved bytes
#: (SVGs included) via the stored bundle and hash chain; today's renderer is never asked
#: to reproduce them.
PACKAGE_VERSION = "publish-0.8.0"
#: 0.4.0: ``report_count`` counts readable independent reports rather than raw articles.
#: The home card's number and the topic page's own timeline and badges are now the same
#: count; a record written by an earlier producer carries the old
#: unit until its publication is next prepared.
CATALOG_VERSION = "catalog-0.4.0"
#: Producers whose immutable records remain verifiable.  A historical publication is
#: verified against its stored bundle bytes and pinned archives, never by re-rendering
#: with today's renderer: renderer evolution must not brick the verification of bytes a
#: human already approved.  The re-render check is asked only of a record that is in the
#: live tier — live for its topic, or a reviewed candidate the event stream has never
#: touched — *and* stamped by the current producer.  A superseded or withdrawn record's
#: authority is its archived bundle plus the hash chain whatever version stamped it.
#: Under the old proxy (`producer == PACKAGE_VERSION` alone) a superseded record sharing
#: the current version was asked to re-render against a renderer that had moved under it,
#: and necessarily failed.  Liveness landing also means a producer bump is never needed
#: just to keep retired records out of the re-render tier.
SUPPORTED_PACKAGE_VERSIONS = frozenset(
    {
        "publish-0.1.0",
        "publish-0.2.0",
        "publish-0.2.1",
        "publish-0.3.0",
        "publish-0.4.0",
        "publish-0.5.0",
        "publish-0.6.0",
        "publish-0.7.0",
        PACKAGE_VERSION,
    }
)
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
# One-time aliases from the scope-signature migration.  Commit 1214264
# verified each legacy fingerprint against the then-current signed manifest before
# removing collection-only ``cluster_threshold`` from TopicManifest.scope_hash().
# Keeping the exact old→new pairs here lets an immutable pre-migration publication
# participate in a later release without treating an arbitrary scope mismatch as valid.
_SCOPE_FINGERPRINT_ALIASES = {
    "sha256:092264c48f30f732c1d61a6fa16861ec78a8e4a626d4a803f8466358d1ba0450": "sha256:497e362a186c45993e805b0ed0449e152e18f37427cbe659f57d69e98fbdc79d",
    "sha256:8f5f1e3a50b0133bd8615977d4feb6ca4b985e8c5f1fb0a38ab53546f91bc05e": "sha256:5b30d761541d49f708ed8dd66bda416e6b826b9b4d05a3e22ef5eb481fe5ab4c",
    "sha256:0c073c4c3a1940e172d3e38ecb5a27e7298d283c23ce34e0f91e641cde3fed35": "sha256:53d16f9e2d5c575794340dfb9969e41dc6e64877a80e03561a5e19b7343c847a",
    "sha256:d13dfa09e3d0918d9c32e459ac4cd0bf2b1b9c2670f4acc8b893e2f5f5aa8663": "sha256:05f557208254f59cb0add28c755708dfe70a90565d5debf684ce92d73b9a35e4",
    "sha256:26f6f84c679779a76f71d3289aa80152680c093f18cc0fda01240ef077a2a713": "sha256:97c032ca359a02cbd94c3a0eec5e67e9036a5b91ea99984971c9b588535e0c52",
    "sha256:b102b18db5f00ad85d87d4dbc663f6ec36893226bde13e17260c2e6619ba55b0": "sha256:bb9c61f8b4501ee24c791dc949e9d52dc3bef5d541083f72c4143e496100c662",
    "sha256:f3e2a0080f242e3715847a4762bd1539e369764919289d8132f5ed90b3e138db": "sha256:1c4e76026bf91aeae29ed3323bdf476ae095732f48160db5ae08c00f789f4155",
    "sha256:55311be9a003e5e96b6387fb565d84dc80eba149a56cde1587fbb1731cbd46e1": "sha256:5e6031dba2ebe8bfbc30c1d4d95d079c093e81040c5e91f289957a1b870dfeea",
    "sha256:b5a54e1cf8e4cf03ce4dc0cb124efe22e01ec74b5bcc8fee9789f1cf23c656d6": "sha256:5d2cca5f21f164596e2f11ff75e5f05caf965d07e6f0867bfadcfd86e6eb1396",
    "sha256:26235850512e5ae9d9b882ce4069902a134585a122108d8b75d3a827a44779ee": "sha256:879852dc136a34b9509ef38b7a47db4736975081e18703792b610671c8c35418",
}
_FORBIDDEN_TEXT = (
    "corpus/articles/",
    "corpus/staging/",
    "submission_control_token",
    "structured_text",
)


def bytes_digest(payload: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def paths_fingerprint(root: Path, relatives: Iterable[str]) -> str:
    """Hash a *named* subset of a directory exactly as :func:`directory_fingerprint` does.

    A caller that knows which files it just wrote can fingerprint those and no others,
    and get a value comparable byte for byte with a whole-directory fingerprint taken
    over the same set somewhere else: the pages a human reviews are compared against the
    submission verifier's own independent recomputation, even though the review root also
    holds site chrome and a review manifest the verifier never wrote.
    """
    rows = []
    for relative in sorted(relatives):
        path = root / relative
        if path.is_symlink():
            raise ArtifactError(f"public bundle contains a symlink: {path}")
        rows.append([relative, file_digest(path)])
    return content_digest(rows)


def bundle_files(root: Path) -> set[str]:
    """Every regular file under ``root``, as root-relative POSIX paths."""
    return {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }


def directory_fingerprint(root: Path) -> str:
    """Hash a directory as ``[[relative path, byte hash], ...]`` in lexical order."""
    return paths_fingerprint(root, bundle_files(root))


def _safe_output_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ArtifactError(f"unsafe public output path: {relative!r}")
    target = root.joinpath(*pure.parts)
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ArtifactError(f"public output escapes build root: {relative!r}") from exc
    return target


def write_closed_file(root: Path, relative: str, payload: bytes) -> Path:
    target = _safe_output_path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ArtifactError(f"closed output list repeats {relative}")
    target.write_bytes(payload)
    return target


def scan_public_bundle(root: Path) -> None:
    """Refuse path/code/private-data shapes in the completed public directory."""
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ArtifactError(f"public bundle contains a symlink: {path}")
        if not path.is_file():
            continue
        mode = path.stat().st_mode
        if mode & 0o111:
            raise ArtifactError(f"public bundle contains an executable file: {path}")
        # Non-UTF-8 content still gets the marker scan on raw bytes; a binary file must
        # not silently exempt itself from the forbidden-shape check.
        payload = path.read_bytes()
        for marker in _FORBIDDEN_TEXT:
            if marker.encode("utf-8") in payload:
                raise ArtifactError(f"public bundle contains forbidden marker {marker!r}: {path}")


@dataclass(frozen=True)
class ResolvedInputs:
    paths: TopicPaths
    manifest: TopicManifest
    page: ReaderPage
    entries: tuple
    entry_by_id: Mapping[str, object]
    pins: tuple[TopicRunPin, ...]
    articles: tuple
    findings: tuple
    question_stats: dict
    answers: AnswerIndex
    question_set: QuestionSet
    topics_by_article: dict
    topics_by_article_bytes: bytes
    source_registry: object
    source_registry_bytes: bytes


def _entry(by_id: Mapping[str, object], run_id: str, label: str):
    found = by_id.get(run_id)
    if found is None:
        raise ArtifactError(f"{label} run is absent from topic manifest: {run_id}")
    return found


def _is_ancestor(entry_by_id: Mapping[str, object], descendant: str, ancestor: str) -> bool:
    pending = [descendant]
    seen = set()
    while pending:
        current = pending.pop()
        if current == ancestor:
            return True
        if current in seen:
            continue
        seen.add(current)
        entry = entry_by_id.get(current)
        if entry is not None:
            pending.extend(entry.inputs)
    return False


def _load_source_registry(topics_root: Path) -> tuple[object, bytes]:
    """Load the cross-topic outlet registry as exact bytes plus its parsed record.

    The registry is the one render input the repo declares mutable (append-only, never a
    gate), so the deterministic page bytes must pin the bytes actually used: a later
    outlet edit must not make an already-reviewed publication unverifiable.
    """
    registry_file = source_registry_path(topics_root)
    if not registry_file.exists():
        from newsab_schema.store import empty_registry

        return empty_registry(), b""
    payload = registry_file.read_bytes()
    return _registry_from_bytes(payload), payload


@lru_cache(maxsize=8)
def _parse_registry(payload: bytes) -> object:
    from newsab_schema.io import load_yaml_text
    from newsab_schema.models.corpus import SourceRegistry
    from newsab_schema.store import empty_registry

    if not payload.strip():
        return empty_registry()
    return SourceRegistry.model_validate(load_yaml_text(payload.decode("utf-8")))


def _registry_from_bytes(payload: bytes) -> object:
    """Parse pinned registry bytes, reusing the parse across publications.

    Every publication archives its own copy of the registry and ``verify-site`` walks all
    of them, so the same three-quarter-megabyte document was parsed once per record — 180
    parses of the same handful of distinct payloads, and the dominant cost of the whole
    command.  Keying the cache on the bytes keeps that exact-bytes pin intact: a
    record pinning different bytes still gets its own parse.  The result is read-only
    everywhere it is consumed (:func:`render_candidate_bundle` only reads outlet rows off
    it), so one shared instance is safe.
    """
    return _parse_registry(payload)


def _load_topics_by_article(paths: TopicPaths) -> tuple[dict, bytes]:
    """Normalize legacy collect notes once, then pin/archive the exact public-safe map.

    The notes are keyed by staging file and only the join through the staging directory
    turns them into article ids, so a topic tree without that private input cannot derive
    the map — it carries the derived map itself instead.  That is exactly the shape of an
    imported submission namespace (the archive ships `corpus/topics_by_article.json` and
    deliberately leaves the staging inputs home), and deriving from an absent staging dir
    there would silently render a page with an empty concept cloud rather than the one the
    gates recomputed.  Shipped map wins where it exists; every ordinary checkout has the
    staging inputs and none of these files, so its behaviour is unchanged.
    """
    from newsab_editorial.topics_raised import load_topics_by_article

    shipped = paths.corpus_dir / "topics_by_article.json"
    if shipped.is_file():
        try:
            mapping = json.loads(shipped.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ArtifactError(
                f"{shipped}: topics_by_article is not valid JSON — {exc}"
            ) from exc
        if not isinstance(mapping, dict):
            raise ArtifactError(f"{shipped}: topics_by_article must be a JSON object")
    else:
        mapping = load_topics_by_article(paths)
    payload = canonical_json_bytes(mapping)
    return mapping, payload


def resolve_inputs(
    topics_root: str | Path,
    topic_id: str,
    page_run_id: str,
    *,
    hash_only: Mapping[str, str] | None = None,
) -> ResolvedInputs:
    """Resolve one page run's pinned closure for publication-grade rendering.

    ``hash_only`` names topic-relative files that are legitimately absent with their
    recorded hashes — the shape an imported submission namespace has, where the page
    run's previews travel as hashes and this renderer rebuilds the reader surface.
    Left unset it is read from the namespace itself, so every command pointed at an
    imported tree resolves it the same way without each one growing a flag; pass ``{}``
    to insist on bytes for the whole set.
    """
    if hash_only is None:
        hash_only = load_hash_only(topics_root, topic_id)
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
        fingerprint = manifest_entry_fingerprint(
            paths, entry_by_id[run_id], hash_only=hash_only
        )
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
    topics_by_article, topics_bytes = _load_topics_by_article(paths)
    source_registry, source_registry_bytes = _load_source_registry(paths.root.parent)

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


def _text(value, locale: str, fallback: str = "en") -> str:
    text = value.get(locale) or value.get(fallback)
    if not text:
        raise ArtifactError(f"reader text is missing locale {locale!r}")
    return text


def render_locales(
    resolved: ResolvedInputs,
    locales: Iterable[str],
    output_root: Path,
    *,
    m2: bool = False,
    theme: Optional[ThemeDefinition] = None,
) -> tuple[list[LocaleBundle], list[DataAsset]]:
    """Re-run every deterministic check and render exact production page bytes.

    An M2 render externalizes the language-neutral data islands: every locale
    must derive byte-identical assets — that identity is asserted, then each unique file
    is written once at the locale-independent ``topics/<topic_id>/data/`` path.
    """
    locales = tuple(normalize_lang(locale) for locale in locales)
    if not locales or len(locales) != len(set(locales)):
        raise ArtifactError("publication locales must be a non-empty unique list")
    registry = resolved.source_registry
    qa_dir = resolved.paths.a1_run_dir(resolved.page.how_we_counted.qa_run_id)
    report = check_page(
        resolved.page,
        resolved.articles,
        list(resolved.findings),
        resolved.question_stats,
        answers=resolved.answers,
        required_langs=locales,
        pinned_corpus_run=resolved.page.how_we_counted.corpus_run_id,
        pinned_qa_run=resolved.page.how_we_counted.qa_run_id,
        manifest=resolved.manifest,
        topics_by_article=resolved.topics_by_article,
    )
    if not report.ok:
        raise ArtifactError(report.render())

    page_components = build_page_components(
        resolved.page, resolved.manifest, resolved.entries
    )
    bundles: list[LocaleBundle] = []
    data_dir = f"topics/{resolved.page.topic_id}/data"
    shared_assets: Optional[dict[str, bytes]] = None
    for locale in locales:
        context = None
        if m2:
            if theme is None:
                raise ArtifactError("M2 production render requires a validated theme")
            ui = dict(site_strings(locale))
            page_url = f"/{locale}/topics/{resolved.page.topic_id}/"
            context = PageSiteContext(
                site_locale=locale,
                content_locale=locale,
                canonical_url=page_url,
                alternate_urls={
                    item: f"/{item}/topics/{resolved.page.topic_id}/" for item in locales
                },
                share_urls={
                    angle.question_id: f"{page_url}#angle-{angle.question_id}"
                    for angle in resolved.page.angles
                },
                share_landing_urls={
                    angle.question_id: f"{page_url}share/angle-{angle.question_id}.html"
                    for angle in resolved.page.angles
                },
                share_image_url=SHARE_CARD_URL,
                language_label=ui["language"],
                share_label=ui["share_angle"],
                share_copied=ui["share_copied"],
                share_failed=ui["share_failed"],
                theme_token=theme.token,
                stylesheet_url=chrome.STYLESHEET_URL,
                script_url=chrome.SCRIPT_URL,
            )
        locale_assets: dict[str, bytes] = {}
        html, shipped, _withheld = render_page(
            resolved.page,
            resolved.articles,
            resolved.manifest,
            resolved.question_stats,
            lang=locale,
            findings=list(resolved.findings),
            answers=resolved.answers,
            question_set=resolved.question_set,
            registry=registry,
            thresholds=load_analysis_thresholds(qa_dir),
            appendix=True,
            return_shipped=True,
            topics_by_article=resolved.topics_by_article,
            cloud_source="topics_raised",
            page_components=page_components,
            home_url=f"/{locale}/",
            site_context=context,
            data_assets_base=(f"/{data_dir}" if context is not None else None),
            assets_out=(locale_assets if context is not None else None),
        )
        if context is not None:
            # Language-neutral means language-neutral: every locale must derive the
            # same asset set, or localization has leaked into the shared data.
            if shared_assets is None:
                shared_assets = locale_assets
            elif shared_assets != locale_assets:
                raise ArtifactError(
                    "data islands are not language-neutral across locales: "
                    f"{sorted(shared_assets)} != {sorted(locale_assets)}"
                )
        cloud = check_rendered_concept_cloud(
            html,
            resolved.question_stats,
            [group.group_id for group in resolved.manifest.groups],
            source="topics_raised",
            topics_by_article=resolved.topics_by_article,
            articles=resolved.articles,
        )
        if not cloud.ok:
            raise ArtifactError(cloud.render())
        load = sentence_load(resolved.articles, shipped)
        over_budget = sorted(
            article_id
            for article_id, (used, total) in load.items()
            if total and used * 2 > total
        )
        if over_budget:
            raise ArtifactError(
                "public page would ship more than half the captured sentences of article(s): "
                + ", ".join(over_budget)
            )
        payload = html.encode("utf-8")
        relative = f"{locale}/topics/{resolved.page.topic_id}/index.html"
        write_closed_file(output_root, relative, payload)
        bundles.append(
            LocaleBundle(
                locale=locale,
                page_url=f"/{locale}/topics/{resolved.page.topic_id}/",
                page_hash=bytes_digest(payload),
            )
        )
    data_assets: list[DataAsset] = []
    for name, payload in sorted((shared_assets or {}).items()):
        write_closed_file(output_root, f"{data_dir}/{name}", payload)
        data_assets.append(
            DataAsset(
                name=name,
                url=f"/{data_dir}/{name}",
                sha256=bytes_digest(payload),
            )
        )
    scan_public_bundle(output_root)
    return bundles, data_assets


def render_candidate_bundle(
    resolved: ResolvedInputs,
    locales: Iterable[str],
    output_root: Path,
    *,
    m2: bool,
    theme: Optional[ThemeDefinition],
) -> tuple[list[LocaleBundle], list[DataAsset], list[ShareAsset]]:
    """Render the closed page/share/data bundle for one publication generation."""
    canonical_locales = tuple(normalize_lang(locale) for locale in locales)
    bundles, data_assets = render_locales(
        resolved,
        canonical_locales,
        output_root,
        m2=m2,
        theme=theme,
    )
    assets = []
    if m2:
        if theme is None:
            raise ArtifactError("M2 candidate requires a validated theme")
        assets = render_share_assets(
            resolved,
            canonical_locales,
            output_root,
            write_file=write_closed_file,
            digest=bytes_digest,
        )
    scan_public_bundle(output_root)
    return bundles, data_assets, assets


def _workers(resolved: ResolvedInputs) -> list[WorkerAttribution]:
    by_model: dict[str, dict[str, list[str]]] = {}
    stage_by_run = {pin.run_id: pin.stage for pin in resolved.pins}
    for pin in resolved.pins:
        if pin.stage == "scope":
            model_id = resolved.manifest.provenance.model_id
        else:
            entry = resolved.entry_by_id[pin.run_id]
            model_id = entry.model_id
        if not model_id:
            continue
        bucket = by_model.setdefault(model_id, {"stages": [], "runs": []})
        if stage_by_run[pin.run_id] not in bucket["stages"]:
            bucket["stages"].append(stage_by_run[pin.run_id])
        bucket["runs"].append(pin.run_id)
    workers = [
        WorkerAttribution(
            model_id=model_id,
            stages=sorted(data["stages"]),
            run_ids=sorted(data["runs"]),
        )
        for model_id, data in sorted(by_model.items())
    ]
    if not workers:
        raise ArtifactError("publication has no model-backed upstream worker attribution")
    return workers


def _catalog_record(
    publication: PublicationRecord,
    publication_hash: str,
    resolved: ResolvedInputs,
    metadata: SiteMetadata,
    locale: str,
    published_at: datetime,
) -> CatalogRecord:
    locale = normalize_lang(locale)
    bundle = next((item for item in publication.locales if item.locale == locale), None)
    if bundle is None:
        raise ArtifactError(f"publication does not ship locale {locale}")
    page = resolved.page
    manifest = resolved.manifest
    lexicon = page.lexicon
    groups = [
        CatalogSide(
            group_id=group.group_id,
            short_label=LangText(
                text=group_text(
                    lexicon, "group_short_labels", group.group_id,
                    group.short_label if group.short_label else group.label, locale,
                ),
                lang=locale,
            ),
            definition=LangText(
                text=group_text(
                    lexicon, "group_definitions", group.group_id, group.definition, locale,
                ),
                lang=locale,
            ),
        )
        for group in manifest.groups
    ]
    findings = {finding.finding_id: finding for finding in resolved.findings}
    share_by_question = {
        asset.question_id: asset
        for asset in publication.share_assets
        if asset.locale == locale
    }
    angles = []
    for angle in page.angles:
        question_text = page.lexicon.questions.get(angle.question_id) or angle.question_display
        answers = {
            side.group_id: (
                None
                if side.is_silent_side or side.answer_label is None
                else LangText(text=_text(side.answer_label, locale), lang=locale)
            )
            for side in angle.sides
        }
        finding = findings.get(angle.finding_id)
        angles.append(
            CatalogAngle(
                question_id=angle.question_id,
                question=LangText(text=_text(question_text, locale), lang=locale),
                finding_kind=angle.kind,
                answers=answers,
                counts={
                    side.group_id: f"{side.badge.numerator}/{side.badge.denominator}"
                    for side in angle.sides
                },
                strength=(finding.strength if finding is not None else None),
                stability=(finding.stability if finding is not None else None),
                fragment_url=f"{bundle.page_url}#angle-{angle.question_id}",
                share_card_url=(
                    share_by_question[angle.question_id].url
                    if angle.question_id in share_by_question
                    else None
                ),
                share_url=(
                    share_by_question[angle.question_id].landing_url
                    if angle.question_id in share_by_question
                    else None
                ),
            )
        )
    intro = page.intro[0].text
    scope_end = manifest.period.end or max(article.publish_date for article in resolved.articles)
    return CatalogRecord(
        publication_id=publication.publication_id,
        publication_hash=publication_hash,
        public_bundle_fingerprint=publication.public_bundle_fingerprint,
        topic_id=publication.topic_id,
        locale=locale,
        slug=publication.topic_id,
        page_url=bundle.page_url,
        title=LangText(text=_text(page.title, locale), lang=locale),
        brief=LangText(text=_text(intro, locale), lang=locale),
        sides=groups,
        scope_start=manifest.period.start,
        scope_end=scope_end,
        published_at=published_at,
        category_ids=metadata.topic_categories[publication.topic_id],
        source_languages=sorted({article.lang for article in resolved.articles}),
        reader_locales=[item.locale for item in publication.locales],
        report_count=len(readable_clusters_of_articles(resolved.articles)),
        angles=angles,
        sponsor=publication.sponsor,
        workers=publication.workers,
        share_card_url=(angles[0].share_card_url if angles else None),
        theme_accent=publication.theme_token,
        catalog_version=CATALOG_VERSION,
    )


def resolve_publication_locales(
    metadata: SiteMetadata,
    review_locale: str,
    requested: Optional[Iterable[str]] = None,
) -> tuple[str, ...]:
    """Decide which languages a publication ships, and refuse to ship fewer.

    The site's full localization set is site-owned metadata, not a call-site argument:
    one file names every language the site ships, so that is the default.

    A human reviews in exactly one language, because that is the only language they
    read.  Their approval is of the page, not of that one rendering of it, so it carries
    to every localization of the same approved bytes.  Two locales therefore always
    ship: the English pivot the page was written in, and the language the reviewer
    signed.  Dropping either leaves readers a site-owned fallback shell where they
    expect a page — which is how a published tree once shipped with no English at all.
    """
    locales = tuple(
        normalize_lang(locale)
        for locale in (metadata.locales if requested is None else requested)
    )
    floor = {PIVOT_LOCALE, normalize_lang(review_locale)}
    missing = sorted(floor - set(locales))
    if missing:
        raise ArtifactError(
            "a publication ships at least the English pivot and the reviewer's own "
            f"language; requested locales {list(locales)} are missing {missing}"
        )
    # Adding a language to the site metadata is only half of adding it: the chrome
    # around the article is renderer-owned and has to speak it too.  Say which half is
    # missing here, rather than failing on a dictionary lookup mid-render.
    unspoken = sorted(set(locales) - set(SITE_LOCALES))
    if unspoken:
        raise ArtifactError(
            f"the site chrome has no strings for {unspoken}: add them to "
            "newsab_publish.site_strings before shipping these languages"
        )
    return locales


def _publication_id(
    resolved: ResolvedInputs,
    review: PublicationReview,
    metadata_fingerprint: str,
    locales: Iterable[str],
    theme_token: str,
) -> str:
    digest = content_digest(
        {
            "topic_id": resolved.page.topic_id,
            "page_run_id": resolved.page.provenance.run_id,
            "review": review.model_dump(mode="json"),
            "metadata": metadata_fingerprint,
            "locales": list(locales),
            "producer": PACKAGE_VERSION,
            "theme_token": theme_token,
        }
    ).split(":", 1)[1][:12]
    return f"PUB-{resolved.page.topic_id}-{digest}"


def _page_bytes(bundle_root: Path, locale: str, topic_id: str) -> bytes:
    """One locale's rendered page out of a freshly built bundle tree."""
    return (bundle_root / locale / "topics" / topic_id / "index.html").read_bytes()


def _prove_equivalence(
    baseline: ContentBaseline,
    *,
    resolved: ResolvedInputs,
    review: PublicationReview,
    reviewed: LocaleBundle,
    reviewed_html: bytes,
    reviewed_data: Iterable[DataAsset],
    reviewed_locales: Iterable[str],
) -> ReviewedEquivalence:
    """Run both equivalence layers and mint the receipt, or refuse.

    Layer 1 compares the artifacts (``page.json`` projected onto the reviewed languages,
    the pinned upstream closure, the language-neutral data islands); Layer 2 compares the
    rendered bytes minus the closed whitelist.  Neither is a weaker byte check: together
    they say the approved content did not move and only renderer-owned and run-identity
    bytes did.
    """
    candidate_page = json.loads(
        (resolved.paths.stage_run_dir("editorial", resolved.page.provenance.run_id)
         / "page.json").read_text(encoding="utf-8")
    )
    locales = list(reviewed_locales)
    prove_content_equivalence(
        baseline,
        candidate_page,
        [(pin.stage, pin.run_id) for pin in resolved.pins if pin.stage != "page"],
        [(asset.name, asset.sha256) for asset in reviewed_data],
        locales,
    )
    digest, differences = prove_byte_equivalence(baseline, reviewed_html)
    return ReviewedEquivalence(
        reviewed_locale=review.locale,
        signed_page_hash=review.page_hash,
        signed_page_run_id=baseline.page_run_id,
        candidate_page_hash=reviewed.page_hash,
        redacted_digest=digest,
        whitelist_version=WHITELIST_VERSION,
        whitelisted_differences=differences,
        content_digest=content_digest(project_page(candidate_page, locales)),
    )


def signed_baseline(
    topics_root: str | Path,
    site_paths: SitePaths,
    publication: PublicationRecord,
) -> ContentBaseline:
    """What a backfill of ``publication`` measures its candidate against.

    Two shapes, and which one applies is the record's own answer.  A publication that
    still carries the user's exact bytes hands them over: they are read back out of
    its stored bundle and re-hashed against ``review.page_hash``, never trusted from a
    hash alone.  A publication that already stands on an equivalence proof hands over
    that proof's digest instead — chaining, because by the second language the site
    learns, the record holding the original bytes has long been superseded.  Either way
    the content side comes from this record's own page run and pins, which the standing
    proof has already tied to the signed ones.
    """
    proof = publication.reviewed_equivalence
    run_dir = TopicPaths.for_topic(
        publication_topics_root(topics_root, site_paths, publication), publication.topic_id
    ).stage_run_dir("editorial", publication.page_run_id)
    common = dict(
        page=json.loads((run_dir / "page.json").read_text(encoding="utf-8")),
        page_run_id=publication.page_run_id,
        closure=tuple(
            (pin.stage, pin.run_id)
            for pin in publication.run_closure
            if pin.stage != "page"
        ),
        data_assets=tuple(
            (asset.name, asset.sha256) for asset in publication.data_assets
        ),
    )
    if proof is not None:
        if proof.whitelist_version != WHITELIST_VERSION:
            raise ArtifactError(
                "the standing publication's equivalence proof was taken under a "
                f"different whitelist ({proof.whitelist_version} != "
                f"{WHITELIST_VERSION}); it cannot be chained onto"
            )
        return ContentBaseline(**common, prior_redacted_digest=proof.redacted_digest)
    page_path = (
        site_paths.publication_dir(publication.publication_id)
        / "bundle"
        / publication.review.locale
        / "topics"
        / publication.topic_id
        / "index.html"
    )
    if not page_path.is_file():
        raise ArtifactError(
            "the approved bundle for this publication is not on disk, so its signed "
            f"bytes cannot be re-proved: {page_path}"
        )
    signed_html = page_path.read_bytes()
    if bytes_digest(signed_html) != publication.review.page_hash:
        raise ArtifactError(
            "the stored bundle's reviewed page does not hash to the human-reviewed bytes"
        )
    return ContentBaseline(**common, page_html=signed_html)


def prepare_publication(
    topics_root: str | Path,
    site_root: str | Path,
    topic_id: str,
    *,
    page_run_id: str,
    review: PublicationReview,
    metadata: SiteMetadata,
    metadata_path: str | Path,
    locales: Optional[Iterable[str]] = None,
    default_locale: Optional[str] = None,
    theme_token: Optional[str] = None,
    theme_registry_path: str | Path | None = None,
    baseline: Optional[ContentBaseline] = None,
    submission: Optional[SubmissionProvenance] = None,
) -> PublicationRecord:
    """Build twice, bind exact reviewed bytes, then write one immutable candidate.

    ``baseline`` is the site-wide locale backfill's one concession and nobody else's:
    when the reviewed locale's bytes do not reproduce, the equivalence proof in
    ``newsab_publish.reviewed_equivalence`` may stand in for them.  Left ``None`` — every
    touchpoint-two path — the byte re-prove is the only thing that passes.

    ``default_locale`` — the row a reader who asks for a language this publication does
    not ship is shown instead — defaults to English, the pivot every reader-facing page
    is written from, so that a reader arriving in any other unshipped language lands on
    the one row every international reader can lean on.
    """
    resolved = resolve_inputs(topics_root, topic_id, page_run_id)
    metadata_bytes = Path(metadata_path).read_bytes()
    metadata_fingerprint = bytes_digest(metadata_bytes)
    if topic_id not in metadata.topic_categories:
        raise ArtifactError(f"site metadata has no approved taxonomy mapping for {topic_id}")
    locales = resolve_publication_locales(metadata, review.locale, locales)
    default_locale = normalize_lang(default_locale or "en")
    registry_path = Path(theme_registry_path or default_theme_registry_path())
    registry_bytes = registry_path.read_bytes()
    registry_fingerprint = bytes_digest(registry_bytes)
    registry = load_theme_registry(registry_path)
    theme = resolve_theme(theme_token, registry)
    # Coverage is checked against the set this publication actually ships, at the point
    # the labels are about to be rendered — not against a global on the model, which
    # would re-judge every archived registry every time the site learns a language.
    check_theme_labels(theme, locales)

    # A page names the other languages it exists in, so its bytes move when the locale
    # set does.  The reviewer approved the article, not the site's language list, so the
    # approval is re-proved against the set it was taken under: render that set too and
    # require the reviewed locale's bytes to reproduce exactly.  Content drift is caught
    # just as hard as before — the same pinned closure feeds both renders.
    reviewed_locales = (
        tuple(review.reviewed_locales) if review.reviewed_locales else locales
    )

    with tempfile.TemporaryDirectory(prefix="newsab-publish-a-") as first_name, tempfile.TemporaryDirectory(
        prefix="newsab-publish-b-"
    ) as second_name:
        first = Path(first_name)
        second = Path(second_name)
        bundles, data_assets, share_assets = render_candidate_bundle(
            resolved, locales, first, m2=True, theme=theme
        )
        render_candidate_bundle(resolved, locales, second, m2=True, theme=theme)
        first_fingerprint = directory_fingerprint(first)
        second_fingerprint = directory_fingerprint(second)
        if first_fingerprint != second_fingerprint:
            raise ArtifactError(
                "two fresh production renders differ: "
                f"{first_fingerprint} != {second_fingerprint}"
            )
        if reviewed_locales == locales:
            reviewed = next(bundle for bundle in bundles if bundle.locale == review.locale)
            reviewed_html = _page_bytes(first, review.locale, topic_id)
            reviewed_data = data_assets
        else:
            with tempfile.TemporaryDirectory(prefix="newsab-publish-r-") as reviewed_name:
                reviewed_root = Path(reviewed_name)
                reviewed_bundles, reviewed_data, _ = render_candidate_bundle(
                    resolved, reviewed_locales, reviewed_root, m2=True, theme=theme
                )
                reviewed_html = _page_bytes(reviewed_root, review.locale, topic_id)
            reviewed = next(
                bundle for bundle in reviewed_bundles if bundle.locale == review.locale
            )
        equivalence = None
        if reviewed.page_hash != review.page_hash:
            if baseline is None:
                raise ArtifactError(
                    "reviewed page hash does not match deterministic production bytes: "
                    f"{review.page_hash} != {reviewed.page_hash} "
                    f"(reviewed locale {review.locale} under locales {list(reviewed_locales)})"
                )
            equivalence = _prove_equivalence(
                baseline,
                resolved=resolved,
                review=review,
                reviewed=reviewed,
                reviewed_html=reviewed_html,
                reviewed_data=reviewed_data,
                reviewed_locales=reviewed_locales,
            )

        publication_id = _publication_id(
            resolved, review, metadata_fingerprint, locales, theme.token
        )
        prepared_at = review.decided_at
        record = PublicationRecord(
            publication_id=publication_id,
            topic_id=topic_id,
            page_run_id=page_run_id,
            run_closure=list(resolved.pins),
            review=review,
            default_locale=default_locale,
            locales=bundles,
            sponsor=submission.sponsor if submission else SponsorAttribution(anonymous=True),
            workers=_workers(resolved),
            share_assets=share_assets,
            data_assets=data_assets,
            theme_token=theme.token,
            theme_registry_version=registry.schema_version,
            theme_registry_fingerprint=registry_fingerprint,
            site_metadata_version=metadata.metadata_version,
            site_metadata_fingerprint=metadata_fingerprint,
            render_input_hashes={
                "topics_by_article.json": bytes_digest(resolved.topics_by_article_bytes),
                "theme_tokens.json": registry_fingerprint,
                "source_registry.yaml": bytes_digest(resolved.source_registry_bytes),
            },
            reviewed_equivalence=equivalence,
            public_bundle_fingerprint=first_fingerprint,
            submission_id=submission.submission_id if submission else None,
            submission_archive_hash=submission.archive_hash if submission else None,
            audit_run_id=submission.audit_run_id if submission else None,
            prepared_at=prepared_at,
            provenance=Provenance(
                skill_version=PACKAGE_VERSION,
                model_id=None,
                run_id=f"pub-{publication_id.rsplit('-', 1)[-1]}",
                timestamp=prepared_at,
            ),
        )

        site_paths = SitePaths.at(site_root).ensure()
        write_publication(site_paths, record)
        publication_dir = site_paths.publication_dir(publication_id)
        bundle_dir = publication_dir / "bundle"
        if bundle_dir.exists():
            raise ArtifactError(f"candidate bundle already exists: {bundle_dir}")
        shutil.copytree(first, bundle_dir)
        audit_dir = site_paths.audit_dir / publication_id
        audit_dir.mkdir(parents=True, exist_ok=False)
        (audit_dir / "topics_by_article.json").write_bytes(resolved.topics_by_article_bytes)
        (audit_dir / "site_metadata.json").write_bytes(metadata_bytes)
        (audit_dir / "theme_tokens.json").write_bytes(registry_bytes)
        (audit_dir / "source_registry.yaml").write_bytes(resolved.source_registry_bytes)
    return record


@dataclass(frozen=True)
class SubmissionProvenance:
    """What an externally submitted topic contributes to its publication record.

    A publication that came from a submission is not just "a topic that happens to live
    elsewhere": it names the archive it was built from, the independent semantic audit
    that cleared it, and the sponsor credit the contributor chose.  The record carries
    all of it so a later rebuild needs no flag and no operator memory.
    """

    submission_id: str
    archive_hash: str
    audit_run_id: str
    sponsor: SponsorAttribution
    topics_root: Path


def submission_topics_root(site_paths: SitePaths, submission_id: str) -> Path:
    """The topic tree of one imported submission, from the site store alone."""
    base = site_paths.imported_submission_dir(submission_id)
    record_path = base / "import.json"
    if not record_path.is_file():
        raise ArtifactError(f"submission is not imported here: {record_path}")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    namespace = record.get("namespace_path")
    if not isinstance(namespace, str) or not namespace:
        raise ArtifactError(f"{record_path}: import record names no namespace")
    if ".." in PurePosixPath(namespace).parts or PurePosixPath(namespace).is_absolute():
        raise ArtifactError(f"{record_path}: namespace path escapes the import")
    root = base / namespace / "topics"
    if not root.is_dir():
        raise ArtifactError(f"imported namespace has no topic tree: {root}")
    return root


def load_submission_provenance(
    site_paths: SitePaths, submission_id: str, topic_id: str
) -> SubmissionProvenance:
    """Read one import's provenance, or refuse to publish from it.

    The clean G3 record is required, not merely looked for: an external report reaching
    readers without a passing independent audit pinned into the record is the one thing
    this whole path exists to prevent.  It is a *risk* recommendation and never
    substitutes for the human review — both are required, neither replaces the other.
    """
    base = site_paths.imported_submission_dir(submission_id)
    record = json.loads((base / "import.json").read_text(encoding="utf-8"))
    if not record.get("verification_ok"):
        raise ArtifactError(f"{submission_id}: import did not pass verification")
    if record.get("source_topic_id") != topic_id:
        raise ArtifactError(
            f"{submission_id} imported topic {record.get('source_topic_id')!r}, "
            f"not {topic_id!r}"
        )
    archive_hash = record.get("archive_sha256")
    if not isinstance(archive_hash, str) or not archive_hash:
        raise ArtifactError(f"{submission_id}: import record has no archive hash")
    envelope = json.loads((base / "envelope.json").read_text(encoding="utf-8"))
    sponsor_payload = envelope.get("sponsor") or {"anonymous": True}
    sponsor = SponsorAttribution.model_validate(sponsor_payload)
    clean = []
    for path in sorted((base / "g3").glob("*.json")) if (base / "g3").is_dir() else ():
        audit = json.loads(path.read_text(encoding="utf-8"))
        if not audit.get("ok") or audit.get("archive_sha256") != archive_hash:
            continue
        run_id = audit.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ArtifactError(f"{path}: clean G3 record has no run_id to pin")
        clean.append(run_id)
    if not clean:
        raise ArtifactError(
            f"{submission_id}: no clean G3 record for this archive — an external "
            "submission may not be published without its independent audit"
        )
    if len(set(clean)) > 1:
        raise ArtifactError(
            f"{submission_id}: several clean G3 records ({sorted(set(clean))}); "
            "the publication must pin exactly one audit"
        )
    return SubmissionProvenance(
        submission_id=submission_id,
        archive_hash=archive_hash,
        audit_run_id=clean[0],
        sponsor=sponsor,
        topics_root=submission_topics_root(site_paths, submission_id),
    )


def publication_topics_root(
    topics_root: str | Path, site_paths: SitePaths, publication: PublicationRecord
) -> Path:
    """Where *this* publication's topic tree is — its own answer, not the caller's.

    Every rebuild walks all live publications with one ``--topics-root``, which works
    only while every published topic is in the same tree.  A submission's is not, so the
    record says so and this is the one place that reads it.
    """
    if publication.submission_id:
        return submission_topics_root(site_paths, publication.submission_id)
    return Path(topics_root)


def _resolved_for_publication(
    topics_root: str | Path, site_paths: SitePaths, publication: PublicationRecord
) -> ResolvedInputs:
    resolved = resolve_inputs(
        publication_topics_root(topics_root, site_paths, publication),
        publication.topic_id,
        publication.page_run_id,
    )
    if not _run_closure_matches(publication.run_closure, list(resolved.pins)):
        raise ArtifactError("publication run closure no longer matches the restorable topic runs")
    audit_map = site_paths.audit_dir / publication.publication_id / "topics_by_article.json"
    if not audit_map.is_file():
        raise ArtifactError(f"publication render input archive is missing: {audit_map}")
    payload = audit_map.read_bytes()
    expected = publication.render_input_hashes.get("topics_by_article.json")
    if expected != bytes_digest(payload):
        raise ArtifactError("archived topics_by_article bytes do not match PublicationRecord")
    try:
        mapping = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"invalid archived topics_by_article map: {exc}") from exc
    resolved = replace(
        resolved,
        topics_by_article=mapping,
        topics_by_article_bytes=payload,
    )
    # Publications that pin the outlet registry re-verify against those exact archived
    # bytes; older records without the pin keep reading the live registry as before.
    registry_pin = publication.render_input_hashes.get("source_registry.yaml")
    if registry_pin is not None:
        archived_registry = (
            site_paths.audit_dir / publication.publication_id / "source_registry.yaml"
        )
        if not archived_registry.is_file():
            raise ArtifactError(
                f"publication source registry archive is missing: {archived_registry}"
            )
        registry_payload = archived_registry.read_bytes()
        if bytes_digest(registry_payload) != registry_pin:
            raise ArtifactError("archived source registry bytes do not match PublicationRecord")
        resolved = replace(
            resolved,
            source_registry=_registry_from_bytes(registry_payload),
            source_registry_bytes=registry_payload,
        )
    return resolved


def _run_closure_matches(stored: list[TopicRunPin], restored: list[TopicRunPin]) -> bool:
    """Match immutable pins, recognizing only audited scope-hash migration aliases."""
    if len(stored) != len(restored):
        return False
    for before, now in zip(stored, restored):
        if before == now:
            continue
        if (
            before.stage != "scope"
            or now.stage != "scope"
            or before.topic_id != now.topic_id
            or before.run_id != now.run_id
            or _SCOPE_FINGERPRINT_ALIASES.get(before.artifact_fingerprint)
            != now.artifact_fingerprint
        ):
            return False
    return True


def _live_publication_ids(
    publications: Mapping[str, PublicationRecord],
    events: Iterable[PublicationEvent],
    selector,
) -> frozenset[str]:
    """The records in the re-render tier: live for their topic, or reviewed candidates
    the event stream has never touched (verifying one *is* the pre-activation check).
    Everything else is history, and its authority is the archived bundle plus the hash
    chain — see SUPPORTED_PACKAGE_VERSIONS."""
    mentioned: set[str] = set()
    for event in events:
        mentioned.add(event.publication_id)
        if event.replacement_publication_id is not None:
            mentioned.add(event.replacement_publication_id)
    live = set(selector.publications.values())
    return frozenset(
        publication_id
        for publication_id in publications
        if publication_id in live or publication_id not in mentioned
    )


def verify_candidate(
    topics_root: str | Path,
    site_root: str | Path,
    publication_id: str,
    *,
    live: bool | None = None,
) -> PublicationRecord:
    site_paths = SitePaths.at(site_root)
    publication = load_publication(site_paths, publication_id)
    resolved = _resolved_for_publication(topics_root, site_paths, publication)
    metadata_path = site_paths.audit_dir / publication_id / "site_metadata.json"
    if not metadata_path.is_file():
        raise ArtifactError(f"publication site metadata archive is missing: {metadata_path}")
    if file_digest(metadata_path) != publication.site_metadata_fingerprint:
        raise ArtifactError("archived site metadata bytes do not match PublicationRecord")

    producer = publication.provenance.skill_version
    if producer not in SUPPORTED_PACKAGE_VERSIONS:
        raise ArtifactError(f"unsupported publication producer: {producer}")
    if publication.theme_registry_fingerprint is not None:
        registry_path = site_paths.audit_dir / publication_id / "theme_tokens.json"
        if not registry_path.is_file():
            raise ArtifactError("publication theme registry archive is missing")
        registry_bytes = registry_path.read_bytes()
        registry_fingerprint = bytes_digest(registry_bytes)
        if registry_fingerprint != publication.theme_registry_fingerprint:
            raise ArtifactError("archived theme registry differs from PublicationRecord")
        if publication.render_input_hashes.get("theme_tokens.json") != registry_fingerprint:
            raise ArtifactError("theme registry render-input pin differs from archived bytes")
        registry = load_theme_registry(registry_path)
        if registry.schema_version != publication.theme_registry_version:
            raise ArtifactError("archived theme registry version differs from PublicationRecord")
        theme = resolve_theme(publication.theme_token, registry)
    else:
        theme = None
    if live is None:
        # Single-candidate callers let the event stream answer for liveness; verify_site
        # computes the selector once and passes ``live`` per record instead (O(n²) if
        # every record re-derived it here).
        publications = load_publications(site_paths)
        events = load_publication_events(site_paths)
        selector = derive_publish_selector(
            publications,
            events,
            publication_hashes=_publication_hashes(site_paths, publications),
        )
        live = publication_id in _live_publication_ids(publications, events, selector)
    if live and producer == PACKAGE_VERSION:
        # Only a record that is still live (or a candidate not yet activated) and was
        # stamped by today's producer is asked to reproduce its bytes with today's
        # renderer; a historical publication's authority is its stored immutable bundle
        # plus the hash chain, not an ever-moving re-render.
        with tempfile.TemporaryDirectory(prefix="newsab-verify-candidate-") as name:
            scratch = Path(name)
            rebuilt, rebuilt_data, rebuilt_assets = render_candidate_bundle(
                resolved,
                [bundle.locale for bundle in publication.locales],
                scratch,
                m2=True,
                theme=theme,
            )
            if rebuilt != publication.locales:
                raise ArtifactError("rebuilt locale page hashes/URLs differ from PublicationRecord")
            if rebuilt_data != publication.data_assets:
                raise ArtifactError("rebuilt data assets differ from PublicationRecord")
            if rebuilt_assets != publication.share_assets:
                raise ArtifactError("rebuilt share assets differ from PublicationRecord")
            if directory_fingerprint(scratch) != publication.public_bundle_fingerprint:
                raise ArtifactError("rebuilt candidate public fingerprint differs from PublicationRecord")
        # When the publication ships more languages than were on screen at touchpoint
        # two, the record cannot assert the reviewed hash against its own bundle.  Re-prove
        # it the only way that means anything: render the reviewed set again and require
        # the user's exact bytes back.
        reviewed_locales = publication.review.reviewed_locales
        shipped_locales = [bundle.locale for bundle in publication.locales]
        if reviewed_locales and sorted(reviewed_locales) != sorted(shipped_locales):
            with tempfile.TemporaryDirectory(prefix="newsab-verify-reviewed-") as name:
                reviewed_root = Path(name)
                reviewed_bundles, _, _ = render_candidate_bundle(
                    resolved, reviewed_locales, reviewed_root, m2=True, theme=theme
                )
                reviewed_html = _page_bytes(
                    reviewed_root, publication.review.locale, publication.topic_id
                )
            signed = next(
                bundle
                for bundle in reviewed_bundles
                if bundle.locale == publication.review.locale
            )
            proof = publication.reviewed_equivalence
            if signed.page_hash != publication.review.page_hash and proof is None:
                raise ArtifactError(
                    "re-rendering the reviewed locale set does not reproduce the "
                    f"human-reviewed bytes: {publication.review.page_hash} != "
                    f"{signed.page_hash}"
                )
            if proof is not None:
                # The record does not reproduce the user's bytes and never claimed to;
                # what it claims is that the difference lay entirely inside the whitelist
                # it names.  Replay that claim against a fresh render — no need for the
                # superseded bundle, which is what makes the proof durable.
                if signed.page_hash != proof.candidate_page_hash:
                    raise ArtifactError(
                        "re-rendering the reviewed locale set does not reproduce the "
                        "bytes this publication's equivalence proof was taken on: "
                        f"{proof.candidate_page_hash} != {signed.page_hash}"
                    )
                if proof.whitelist_version != WHITELIST_VERSION:
                    raise ArtifactError(
                        "the equivalence proof was taken under a different whitelist: "
                        f"{proof.whitelist_version} != {WHITELIST_VERSION}"
                    )
                replayed, _ = redacted_digest(reviewed_html)
                if replayed != proof.redacted_digest:
                    raise ArtifactError(
                        "the equivalence proof does not replay: redacted "
                        f"{proof.redacted_digest} != {replayed}"
                    )
    stored_bundle = site_paths.publication_dir(publication_id) / "bundle"
    scan_public_bundle(stored_bundle)
    if directory_fingerprint(stored_bundle) != publication.public_bundle_fingerprint:
        raise ArtifactError("stored candidate bundle differs from PublicationRecord")
    return publication


def _publication_time(events: Iterable[PublicationEvent], publication_id: str) -> datetime:
    times = []
    for event in events:
        if event.publication_id == publication_id and event.event_type.value in {"publish", "restore"}:
            times.append(event.occurred_at)
        if (
            event.event_type.value == "supersede"
            and event.replacement_publication_id == publication_id
        ):
            times.append(event.occurred_at)
    if not times:
        raise ArtifactError(f"live publication has no activating event: {publication_id}")
    return max(times)


def _publication_hashes(site_paths: SitePaths, publications: Mapping[str, PublicationRecord]) -> dict[str, str]:
    return {
        publication_id: file_digest(site_paths.publication_record(publication_id))
        for publication_id in publications
    }


def write_chrome_assets(root: str | Path, registry: Optional[ThemeRegistry] = None) -> dict[str, str]:
    """Place the chrome files in a servable root and return their hashes.

    A candidate bundle never contains them, so anything that serves candidate bytes — the
    review preview, the browser gate, the dev shell — has to lay them down beside the
    pages.  This is the single helper that does it.
    """
    resolved = registry if registry is not None else site_theme_registry()
    target = Path(root)
    written = {}
    for relative, payload in sorted(chrome.chrome_assets(resolved).items()):
        path = target.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        written[relative] = bytes_digest(payload)
    return written


def _released(payload: bytes, relative: str, base_url: str) -> bytes:
    """One deployed page = the approved page ⊕ the release origin.

    Only HTML passes through the crawler-metadata resolution, and only its Open Graph
    block moves; see ``crawler_meta`` for why the origin cannot live in approved bytes.
    """
    if not relative.endswith(".html"):
        return payload
    return crawler_meta.resolve(payload, base_url=base_url)


def site_theme_registry(path: str | Path | None = None) -> ThemeRegistry:
    """The registry the *site* is currently shipping as chrome.

    A publication pins the registry bytes it was prepared against for audit, but the
    colours a live page shows come from the chrome layer, so the release reads the
    checked-in registry rather than any one publication's archive.
    """
    return load_theme_registry(path or default_theme_registry_path())


def build_production_tree(
    topics_root: str | Path,
    site_paths: SitePaths,
    metadata: SiteMetadata,
    events: Iterable[PublicationEvent],
    output_root: Path,
    *,
    base_url: str,
    build_date: date,
    theme_registry: Optional[ThemeRegistry] = None,
) -> tuple[dict[str, list[CatalogRecord]], str]:
    """Derive one complete static release from immutable records plus the event stream."""
    # Imported lazily so the lower-level candidate builder remains usable in isolation.
    from .home import render_home
    from .fallback import render_locale_fallback, render_root_redirect
    from .legal import legal_pages
    from .seo import render_robots, render_sitemap

    registry = theme_registry if theme_registry is not None else site_theme_registry()
    publications = load_publications(site_paths)
    sequence = list(events)
    selector = derive_publish_selector(
        publications,
        sequence,
        publication_hashes=_publication_hashes(site_paths, publications),
    )
    catalogs: dict[str, list[CatalogRecord]] = {locale: [] for locale in metadata.locales}
    all_catalog_rows: list[CatalogRecord] = []
    for topic_id, publication_id in sorted(selector.publications.items()):
        publication = publications[publication_id]
        # A publication keeps the metadata revision used when it was prepared as audit
        # provenance. The site may later remap that published topic in a new site-owned
        # taxonomy revision without altering or republishing the article bytes.
        archived_metadata = site_paths.audit_dir / publication_id / "site_metadata.json"
        if (
            not archived_metadata.is_file()
            or file_digest(archived_metadata) != publication.site_metadata_fingerprint
        ):
            raise ArtifactError(f"{publication_id}: archived site metadata is missing or changed")
        archived_metadata_model = SiteMetadata.model_validate_json(
            archived_metadata.read_text(encoding="utf-8")
        )
        if archived_metadata_model.metadata_version != publication.site_metadata_version:
            raise ArtifactError(
                f"{publication_id}: archived site metadata version differs from its pin"
            )
        if topic_id not in metadata.topic_categories:
            raise ArtifactError(f"current site metadata has no taxonomy mapping for {topic_id}")
        candidate = site_paths.publication_dir(publication_id) / "bundle"
        if directory_fingerprint(candidate) != publication.public_bundle_fingerprint:
            raise ArtifactError(f"{publication_id}: stored candidate bundle fingerprint changed")
        for source in sorted(path for path in candidate.rglob("*") if path.is_file()):
            relative = source.relative_to(candidate).as_posix()
            write_closed_file(output_root, relative, _released(source.read_bytes(), relative, base_url))
        resolved = _resolved_for_publication(topics_root, site_paths, publication)
        published_at = _publication_time(sequence, publication_id)
        publication_hash = file_digest(site_paths.publication_record(publication_id))
        publication_rows: dict[str, CatalogRecord] = {}
        for bundle in publication.locales:
            row = _catalog_record(
                publication,
                publication_hash,
                resolved,
                metadata,
                bundle.locale,
                published_at,
            )
            catalogs.setdefault(bundle.locale, []).append(row)
            all_catalog_rows.append(row)
            publication_rows[bundle.locale] = row
        default_row = publication_rows.get(publication.default_locale)
        if default_row is None:
            raise ArtifactError(f"{publication_id}: default locale has no catalog row")
        actual_urls = {bundle.locale: bundle.page_url for bundle in publication.locales}
        for site_locale in sorted(set(metadata.locales) - set(actual_urls)):
            fallback = render_locale_fallback(
                default_row,
                site_locale=site_locale,
                actual_locale_urls=actual_urls,
            )
            write_closed_file(
                output_root,
                f"{site_locale}/topics/{topic_id}/index.html",
                _released(
                    fallback.encode("utf-8"),
                    f"{site_locale}/topics/{topic_id}/index.html",
                    base_url,
                ),
            )

    for locale in metadata.locales:
        rows = sorted(
            catalogs.get(locale, []),
            key=lambda row: (-row.published_at.timestamp(), row.publication_id),
        )
        catalogs[locale] = rows
        catalog_payload = "".join(dump_record(row) + "\n" for row in rows).encode("utf-8")
        write_closed_file(output_root, f"catalog/{locale}.jsonl", catalog_payload)
        home = render_home(
            rows,
            locale=locale,
            metadata=metadata,
            build_date=build_date,
            canonical_url=f"/{locale}/",
            alternate_urls={item: f"/{item}/" for item in metadata.locales},
            # English is the pivot every other locale was translated from, so an English
            # search term finds the same topics on every homepage.
            pivot_records={
                row.publication_id: row for row in catalogs.get(PIVOT_LOCALE, [])
            },
        )
        write_closed_file(
            output_root,
            f"{locale}/index.html",
            _released(home.encode("utf-8"), f"{locale}/index.html", base_url),
        )

    # The root is deterministic and contains no topic content: a blank sheet that sends
    # each browser to its own language's homepage, the English pivot when none matches.
    # It still passes through the release-owned head resolver so every browser entry
    # point carries the same chrome favicon.
    root_fallback = render_root_redirect(
        metadata.locales, default_locale=PIVOT_LOCALE
    ).encode("utf-8")
    write_closed_file(
        output_root,
        "index.html",
        _released(root_fallback, "index.html", base_url),
    )
    # The site chrome is written once per release at its stable URLs.  It is part of the
    # deployed closed list and the public fingerprint, and deliberately not part of any
    # candidate bundle: that is the whole point of the split.
    for relative, payload in sorted(chrome.chrome_assets(registry).items()):
        write_closed_file(output_root, relative, payload)
    # Legal notices are release chrome too: the forms link to them, so a release that
    # carries the forms carries the exact text they point at (official identity only).
    for relative, payload in sorted(legal_pages().items()):
        write_closed_file(output_root, relative, _released(payload, relative, base_url))
    sitemap = render_sitemap(
        all_catalog_rows,
        metadata=metadata,
        base_url=base_url,
        build_date=build_date,
    )
    write_closed_file(output_root, "sitemap.xml", sitemap.encode("utf-8"))
    robots = render_robots(base_url=base_url)
    write_closed_file(output_root, "robots.txt", robots.encode("utf-8"))
    scan_public_bundle(output_root)
    return catalogs, directory_fingerprint(output_root)


def event_time(
    approval: HumanApproval, events: "list[PublicationEvent]", *, now: Optional[datetime] = None
) -> datetime:
    """When the change happens — not when the human decided it.

    Both facts survive; the decision keeps its own timestamp inside ``approval``.  Reading
    the event time *off* the approval is what breaks the moment one sitting authorizes
    several topics: those clicks land inside the same second, in an order that has nothing
    to do with the order the candidates are then activated in, and the chain refuses a
    backwards step.  The two floors keep it monotonic and keep an event from preceding the
    approval that authorized it.
    """
    occurred_at = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    for floor in (approval.decided_at, events[-1].occurred_at if events else None):
        if floor is not None and occurred_at < floor:
            occurred_at = floor
    return occurred_at


def _event_id(
    occurred_at: datetime, approval: HumanApproval, operation: str, publication_id: str
) -> str:
    stamp = occurred_at.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = content_digest(
        {
            "approval": approval.model_dump(mode="json"),
            "operation": operation,
            "publication_id": publication_id,
        }
    ).split(":", 1)[1][:8]
    return f"EVT-{stamp}-{suffix}"


def make_event(
    site_paths: SitePaths,
    publication_id: str,
    approval: HumanApproval,
    *,
    operation: str,
    replacement_publication_id: Optional[str] = None,
    reason: Optional[LangText] = None,
    now: Optional[datetime] = None,
) -> PublicationEvent:
    publications = load_publications(site_paths)
    if publication_id not in publications:
        raise ArtifactError(f"publication does not exist: {publication_id}")
    events = load_publication_events(site_paths)
    previous = (
        content_digest(events[-1].model_dump(mode="json")) if events else None
    )
    replacement_hash = None
    if replacement_publication_id:
        if replacement_publication_id not in publications:
            raise ArtifactError(
                f"replacement publication does not exist: {replacement_publication_id}"
            )
        replacement_hash = file_digest(
            site_paths.publication_record(replacement_publication_id)
        )
    occurred_at = event_time(approval, events, now=now)
    return PublicationEvent(
        event_id=_event_id(occurred_at, approval, operation, publication_id),
        event_type=operation,
        publication_id=publication_id,
        publication_hash=file_digest(site_paths.publication_record(publication_id)),
        replacement_publication_id=replacement_publication_id,
        replacement_publication_hash=replacement_hash,
        reason=reason,
        approval=approval,
        occurred_at=occurred_at,
        previous_event_hash=previous,
        provenance=Provenance(
            skill_version=PACKAGE_VERSION,
            model_id=None,
            run_id=(
                "evt-"
                + _event_id(occurred_at, approval, operation, publication_id).rsplit("-", 1)[-1]
            ),
            timestamp=occurred_at,
        ),
    )


def _write_catalog_cache(site_paths: SitePaths, catalogs: Mapping[str, list[CatalogRecord]]) -> None:
    site_paths.catalog_dir.mkdir(parents=True, exist_ok=True)
    for locale, rows in sorted(catalogs.items()):
        target = site_paths.catalog(locale)
        temporary = target.with_name(f".{target.name}-{os.getpid()}.tmp")
        temporary.write_text(
            "".join(dump_record(row) + "\n" for row in rows), encoding="utf-8"
        )
        os.replace(temporary, target)


def _atomic_replace_tree(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.with_name(f".{target.name}-previous-{os.getpid()}")
    if previous.exists():
        shutil.rmtree(previous)
    if target.exists():
        os.replace(target, previous)
    try:
        os.replace(source, target)
    except Exception:
        if previous.exists() and not target.exists():
            os.replace(previous, target)
        raise
    if previous.exists():
        shutil.rmtree(previous)


def _is_canonical_public(site_paths: SitePaths, production_dir: str | Path) -> bool:
    """Whether ``production_dir`` is the site's own public tree.

    The release record and the site catalog cache describe exactly one tree.  A build
    pointed anywhere else (a local preview, a scratch check) must not overwrite the
    authority records for ``site/public``.
    """
    return Path(production_dir).resolve() == (site_paths.root / "public").resolve()


def _write_release_record(
    site_paths: SitePaths,
    *,
    fingerprint: str,
    build_date: date,
    base_url: str,
    metadata: SiteMetadata,
    theme_registry: Optional[ThemeRegistry] = None,
) -> None:
    registry = theme_registry if theme_registry is not None else site_theme_registry()
    payload = {
        "base_url": base_url,
        "build_date": build_date.isoformat(),
        "site_metadata_fingerprint": content_digest(metadata.model_dump(mode="json")),
        "site_metadata_version": metadata.metadata_version,
        "public_fingerprint": fingerprint,
        "producer": PACKAGE_VERSION,
        # Chrome is a site-release fact, not a publication fact: this is the record that
        # says which stylesheet/script bytes the approved content documents were served
        # with, without any of them having to name it.
        "chrome": chrome.chrome_release(registry, bytes_digest),
    }
    target = site_paths.production_dir / "release.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}-{os.getpid()}.tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    os.replace(temporary, target)


def activate_publication(
    topics_root: str | Path,
    site_root: str | Path,
    publication_id: str,
    *,
    approval: HumanApproval,
    metadata: SiteMetadata,
    production_dir: str | Path,
    base_url: str,
    build_date: date,
    reason: Optional[LangText] = None,
    now: Optional[datetime] = None,
) -> PublicationEvent:
    site_paths = SitePaths.at(site_root).ensure()
    publications = load_publications(site_paths)
    existing_events = load_publication_events(site_paths)
    selector = derive_publish_selector(
        publications,
        existing_events,
        publication_hashes=_publication_hashes(site_paths, publications),
    )
    rerender_tier = _live_publication_ids(publications, existing_events, selector)
    publication = verify_candidate(
        topics_root, site_root, publication_id, live=publication_id in rerender_tier
    )
    live = selector.publications.get(publication.topic_id)
    if live is None:
        operation = "publish"
        target = publication_id
        replacement = None
        event_reason = None
    else:
        if live == publication_id:
            raise ArtifactError(f"publication is already live: {publication_id}")
        operation = "supersede"
        target = live
        replacement = publication_id
        event_reason = reason
        if event_reason is None:
            raise ArtifactError("supersede requires an explicit approved reason")
    event = make_event(
        site_paths,
        target,
        approval,
        operation=operation,
        replacement_publication_id=replacement,
        reason=event_reason,
        now=now,
    )
    with tempfile.TemporaryDirectory(
        prefix="newsab-production-", dir=Path(production_dir).parent
    ) as temporary_name:
        scratch = Path(temporary_name) / "release"
        scratch.mkdir()
        catalogs, fingerprint = build_production_tree(
            topics_root,
            site_paths,
            metadata,
            [*existing_events, event],
            scratch,
            base_url=base_url,
            build_date=build_date,
        )
        append_publication_event(site_paths, event)
        # The event is authority; the selector, catalog and public tree are derived and
        # can be rebuilt if this local filesystem switch is interrupted.
        _atomic_replace_tree(scratch, Path(production_dir))
        if _is_canonical_public(site_paths, production_dir):
            _write_catalog_cache(site_paths, catalogs)
            _write_release_record(
                site_paths,
                fingerprint=fingerprint,
                build_date=build_date,
                base_url=base_url,
                metadata=metadata,
            )
    return event


def rebuild_production(
    topics_root: str | Path,
    site_root: str | Path,
    *,
    metadata: SiteMetadata,
    production_dir: str | Path,
    base_url: str,
    build_date: date,
) -> str:
    site_paths = SitePaths.at(site_root).ensure()
    events = load_publication_events(site_paths)
    with tempfile.TemporaryDirectory(
        prefix="newsab-production-", dir=Path(production_dir).parent
    ) as temporary_name:
        scratch = Path(temporary_name) / "release"
        scratch.mkdir()
        catalogs, fingerprint = build_production_tree(
            topics_root,
            site_paths,
            metadata,
            events,
            scratch,
            base_url=base_url,
            build_date=build_date,
        )
        _atomic_replace_tree(scratch, Path(production_dir))
        if _is_canonical_public(site_paths, production_dir):
            _write_catalog_cache(site_paths, catalogs)
            _write_release_record(
                site_paths,
                fingerprint=fingerprint,
                build_date=build_date,
                base_url=base_url,
                metadata=metadata,
            )
    return fingerprint


def lifecycle_event(
    topics_root: str | Path,
    site_root: str | Path,
    publication_id: str,
    *,
    operation: str,
    approval: HumanApproval,
    reason: LangText,
    metadata: SiteMetadata,
    production_dir: str | Path,
    base_url: str,
    build_date: date,
) -> PublicationEvent:
    if operation not in {"withdraw", "restore", "audit_delete"}:
        raise ArtifactError(f"unsupported lifecycle operation: {operation}")
    site_paths = SitePaths.at(site_root).ensure()
    existing_events = load_publication_events(site_paths)
    event = make_event(
        site_paths,
        publication_id,
        approval,
        operation=operation,
        reason=reason,
    )
    with tempfile.TemporaryDirectory(
        prefix="newsab-production-", dir=Path(production_dir).parent
    ) as temporary_name:
        scratch = Path(temporary_name) / "release"
        scratch.mkdir()
        catalogs, fingerprint = build_production_tree(
            topics_root,
            site_paths,
            metadata,
            [*existing_events, event],
            scratch,
            base_url=base_url,
            build_date=build_date,
        )
        append_publication_event(site_paths, event)
        _atomic_replace_tree(scratch, Path(production_dir))
        if _is_canonical_public(site_paths, production_dir):
            _write_catalog_cache(site_paths, catalogs)
            _write_release_record(
                site_paths,
                fingerprint=fingerprint,
                build_date=build_date,
                base_url=base_url,
                metadata=metadata,
            )
    return event


def _verify_released_pages(
    site_paths: SitePaths,
    selector,
    publications: Mapping[str, PublicationRecord],
    production_dir: Path,
    base_url: str,
) -> None:
    """Bind every deployed page to its approved bytes plus the release origin.

    The approval is on the bundle; the origin and the crawler card are the release's.
    Stating that relation as a check is what keeps "deployed = approved ⊕ origin" an
    audited fact rather than a promise made once inside the builder.
    """
    for publication_id in sorted(set(selector.publications.values())):
        bundle = site_paths.publication_dir(publication_id) / "bundle"
        for source in sorted(path for path in bundle.rglob("*.html") if path.is_file()):
            relative = source.relative_to(bundle).as_posix()
            deployed = production_dir / relative
            if not deployed.is_file():
                raise ArtifactError(f"{publication_id}: released page is missing: {relative}")
            approved = source.read_bytes()
            expected = crawler_meta.resolve(approved, base_url=base_url)
            if deployed.read_bytes() != expected:
                raise ArtifactError(
                    f"{publication_id}: released page is not its approved bytes under the "
                    f"release origin: {relative}"
                )
            crawler_meta.check_resolved(expected, base_url=base_url, label=relative)


def verify_site(
    topics_root: str | Path,
    site_root: str | Path,
    production_dir: str | Path,
    *,
    metadata: SiteMetadata,
) -> str:
    site_paths = SitePaths.at(site_root)
    publications = load_publications(site_paths)
    events = load_publication_events(site_paths)
    selector = derive_publish_selector(
        publications,
        events,
        publication_hashes=_publication_hashes(site_paths, publications),
    )
    # Liveness is decided once from the event stream and passed down; letting each
    # verify_candidate re-derive it would reload the whole store per record (O(n²)).
    rerender_tier = _live_publication_ids(publications, events, selector)
    for publication_id in publications:
        verify_candidate(
            topics_root,
            site_root,
            publication_id,
            live=publication_id in rerender_tier,
        )
    if not site_paths.production_selector.is_file():
        raise ArtifactError("derived production selector is missing")
    stored_selector = json.loads(site_paths.production_selector.read_text(encoding="utf-8"))
    if stored_selector != selector.model_dump(mode="json"):
        raise ArtifactError("stored production selector does not match the event stream")
    release_path = site_paths.production_dir / "release.json"
    if not release_path.is_file():
        raise ArtifactError("production release record is missing")
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release_producer = release.get("producer")
    if release_producer not in SUPPORTED_PACKAGE_VERSIONS:
        raise ArtifactError("production release producer version is unexpected")
    if release.get("site_metadata_version") != metadata.metadata_version:
        raise ArtifactError("production release pins a different site metadata version")
    if release.get("site_metadata_fingerprint") != content_digest(
        metadata.model_dump(mode="json")
    ):
        raise ArtifactError("production release pins different site metadata bytes")
    if not _HASH.fullmatch(str(release.get("public_fingerprint", ""))):
        raise ArtifactError("production release fingerprint is invalid")
    # A release that names chrome assets must still be serving exactly those bytes.  A
    # release minted before the content/chrome split names none, and is verified whole by
    # its fingerprint as before.
    chrome.verify_chrome_release(Path(production_dir), release.get("chrome") or {}, bytes_digest)
    _verify_released_pages(
        site_paths, selector, publications, Path(production_dir), release["base_url"]
    )
    scan_public_bundle(Path(production_dir))
    actual = directory_fingerprint(Path(production_dir))
    if actual != release["public_fingerprint"]:
        raise ArtifactError(
            f"production directory fingerprint differs: {actual} != {release['public_fingerprint']}"
        )
    # A release minted by an older producer deliberately retains its exact old
    # home/catalog bytes; the scanner and fingerprint above verify that deployed closed
    # tree as-is.  Only a current-producer release is asked to reproduce itself with
    # today's derivation code — a current-code rebuild of an old release would be a new
    # release, not a restoration of those bytes.
    if release_producer != PACKAGE_VERSION:
        return actual
    # Rebuild in a fresh root from the stored explicit date/base URL and compare bytes.
    with tempfile.TemporaryDirectory(prefix="newsab-verify-site-") as name:
        scratch = Path(name)
        rebuilt_catalogs, rebuilt = build_production_tree(
            topics_root,
            site_paths,
            metadata,
            events,
            scratch,
            base_url=release["base_url"],
            build_date=date.fromisoformat(release["build_date"]),
        )
        if rebuilt != actual:
            raise ArtifactError(f"fresh production rebuild differs: {rebuilt} != {actual}")
        for locale, rows in rebuilt_catalogs.items():
            expected = "".join(dump_record(row) + "\n" for row in rows)
            target = site_paths.catalog(locale)
            if not target.is_file() or target.read_text(encoding="utf-8") != expected:
                raise ArtifactError(f"derived catalog cache differs for locale {locale}")
    return actual
