"""The Dev Shell: one local command that puts every human touchpoint in a browser.

Why this exists: the reviewer's work was spread across a file-tree of previews, a
repo-root index page, a hand-copied page hash, a separate theme picker and an ad-hoc
``python -m http.server``.  This is one loopback command that indexes
all of it and lets the two human touchpoints be *taken* in the browser, while the
authority moves — activate, supersede, withdraw — stay on the publish CLI where a
deliberate command is the point.

Three rules this module is built to keep:

1. **Nothing dev-shaped is ever injected into a page under review.** The bytes served are
   the bytes that ship.  Every control lives in the dashboard beside the link, never
   inside the document — otherwise "approve these exact bytes" would be a lie.
2. **Roots are roots.** Production pages use root-relative URLs, so each servable tree
   gets its own loopback port instead of a path prefix.
3. **Writes are whitelisted and derived-only.** The shell writes approval, review-note and
   proposal artifacts in their existing formats; it never edits a publication, an event, a
   catalog or the public tree.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional
from urllib.parse import unquote

from newsab_schema import HALO_LOCALE_CODES, HALO_LOCALES, halo_locale
from newsab_schema.common import LangText, normalize_lang
from newsab_schema.io import ArtifactError, load_yaml_text, read_yaml
from newsab_schema.models.corpus import TopicManifest
from newsab_schema.models.manifest import file_digest
from newsab_schema.models.publication import HumanApproval, LocalePlan, PublicationReview

from .metadata import TopicCategoryApproval
from newsab_schema.paths import SitePaths, TopicPaths
from newsab_schema.store import (
    derive_publish_selector,
    load_publication_events,
    load_publications,
)

from . import chrome
from .builder import bytes_digest
from .dashboard_strings import DEFAULT_DASHBOARD_LOCALE, dashboard_strings
from .identity import site_identity
from .static_server import OverlayHandler, make_handler, serve_forever_in_thread
from .themes import load_theme_registry


DASHBOARD_TITLE = site_identity().dashboard_title
#: The port ``dev-serve`` tries first when the operator does not pass ``--port``.
DEFAULT_DASHBOARD_PORT = 8787
#: Where browser-taken decisions land.  ``site/private/`` is never deployed and never
#: committed, which is exactly right for a decision record that a CLI command then
#: consumes.
APPROVALS_DIR = "approvals"
NOTES_DIR = "review_notes"
PROPOSALS_DIR = "theme_proposals"
#: Local operator panels: static HTML that a script (never a model, never this shell)
#: generated under ``site/private/``.  The dashboard lists and serves whatever is there,
#: because a step that ends in human review must end in a clickable ``http://`` link —
#: and it knows nothing about any specific panel: a checkout that generates none (a
#: public clone, a fresh machine) simply has no such section.
PANELS_DIR = "panels"


# --------------------------------------------------------------------------- servable roots


@dataclass(frozen=True)
class ServedRoot:
    """One tree served at its own loopback root, because its URLs are root-relative."""

    key: str
    kind: str  # "production" | "candidate" | "preview"
    label: str
    path: Path
    port: int
    topic_id: Optional[str] = None
    publication_id: Optional[str] = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@dataclass(frozen=True)
class ReviewPage:
    """One reviewable HTML document: where it is, and the exact bytes it is."""

    root_key: str
    topic_id: str
    locale: str
    url_path: str
    page_hash: str
    origin: str

    @property
    def url(self) -> str:
        return f"{self.origin}{self.url_path}"


#: Written into a review root beside the pages so the shell can tell a reviewer exactly
#: what their approval leads to.  It is review scaffolding, never part of a bundle.
REVIEW_MANIFEST = "review_manifest.json"


def write_review_manifest(
    root: str | Path,
    *,
    topic_id: str,
    page_run_id: str,
    theme_token: str,
    locales: Iterable[str],
    bundles: Iterable,
    categories: Iterable[str] = (),
    review_locale: str = "",
    candidate_fingerprint: str = "",
) -> Path:
    """Record which pinned run produced each page in a review root (merge-aware).

    ``categories`` is the site taxonomy the publishing agent *proposes* for this topic.
    It rides along so the review card can show it while the reviewer reads the page: the
    category a reader filters the home page by is part of what touchpoint two covers, not
    a second question asked afterwards.

    ``candidate_fingerprint`` is the bundle these pages belong to; on the submission path
    it has been proved equal to the archive verifier's independent recomputation before
    it is written here.

    ``review_locale`` rides along for the same reason the theme token does: it is a fact
    about the topic that was resolved when this preview was rendered, and the shell has no
    other way back to it.  A submission preview's topic tree lives in an imported
    namespace, not under the repo's ``topics/``, so a shell that re-reads the manifest by
    topic id finds nothing and offers no approval at all.
    """
    target = Path(root) / REVIEW_MANIFEST
    payload = {"topics": {}}
    if target.is_file():
        existing = _read_json(target)
        if isinstance(existing, dict) and isinstance(existing.get("topics"), dict):
            payload = existing
    payload["topics"][topic_id] = {
        "page_run_id": page_run_id,
        "theme_token": theme_token,
        "locales": list(locales),
        "page_hashes": {bundle.locale: bundle.page_hash for bundle in bundles},
        "categories": list(categories),
        "review_locale": review_locale,
        # The fingerprint of the exact bundle these pages came from.  On the submission
        # path ``review-preview`` has already proved it equals the verifier's own
        # recomputation; recording it here means the review root carries that
        # evidence for anyone reading it afterwards, rather than it living only in the
        # console output of the command that rendered.
        "candidate_fingerprint": candidate_fingerprint,
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def read_review_manifest(root: Path) -> dict:
    payload = _read_json(root / REVIEW_MANIFEST)
    topics = (payload or {}).get("topics")
    return topics if isinstance(topics, dict) else {}


def _topic_pages(root: Path) -> list[tuple[str, str, str]]:
    """(topic_id, locale, url path) for every topic page in a served tree."""
    found = []
    for path in sorted(root.glob("*/topics/*/index.html")):
        locale = path.parents[2].name
        topic_id = path.parent.name
        found.append((topic_id, locale, f"/{locale}/topics/{topic_id}/"))
    return found


def review_pages(root: ServedRoot) -> list[ReviewPage]:
    pages = []
    for topic_id, locale, url_path in _topic_pages(root.path):
        payload = (root.path / url_path.strip("/") / "index.html").read_bytes()
        pages.append(
            ReviewPage(
                root_key=root.key,
                topic_id=topic_id,
                locale=locale,
                url_path=url_path,
                page_hash=bytes_digest(payload),
                origin=root.origin,
            )
        )
    return pages


def pending_publications(site_paths: SitePaths) -> list[str]:
    """Candidates that no lifecycle event has ever touched — "approved, not published".

    A live publication is already reachable through the production tree, and a superseded
    one is history: neither needs a port of its own.  Only the undecided ones do.
    """
    publications = load_publications(site_paths)
    touched: set[str] = set()
    for event in load_publication_events(site_paths):
        touched.add(event.publication_id)
        if event.replacement_publication_id:
            touched.add(event.replacement_publication_id)
    return sorted(set(publications) - touched)


def _hashes_in_previews(preview_dirs: Iterable[Path]) -> set[str]:
    """Every page hash any registered preview root already serves."""
    found: set[str] = set()
    for directory in preview_dirs:
        for entry in read_review_manifest(Path(directory)).values():
            found.update(str(item) for item in (entry.get("page_hashes") or {}).values())
    return found


def discover_roots(
    site_paths: SitePaths,
    production_dir: Path,
    preview_dirs: Iterable[Path],
    base_port: int,
    candidate_ids: Optional[Iterable[str]] = None,
) -> list[ServedRoot]:
    """Assign one deterministic loopback port per servable tree.

    Deterministic because the reviewer keeps these tabs open: a candidate that has not
    changed should still be at the port it was at ten minutes ago.
    """
    roots: list[ServedRoot] = []
    if production_dir.is_dir():
        roots.append(
            ServedRoot(
                key="production",
                kind="production",
                label="生产站",
                path=production_dir,
                port=0,
            )
        )
    wanted = (
        sorted(candidate_ids)
        if candidate_ids is not None
        else pending_publications(site_paths)
    )
    # A candidate whose bytes a registered preview already serves needs no port of its
    # own: the review card links into the preview, and one root per topic per tree is how
    # a hundred waiting candidates would exhaust the machine's ports.
    covered = _hashes_in_previews(preview_dirs)
    if covered:
        publications = load_publications(site_paths)
        wanted = [
            publication_id
            for publication_id in wanted
            if publication_id not in publications
            or publications[publication_id].review.page_hash not in covered
        ]
    for publication_id in sorted(
        path.name
        for path in site_paths.publications_dir.glob("PUB-*")
        if (path / "bundle").is_dir() and path.name in set(wanted)
    ):
        roots.append(
            ServedRoot(
                key=f"candidate:{publication_id}",
                kind="candidate",
                label=publication_id,
                path=site_paths.publication_dir(publication_id) / "bundle",
                port=0,
                publication_id=publication_id,
            )
        )
    for directory in sorted(Path(item).resolve() for item in preview_dirs):
        roots.append(
            ServedRoot(
                key=f"preview:{directory.name}",
                kind="preview",
                label=f"候选预览 {directory.name}",
                path=directory,
                port=0,
            )
        )
    # Ports are assigned when the roots are actually bound (``start_dev_shell``), because
    # a machine that already has something on one of them must cost that root a different
    # port, not cost the reviewer the whole shell.
    return roots


# --------------------------------------------------------------------------- dashboard state


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


#: Panel files are named by the generating script, not by a request, but the serving
#: route is request-shaped — so only a flat, extensionful name is ever resolved.
PANEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.html$")


def private_panels(site_paths: SitePaths) -> list[dict]:
    """The locally generated operator panels, if any: name and dashboard route."""
    directory = site_paths.private_dir / PANELS_DIR
    if not directory.is_dir():
        return []
    return [
        {"name": path.name, "url_path": f"/panels/{path.name}"}
        for path in sorted(directory.glob("*.html"))
        if path.is_file() and PANEL_NAME.fullmatch(path.name)
    ]


#: A panel item id, a decision label, and a machine reason code, as requests may carry
#: them.  The reason pattern mirrors what the intake service accepts, so a code recorded
#: here is a code the consequence can actually use.
_PANEL_ITEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_PANEL_CHOICE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_PANEL_REASON = re.compile(r"^[a-z0-9][a-z0-9_:-]{0,79}$")


def record_panel_decision(
    site_paths: SitePaths, *, panel: str, item_id: str, decision: str, reason: str = ""
) -> dict:
    """Append one browser-taken decision about one item of a private panel.

    Generic on purpose, like the panels themselves: the dashboard neither knows what a
    panel's items mean nor executes any consequence.  It only remembers what the human
    chose — append-only, last decision per item wins, under gitignored ``site/private/``
    — and a private script later reads the file and does the consequential work through
    its own CLI with its own credentials.  A batch of thirty triage calls is thirty
    clicks here and one command there, instead of thirty dictated sentences.
    """
    if not PANEL_NAME.fullmatch(panel):
        raise ArtifactError(f"invalid panel name: {panel!r}")
    if not (site_paths.private_dir / PANELS_DIR / panel).is_file():
        raise ArtifactError(f"no such panel: {panel}")
    if not _PANEL_ITEM.fullmatch(item_id):
        raise ArtifactError(f"invalid panel item id: {item_id!r}")
    if not _PANEL_CHOICE.fullmatch(decision):
        raise ArtifactError(f"invalid decision label: {decision!r}")
    if reason and not _PANEL_REASON.fullmatch(reason):
        raise ArtifactError(f"invalid machine reason code: {reason!r}")
    record = {
        "recorded_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "panel": panel,
        "item_id": item_id,
        "decision": decision,
        "reason": reason,
    }
    target = (
        site_paths.private_dir
        / PANELS_DIR
        / f"{panel[: -len('.html')]}.decisions.jsonl"
    )
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return {"path": str(target), "record": record}


def latest_panel_decisions(site_paths: SitePaths, panel: str) -> dict[str, dict]:
    """Last recorded decision per item of one panel — what a reloaded page must show.

    The panel is a pre-rendered static file, so a click can only change the DOM it was
    served into; on load the page asks this endpoint for the recorded state and hydrates
    itself.  Same genericity as recording: the dashboard returns what was chosen and
    interprets none of it.
    """
    if not PANEL_NAME.fullmatch(panel):
        raise ArtifactError(f"invalid panel name: {panel!r}")
    if not (site_paths.private_dir / PANELS_DIR / panel).is_file():
        raise ArtifactError(f"no such panel: {panel}")
    path = (
        site_paths.private_dir / PANELS_DIR / f"{panel[: -len('.html')]}.decisions.jsonl"
    )
    latest: dict[str, dict] = {}
    if not path.is_file():
        return latest
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except ValueError as exc:
            raise ArtifactError(f"corrupt decision line {number} in {path}") from exc
        if not isinstance(record, dict) or "item_id" not in record:
            raise ArtifactError(f"corrupt decision line {number} in {path}")
        latest[str(record["item_id"])] = {
            "decision": str(record.get("decision") or ""),
            "reason": str(record.get("reason") or ""),
            "recorded_at": str(record.get("recorded_at") or ""),
        }
    return latest


def existing_reviews(site_paths: SitePaths) -> dict[str, str]:
    """Page hash -> the approval record that already binds it.

    A reviewer who comes back to the dashboard must see what they already decided.  The
    first version of this shell showed a toast that vanished after six seconds and nothing
    else, which is indistinguishable from having done nothing.
    """
    found: dict[str, str] = {}
    directory = site_paths.private_dir / APPROVALS_DIR
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.json")):
        payload = _read_json(path)
        if isinstance(payload, dict) and payload.get("page_hash") and payload.get("locale"):
            found[str(payload["page_hash"])] = str(path)
    return found


def _scope_state(topics_root: Path) -> list[dict]:
    """Touchpoint one: which topics are signed, stale or unsigned."""
    rows = []
    if not topics_root.is_dir():
        return rows
    for manifest_path in sorted(topics_root.glob("*/topic_manifest.yaml")):
        topic_id = manifest_path.parent.name
        try:
            manifest = read_yaml(manifest_path, TopicManifest)
        except (ArtifactError, ValueError) as exc:
            rows.append({"topic_id": topic_id, "state": "invalid", "detail": str(exc)[:200]})
            continue
        problem = manifest.scope_approval_problem()
        approval = manifest.scope_approval
        rows.append(
            {
                "topic_id": topic_id,
                # The reviewer's own language first: this list is read by the person who
                # signs these topics, and which language that is, is the manifest's fact.
                "title": (
                    (manifest.title.get(manifest.review_locale) if manifest.review_locale else "")
                    or manifest.title.get("en")
                    or topic_id
                ),
                "review_locale": manifest.review_locale or "",
                "state": "signed" if problem is None else "unsigned",
                "detail": problem or "",
                "approved_by": approval.approved_by if approval else "",
                "decided_by": approval.decided_by.value if approval else "",
                "scope_hash": manifest.scope_hash(),
                "candidates": (manifest_path.parent / "scope" / "question_candidates.yaml").is_file(),
                "seeds": len(manifest.question_seeds),
            }
        )
    return rows


def collect_state(
    *,
    repo_root: Path,
    topics_root: Path,
    site_paths: SitePaths,
    production_dir: Path,
    roots: list[ServedRoot],
) -> dict:
    """Everything the dashboard shows, derived — never authored."""
    publications = load_publications(site_paths)
    events = load_publication_events(site_paths)
    selector = derive_publish_selector(
        publications,
        events,
        publication_hashes={
            publication_id: file_digest(site_paths.publication_record(publication_id))
            for publication_id in publications
        },
    )
    live_by_topic = dict(selector.publications)
    live_ids = set(live_by_topic.values())
    #: A record that any event has touched is history, not a decision waiting to be made.
    #: Offering "activate" on a superseded M1 record would be an invitation to republish
    #: bytes the user deliberately replaced.
    last_event: dict[str, str] = {}
    for event in events:
        last_event[event.publication_id] = event.event_type.value
        if event.replacement_publication_id:
            last_event[event.replacement_publication_id] = event.event_type.value

    by_key = {root.key: root for root in roots}
    release = _read_json(site_paths.production_dir / "release.json") or {}

    candidates = []
    for publication_id, record in sorted(publications.items()):
        root = by_key.get(f"candidate:{publication_id}")
        pages = review_pages(root) if root else []
        if publication_id in live_ids:
            state = "live"
        elif publication_id in last_event:
            state = {"supersede": "superseded", "withdraw": "withdrawn"}.get(
                last_event[publication_id], last_event[publication_id]
            )
        else:
            state = "pending"
        candidates.append(
            {
                "publication_id": publication_id,
                "state": state,
                "topic_id": record.topic_id,
                "page_run_id": record.page_run_id,
                "producer": record.provenance.skill_version,
                "theme_token": record.theme_token or "",
                "prepared_at": record.prepared_at.isoformat(),
                "live": publication_id in live_ids,
                "reviewed_locale": record.review.locale,
                "reviewed_hash": record.review.page_hash,
                "locales": [
                    {"locale": bundle.locale, "page_hash": bundle.page_hash}
                    for bundle in record.locales
                ],
                "pages": [page.__dict__ | {"url": page.url} for page in pages],
                "supersedes": live_by_topic.get(record.topic_id),
            }
        )

    reviews = existing_reviews(site_paths)
    previews = []
    for root in roots:
        if root.kind != "preview":
            continue
        pinned = read_review_manifest(root.path)
        pages = []
        for page in review_pages(root):
            entry = pinned.get(page.topic_id) or {}
            pages.append(
                page.__dict__
                | {
                    "url": page.url,
                    "page_run_id": entry.get("page_run_id", ""),
                    "theme_token": entry.get("theme_token", ""),
                    "categories": entry.get("categories") or [],
                    "locales": entry.get("locales") or [],
                    "review_locale": entry.get("review_locale", ""),
                    "approved_path": reviews.get(page.page_hash, ""),
                }
            )
        previews.append(
            {
                "key": root.key,
                "label": root.label,
                "path": str(root.path),
                "origin": root.origin,
                "pages": pages,
            }
        )

    production_root = by_key.get("production")
    production_pages = review_pages(production_root) if production_root else []
    scope = _scope_state(topics_root)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo_root": str(repo_root),
        "release": release,
        "production": {
            "origin": production_root.origin if production_root else "",
            "path": str(production_dir),
            # The count, not the list.  A site with a thousand topics must still render a
            # dashboard, and "which topics are live" is a question the production site
            # itself answers better than a copy of its index would.
            "topic_count": len({page.topic_id for page in production_pages}),
            "page_count": len(production_pages),
            "pages": [page.__dict__ | {"url": page.url} for page in production_pages],
        },
        "candidates": candidates,
        "previews": previews,
        "releases": _releases(
            site_paths,
            previews=previews,
            candidates=candidates,
            live_by_topic=live_by_topic,
            publications=publications,
            titles={row["topic_id"]: row.get("title") or row["topic_id"] for row in scope},
            reviewer_locales={
                row["topic_id"]: row.get("review_locale") or "" for row in scope
            },
        ),
        "scope": scope,
        "panels": private_panels(site_paths),
        "chrome": chrome.chrome_release(load_theme_registry(), bytes_digest),
    }


def _reviewer_locale_problem(
    topic_id: str, reviewer_locale: str, page_locales: list[str]
) -> str:
    """Why this row cannot take an approval, or ``""`` when it can.

    Two different failures, kept apart because they are fixed in different places: a
    scope that never named the reviewer's language (fix the manifest) and a candidate
    rendered without it (fix the render).  Neither may be papered over with a default —
    an approval names the one rendering a human read, and a guess would name another.
    """
    if not reviewer_locale:
        return "no_review_locale"
    if reviewer_locale not in page_locales:
        return "review_locale_absent"
    return ""


def _releases(
    site_paths: SitePaths,
    *,
    previews: list[dict],
    candidates: list[dict],
    live_by_topic: dict,
    publications: dict,
    titles: dict,
    reviewer_locales: Mapping[str, str],
) -> list[dict]:
    """One row per topic waiting to go live — the whole decision in one place.

    The shell used to show this as three sections the reviewer had to join by hand: a
    preview to read, a prepared candidate to authorize, and a production list to compare
    against.  They are one question ("does this replace what is live?"), so they are now
    one card.

    ``reviewer_locales`` maps topic id to the language that topic's touchpoint two is
    read and signed in — ``topic_manifest.review_locale``, never a constant.  It is the
    locale whose page hash the approval and the replacement authorization are keyed by,
    so a topic whose manifest never named one has no reviewable rendering here: the row
    still lists its bytes, but the card says what is missing instead of offering a
    confirmation keyed to a guess.

    That map is built by scanning the repo's ``topics/``, which holds every topic this
    checkout produced and no topic it merely *reviews*: an imported submission renders
    from its own namespace and has no row there.  So the preview's own record wins where
    it has one — same fact, read from where this rendering actually came from.
    """
    prepared_by_hash = {
        candidate["reviewed_hash"]: candidate
        for candidate in candidates
        if candidate["state"] == "pending"
    }
    rows = []
    for preview in previews:
        by_topic: dict[str, list[dict]] = {}
        for page in preview["pages"]:
            by_topic.setdefault(page["topic_id"], []).append(page)
        for topic_id, pages in sorted(by_topic.items()):
            reviewer_locale = next(
                (str(page.get("review_locale")) for page in pages if page.get("review_locale")),
                "",
            ) or reviewer_locales.get(topic_id, "")
            live_id = live_by_topic.get(topic_id, "")
            live_hashes = {}
            if live_id and live_id in publications:
                live_hashes = {
                    bundle.locale: bundle.page_hash
                    for bundle in publications[live_id].locales
                }
            locales = []
            reviewed_hash = ""
            for page in sorted(pages, key=lambda item: item["locale"]):
                if reviewer_locale and page["locale"] == reviewer_locale:
                    reviewed_hash = page["page_hash"]
                locales.append(
                    page
                    | {
                        "live_hash": live_hashes.get(page["locale"], ""),
                        "changed": live_hashes.get(page["locale"], "") != page["page_hash"],
                    }
                )
            # A preview whose bytes are already the live ones is history, not a decision:
            # the shell keeps showing the review root after the release, and offering
            # "approve and ship" for what is already shipped invites a pointless supersede.
            already_live = bool(live_hashes) and all(
                not item["changed"] for item in locales
            )
            prepared = prepared_by_hash.get(reviewed_hash) or {}
            publication_id = prepared.get("publication_id", "")
            authorization = ""
            if publication_id:
                path = (
                    site_paths.private_dir / APPROVALS_DIR / f"activate-{publication_id}.json"
                )
                authorization = str(path) if path.is_file() else ""
            if not authorization and reviewed_hash:
                # Only a still-pending intent counts: one already spent on an earlier
                # publication authorizes nothing here.
                path = pending_intent_path(
                    site_paths, topic_id=topic_id, page_hash=reviewed_hash
                )
                authorization = str(path) if path is not None else ""
            rows.append(
                {
                    "topic_id": topic_id,
                    "title": titles.get(topic_id, topic_id),
                    "preview_key": preview["key"],
                    "page_run_id": (pages[0].get("page_run_id") if pages else "") or "",
                    "theme_token": (pages[0].get("theme_token") if pages else "") or "",
                    "categories": (pages[0].get("categories") if pages else []) or [],
                    "reviewer_locale": reviewer_locale,
                    "reviewer_locale_problem": _reviewer_locale_problem(
                        topic_id, reviewer_locale, [str(item["locale"]) for item in locales]
                    ),
                    "reviewed_hash": reviewed_hash,
                    "locales": locales,
                    "live_publication_id": live_id,
                    "publication_id": publication_id,
                    "reviewed": all(bool(item.get("approved_path")) for item in locales),
                    "authorization": authorization,
                    "live": already_live,
                    "operation": "supersede" if live_id else "publish",
                }
            )
    return rows


# --------------------------------------------------------------------------- decisions taken


def _approval_id(topic_id: str, seed: str) -> str:
    import hashlib

    return f"APR-{topic_id}-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:8]}"


def _private_dir(site_paths: SitePaths, name: str) -> Path:
    target = site_paths.private_dir / name
    target.mkdir(parents=True, exist_ok=True)
    return target


def _write_record(path: Path, record) -> Path:
    if path.exists():
        raise ArtifactError(f"refusing to overwrite an existing decision record: {path}")
    path.write_text(record.model_dump_json() + "\n", encoding="utf-8")
    return path


def record_page_approval(
    site_paths: SitePaths,
    *,
    topic_id: str,
    locale: str,
    page_hash: str,
    reviewer_id: str,
    note: str,
    note_lang: str,
    reviewed_locales: Optional[Iterable[str]] = None,
    decided_at: Optional[datetime] = None,
) -> Path:
    """Touchpoint two, taken in the browser against the bytes the browser was served.

    The page hash is computed by the server from the exact file it served, so the user
    approves what they read instead of copying a digest between two windows.

    ``note_lang`` is the language the reviewer wrote that note in — their own, which is
    the topic's ``review_locale`` and not a constant this module could know.  A record
    that mislabels it makes the reviewer's own words unreadable to the next operator.
    """
    when = (decided_at or datetime.now(timezone.utc)).replace(microsecond=0)
    review = PublicationReview(
        approval_id=_approval_id(topic_id, f"review|{page_hash}|{when.isoformat()}"),
        reviewer_id=reviewer_id,
        decided_at=when,
        note=LangText(text=note, lang=normalize_lang(note_lang)) if note else None,
        locale=locale,
        page_hash=page_hash,
        # These bytes name the other languages they exist in, so the set they were
        # rendered under is part of what was approved.  Recorded here, a later build can
        # re-prove them while shipping a wider set.
        reviewed_locales=list(reviewed_locales) if reviewed_locales else None,
    )
    target = _private_dir(site_paths, APPROVALS_DIR) / f"review-{topic_id}-{page_hash[7:15]}.json"
    return _write_record(target, review)


#: A supersede authorization the user signed *before* the candidate existed.
#: Keyed by the reviewed page hash rather than a publication id, because touchpoint two
#: happens on preview bytes and ``prepare`` is what mints the id.  ``prepare`` promotes a
#: matching intent into the ordinary ``activate-<publication_id>.json`` approval.
INTENT_PREFIX = "activate-intent"


def intent_path(site_paths: SitePaths, topic_id: str, page_hash: str) -> Path:
    return (
        site_paths.private_dir
        / APPROVALS_DIR
        / f"{INTENT_PREFIX}-{topic_id}-{page_hash[7:15]}.json"
    )


def intent_consumed_path(site_paths: SitePaths, topic_id: str, page_hash: str) -> Path:
    """Sidecar written when an intent is promoted; the intent itself is never edited.

    An intent is keyed by page hash, and the same approved bytes can legitimately be
    prepared more than once (a locale-set backfill re-prepares them wholesale).  Without
    this marker the second ``prepare`` would promote the same signature again and hang an
    authorization on the new publication that was actually spent on the previous one.
    """
    return intent_path(site_paths, topic_id, page_hash).with_suffix(".consumed.json")


def consumed_intent(
    site_paths: SitePaths, *, topic_id: str, page_hash: str
) -> Optional[dict]:
    """The consumption record for this hash's intent, or None if it is still pending."""
    marker = intent_consumed_path(site_paths, topic_id, page_hash)
    if not marker.is_file():
        return None
    return json.loads(marker.read_text(encoding="utf-8"))


def pending_intent_path(
    site_paths: SitePaths, *, topic_id: str, page_hash: str
) -> Optional[Path]:
    """The intent for this hash, only while no operation has consumed it yet."""
    source = intent_path(site_paths, topic_id, page_hash)
    if not source.is_file():
        return None
    if intent_consumed_path(site_paths, topic_id, page_hash).is_file():
        return None
    return source


#: Filename convention for the locale-plan record, keyed by the reviewed page hash
#: the same way ``review-<topic>-<hash8>.json`` and ``topic-categories-<topic>-<hash8>.json``
#: already are — one card, one confirmation, three records under the same key.
def locale_plan_path(site_paths: SitePaths, topic_id: str, reviewed_hash: str) -> Path:
    return (
        site_paths.private_dir
        / APPROVALS_DIR
        / f"locale-plan-{topic_id}-{reviewed_hash[7:15]}.json"
    )


def locale_plan_consumed_path(site_paths: SitePaths, topic_id: str, reviewed_hash: str) -> Path:
    """Sidecar a later expansion run writes once it has acted on the plan.

    Mirrors ``intent_consumed_path``: the plan file itself is never rewritten, and a
    consumer that finds this marker already present must not localize the same
    ``target_locales`` a second time on the same authorization — a fresh plan (a later
    approval, or ``backfill-locales``' own ``--reason``) is a new decision, not this one
    replayed.
    """
    return locale_plan_path(site_paths, topic_id, reviewed_hash).with_suffix(".consumed.json")


def pending_locale_plan(
    site_paths: SitePaths, *, topic_id: str, reviewed_hash: str
) -> Optional[LocalePlan]:
    """The still-unconsumed locale-plan for this reviewed candidate, if any.

    Read by a render-localize expansion run (``skills/render-localize/SKILL.md``) to
    learn which locales beyond the reviewer's own the user already authorized,
    without asking again.
    """
    source = locale_plan_path(site_paths, topic_id, reviewed_hash)
    if not source.is_file():
        return None
    if locale_plan_consumed_path(site_paths, topic_id, reviewed_hash).is_file():
        return None
    return LocalePlan.model_validate_json(source.read_text(encoding="utf-8"))


def consume_locale_plan(
    site_paths: SitePaths, *, topic_id: str, reviewed_hash: str, consumer: str
) -> Optional[Path]:
    """Mark a locale-plan spent once its expansion has been prepared and activated.

    ``consumer`` is a free-text pointer back to what used it (a publication id is the
    normal case) — recorded for audit, not re-validated later.  Idempotent: consuming an
    already-consumed plan for the same hash is a no-op so a resumed expansion run does
    not fail on its own marker.
    """
    marker = locale_plan_consumed_path(site_paths, topic_id, reviewed_hash)
    if marker.is_file():
        return marker
    if not locale_plan_path(site_paths, topic_id, reviewed_hash).is_file():
        return None
    when = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "reviewed_hash": reviewed_hash,
        "consumed_by": consumer,
        "consumed_at": when.isoformat().replace("+00:00", "Z"),
    }
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return marker


def record_locale_plan(
    site_paths: SitePaths,
    *,
    topic_id: str,
    reviewed_hash: str,
    included_locales: Iterable[str],
    target_locales: Iterable[str],
    reviewer_id: str,
    reason: str,
    reason_lang: str,
    decided_at: Optional[datetime] = None,
) -> Path:
    """Touchpoint two's language-expansion authorization, written beside the page reviews.

    Always written alongside a release approval, even when the user added nothing:
    "ship only what is already here" is itself the decision, and a later agent should
    not have to infer silence as authorization for anything.  Idempotent on the same
    reviewed hash — a retried approval click must not raise on the second write.
    """
    when = (decided_at or datetime.now(timezone.utc)).replace(microsecond=0)
    target = locale_plan_path(site_paths, topic_id, reviewed_hash)
    if target.exists():
        return target
    plan = LocalePlan(
        approval_id=_approval_id(topic_id, f"locale-plan|{reviewed_hash}|{when.isoformat()}"),
        topic_id=topic_id,
        reviewer_id=reviewer_id,
        decided_at=when,
        reviewed_hash=reviewed_hash,
        included_locales=sorted(set(included_locales)),
        target_locales=sorted(set(target_locales)),
        reason=LangText(text=reason, lang=normalize_lang(reason_lang)),
    )
    _private_dir(site_paths, APPROVALS_DIR)
    target.write_text(plan.model_dump_json() + "\n", encoding="utf-8")
    return target


def record_release_approval(
    site_paths: SitePaths,
    *,
    topic_id: str,
    pages: list[dict],
    reviewer_locale: str,
    reason: str,
    reviewer_id: str,
    publication_id: str = "",
    categories: Iterable[str] = (),
    add_locales: Iterable[str] = (),
    decided_at: Optional[datetime] = None,
) -> dict:
    """Touchpoint two and the replacement authorization, taken in one decision.

    Splitting them was ceremony, not a second judgement: a user who has read the exact
    bytes and approved them has no further information with which to decide whether those
    bytes may replace the ones they already superseded on screen.  What *does* still
    protect the bytes is mechanical and stays mechanical — ``verify-candidate`` re-renders
    and compares, and a mismatch is an automatic refusal that no click can wave past.

    So one confirmation writes three records: a ``PublicationReview`` per locale bound to
    the exact served bytes, one ``HumanApproval`` authorizing the lifecycle move, and one
    ``LocalePlan`` naming which halo locales — the candidate's own plus any the
    user checked on the card — this decision authorizes reaching after the fact.  The
    lifecycle authorization names the prepared candidate when there is one; before
    ``prepare`` has run there is no id yet, so it is filed as an *intent* keyed by the
    reviewed page hash and promoted later by ``prepare`` itself.
    """
    # Refuse before writing anything: half a decision on disk is worse than none.
    if not reason.strip():
        raise ArtifactError("a release decision needs a reason: it outlives the click")
    if not reviewer_locale:
        raise ArtifactError(
            f"{topic_id}: topic_manifest.review_locale is unset, so there is no rendering "
            "this approval could name; set it in the scope before taking touchpoint two"
        )
    reviewer_locale = normalize_lang(reviewer_locale)
    reviewed_hash = next(
        (
            str(page["page_hash"])
            for page in pages
            if str(page["locale"]) == reviewer_locale
        ),
        "",
    )
    if not reviewed_hash:
        raise ArtifactError(
            f"no {reviewer_locale} page among the reviewed locales for {topic_id}"
        )
    included_locales = sorted({str(page["locale"]) for page in pages})
    requested_locales = sorted(
        {normalize_lang(item) for item in add_locales if str(item).strip()}
    )
    unknown = sorted(set(requested_locales) - set(HALO_LOCALE_CODES))
    if unknown:
        raise ArtifactError(
            f"locale-plan requested locales outside the halo's nine: {unknown}"
        )
    target_locales = sorted(set(included_locales) | set(requested_locales))

    when = (decided_at or datetime.now(timezone.utc)).replace(microsecond=0)
    written: list[str] = []
    for page in pages:
        locale = str(page["locale"])
        page_hash = str(page["page_hash"])
        target = (
            _private_dir(site_paths, APPROVALS_DIR)
            / f"review-{topic_id}-{page_hash[7:15]}.json"
        )
        if target.exists():
            written.append(str(target))
            continue
        written.append(
            str(
                record_page_approval(
                    site_paths,
                    topic_id=topic_id,
                    locale=locale,
                    page_hash=page_hash,
                    reviewed_locales=[str(item["locale"]) for item in pages],
                    reviewer_id=reviewer_id,
                    note=reason,
                    note_lang=reviewer_locale,
                    decided_at=when,
                )
            )
        )
    # The card showed the proposed categories beside the page the reviewer just read,
    # so the same decision settles them.  Asking separately afterwards would be a second
    # question about something they had already seen and not objected to.
    proposed = [c for c in categories if c]
    if proposed:
        target = (
            _private_dir(site_paths, APPROVALS_DIR)
            / f"topic-categories-{topic_id}-{reviewed_hash[7:15]}.json"
        )
        if not target.exists():
            _write_record(
                target,
                TopicCategoryApproval(
                    approval_id=f"taxonomy-topic-{topic_id}-{when.date().isoformat()}",
                    topic_id=topic_id,
                    reviewer_id=reviewer_id,
                    decision="approved",
                    decided_at=when,
                    category_ids=list(proposed),
                    note=LangText(text=reason, lang=reviewer_locale),
                ),
            )
        written.append(str(target))
    approval = HumanApproval(
        approval_id=_approval_id(topic_id, f"release|{reviewed_hash}|{when.isoformat()}"),
        reviewer_id=reviewer_id,
        decided_at=when,
        note=LangText(text=reason, lang=reviewer_locale),
    )
    _private_dir(site_paths, APPROVALS_DIR)
    if publication_id:
        target = site_paths.private_dir / APPROVALS_DIR / f"activate-{publication_id}.json"
    else:
        target = intent_path(site_paths, topic_id, reviewed_hash)
        spent = consumed_intent(site_paths, topic_id=topic_id, page_hash=reviewed_hash)
        if spent is not None:
            # The intent slot for this hash is single-use and already spent.
            # Reusing it would hand the new operation the old signature; take this
            # decision after ``prepare`` instead, so it binds the new publication id.
            raise ArtifactError(
                f"the authorization for {reviewed_hash[:15]} was already consumed by "
                f"{spent.get('publication_id', '?')}; prepare the candidate first and "
                "record the decision against its publication id"
            )
    if not target.exists():
        _write_record(target, approval)
    locale_plan = record_locale_plan(
        site_paths,
        topic_id=topic_id,
        reviewed_hash=reviewed_hash,
        included_locales=included_locales,
        target_locales=target_locales,
        reviewer_id=reviewer_id,
        reason=reason,
        reason_lang=reviewer_locale,
        decided_at=when,
    )
    return {
        "reviews": written,
        "authorization": str(target),
        "publication_id": publication_id,
        "page_hash": reviewed_hash,
        "locale_plan": str(locale_plan),
        "target_locales": target_locales,
    }


def promote_intent(
    site_paths: SitePaths, *, topic_id: str, publication_id: str, page_hash: str
) -> Optional[Path]:
    """Turn the user's pre-``prepare`` authorization into this candidate's approval.

    Mechanical on purpose.  The promotion is allowed only because the hash in the intent's
    filename is the hash the candidate pins as reviewed: the human signed these bytes, and
    ``prepare`` merely learned what id they ended up carrying.

    Single-use.  The user authorized one lifecycle move, not every future
    operation on the same bytes, so promotion writes a consumption sidecar first and a
    consumed intent promotes nothing: a later ``prepare`` of the same approved bytes needs
    its own authorization.  The marker is written before the copy so a crash between the
    two fails closed (authorization missing, never duplicated); re-running the same
    candidate's ``prepare`` completes the interrupted copy because the marker names it.
    """
    source = intent_path(site_paths, topic_id, page_hash)
    if not source.is_file():
        return None
    target = site_paths.private_dir / APPROVALS_DIR / f"activate-{publication_id}.json"
    if target.exists():
        return target
    marker = intent_consumed_path(site_paths, topic_id, page_hash)
    if marker.is_file():
        spent = json.loads(marker.read_text(encoding="utf-8"))
        if spent.get("publication_id") != publication_id:
            return None
    else:
        payload = {
            "intent": source.name,
            "page_hash": page_hash,
            "publication_id": publication_id,
            "consumed_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        marker.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def record_note(
    site_paths: SitePaths, *, subject: str, text: str, reviewer_id: str
) -> Path:
    """A comment or a rejection reason.  Not an approval, and never mistaken for one."""
    if not text.strip():
        raise ArtifactError("a review note needs text")
    when = datetime.now(timezone.utc).replace(microsecond=0)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", subject).strip("-") or "note"
    target = (
        _private_dir(site_paths, NOTES_DIR)
        / f"{when.strftime('%Y%m%dT%H%M%SZ')}-{safe[:60]}.json"
    )
    payload = {
        "subject": subject,
        "reviewer_id": reviewer_id,
        "recorded_at": when.isoformat().replace("+00:00", "Z"),
        "decision": "note",
        "text": text,
        "lang": "zh-CN",
    }
    if target.exists():
        raise ArtifactError(f"refusing to overwrite an existing note: {target}")
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def record_theme_proposal(site_paths: SitePaths, *, payload: dict, author: str) -> Path:
    """Dev-3 export: a proposed change to the token registry, not CSS.

    The panel edits CSS variables live, but what leaves the browser is a proposal against
    ``theme_tokens.v1.json`` — it still has to pass the contrast gate, the browser gate
    and a site-operator commit before any reader sees it.
    """
    tokens = payload.get("themes")
    if not isinstance(tokens, list) or not tokens:
        raise ArtifactError("a theme proposal must carry at least one theme entry")
    when = datetime.now(timezone.utc).replace(microsecond=0)
    target = (
        _private_dir(site_paths, PROPOSALS_DIR)
        / f"{when.strftime('%Y%m%dT%H%M%SZ')}-theme-proposal.json"
    )
    document = {
        "proposed_at": when.isoformat().replace("+00:00", "Z"),
        "author": author,
        "target": "packages/publish/newsab_publish/data/theme_tokens.v1.json",
        "gate": ["contrast", "web-gate", "site-operator-commit"],
        "proposal": payload,
    }
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def sign_scope(
    repo_root: Path,
    topics_root: Path,
    *,
    topic_id: str,
    checkmarks: list[dict],
    approved_by: str,
    note: str,
) -> dict:
    """Touchpoint one, taken in the browser and written by the scope skill's own tool.

    The checkmark sheet is the user's artifact and is written here; the manifest
    signature is not, because the rules around it (stand-ins may not create a required
    seed, a review's decider must match the scope's) live in ``scope_tool.py`` and must
    have exactly one implementation.
    """
    paths = TopicPaths.for_topic(topics_root, topic_id)
    candidates_path = paths.root / "scope" / "question_candidates.yaml"
    steps: list[dict] = []
    if checkmarks:
        if not candidates_path.is_file():
            raise ArtifactError(f"no question candidate sheet to review: {candidates_path}")
        import yaml

        raw = load_yaml_text(candidates_path.read_text(encoding="utf-8")) or {}
        wanted = {item["candidate_id"]: item for item in checkmarks}
        for candidate in raw.get("candidates", []):
            mark = wanted.get(candidate.get("candidate_id"))
            if mark is None:
                continue
            candidate["review"] = {
                "approved": bool(mark.get("approved")),
                "required": bool(mark.get("approved")) and bool(mark.get("required")),
            }
        candidates_path.write_text(
            yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        steps.append(_scope_tool(repo_root, [
            "apply-question-review", str(topics_root), topic_id, "--decided-by", "human",
        ]))
    command = ["approve", str(topics_root), topic_id, "--approved-by", approved_by, "--decided-by", "human"]
    if note:
        command += ["--note", note]
    steps.append(_scope_tool(repo_root, command))
    return {"ok": all(step["returncode"] == 0 for step in steps), "steps": steps}


def _scope_tool(repo_root: Path, args: list[str]) -> dict:
    script = repo_root / "skills" / "scope" / "scripts" / "scope_tool.py"
    if not script.is_file():
        raise ArtifactError(f"scope tool is missing: {script}")
    completed = subprocess.run(  # noqa: S603 - fixed script, argv never shell-joined
        [sys.executable, str(script), *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    return {
        "command": " ".join(["scope_tool.py", *args]),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


# --------------------------------------------------------------------------- dashboard page


def resolve_ui_locale(raw: Optional[str]) -> str:
    """The dashboard's own UI language: any of the halo's nine, else the default.

    Independent of any topic's ``review_locale`` (approval semantics, read from that
    topic's manifest and never from this button) — this is
    purely which language the *tool* speaks, chosen by the language button and carried on
    the ``?locale=`` query parameter so a plain server-rendered page can switch it without
    any client-side templating.  An unrecognized or missing value falls back rather than
    failing: a stale bookmark or a stray query string must never break the dashboard.
    """
    if not raw:
        return DEFAULT_DASHBOARD_LOCALE
    try:
        canonical = normalize_lang(raw)
    except ValueError:
        return DEFAULT_DASHBOARD_LOCALE
    try:
        dashboard_strings(canonical)
    except ValueError:
        return DEFAULT_DASHBOARD_LOCALE
    return canonical


DASHBOARD_CSS = """
:root{--paper:#FBFAF7;--panel:#fff;--ink:#14171A;--ink2:#41484E;--muted:#767D84;
  --rule:#E0DCD2;--accent:#8C2F1E;--ok:#2F6B3B;--warn:#9A7211;
  --sans:"IBM Plex Sans","Noto Sans SC",system-ui,-apple-system,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,monospace}
/* Three theme states, same order and same override pattern as the reader page's
   render/theme.py: bare :root is the light palette; the media query, guarded by
   :not([data-theme="light"]), is the system default; the explicit [data-theme="dark"]
   selector wins in both directions so the button can force either theme regardless of
   what the browser prefers. */
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){--paper:#171B20;--panel:#1E242A;--ink:#E7E3DB;
    --ink2:#C4BFB6;--muted:#98A0A8;--rule:#363E46;--accent:#E08265;--ok:#6FAF7C;--warn:#D2A94A}
}
:root[data-theme="dark"]{--paper:#171B20;--panel:#1E242A;--ink:#E7E3DB;
  --ink2:#C4BFB6;--muted:#98A0A8;--rule:#363E46;--accent:#E08265;--ok:#6FAF7C;--warn:#D2A94A}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);font:15px/1.6 var(--sans);
  padding:clamp(1rem,3vw,2.5rem);max-width:74rem;margin:0 auto}
h1{font-size:1.6rem;letter-spacing:-.01em}
/* The theme and language buttons: fixed top-right, same corner on every dashboard page,
   never inside a card so they never scroll out of reach. */
.chrome-controls{position:fixed;top:1rem;right:1rem;z-index:60;display:flex;gap:.5rem}
[dir="rtl"] .chrome-controls{right:auto;left:1rem}
.chrome-controls .fab{display:flex;align-items:center;justify-content:center;
  width:2.4rem;height:2.4rem;min-height:0;padding:0;border-radius:50%;font-size:1.05rem;
  line-height:1;box-shadow:0 3px 12px rgba(0,0,0,.14)}
.lang-wrap{position:relative}
.lang-menu{position:absolute;top:2.7rem;right:0;z-index:61;min-width:9rem;
  background:var(--panel);border:1px solid var(--rule);border-radius:4px;
  box-shadow:0 8px 24px rgba(0,0,0,.2);padding:.3rem;display:flex;flex-direction:column}
[dir="rtl"] .lang-menu{right:auto;left:0}
.lang-menu[hidden]{display:none}
.lang-menu button{border:none;background:none;text-align:left;padding:.4rem .6rem;
  min-height:0;border-radius:2px}
[dir="rtl"] .lang-menu button{text-align:right}
.lang-menu button:hover,.lang-menu button.on{background:var(--paper);color:var(--accent)}
.lang-menu button.on{font-weight:600}
h2{font-size:1.15rem;margin:2.4rem 0 .8rem;padding-bottom:.4rem;border-bottom:1px solid var(--rule)}
h3{font-size:.95rem;margin:0 0 .3rem}
a{color:var(--accent)}
.lede{color:var(--muted);font-size:.85rem;margin-top:.35rem}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:4px;
  padding:.9rem 1rem;margin:.6rem 0}
.row{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin:.35rem 0}
.hash{font:400 11.5px/1.5 var(--mono);color:var(--muted);overflow-wrap:anywhere}
.tag{font:500 11px/1.5 var(--sans);border:1px solid var(--rule);border-radius:2px;
  padding:.05rem .4rem;color:var(--ink2)}
.tag.live{border-color:var(--ok);color:var(--ok)}
.tag.wait{border-color:var(--warn);color:var(--warn)}
button{font:500 12.5px/1 var(--sans);padding:.5rem .8rem;border:1px solid var(--rule);
  border-radius:2px;background:var(--panel);color:var(--ink2);cursor:pointer;min-height:2.2rem}
button:hover{border-color:var(--accent);color:var(--accent)}
button.go{border-color:var(--accent);color:var(--accent)}
input[type=text],textarea{font:400 12.5px/1.5 var(--sans);padding:.45rem .55rem;
  border:1px solid var(--rule);border-radius:2px;background:var(--paper);color:var(--ink);
  width:100%;max-width:38rem}
textarea{min-height:3.4rem}
pre{font:400 11.5px/1.6 var(--mono);background:var(--paper);border:1px solid var(--rule);
  border-radius:2px;padding:.6rem .7rem;overflow-x:auto;white-space:pre;margin:.4rem 0}
ul{margin:.3rem 0 .3rem 1.1rem}li{margin:.2rem 0}
.muted{color:var(--muted);font-size:.85rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(20rem,1fr));gap:.6rem}
#toast{position:fixed;left:50%;bottom:1.2rem;transform:translateX(-50%);z-index:9;
  background:var(--ink);color:var(--paper);padding:.6rem .9rem;border-radius:3px;
  font-size:12.5px;max-width:90vw}
#toast:empty{display:none}
label.check{display:flex;gap:.4rem;align-items:flex-start;margin:.25rem 0;font-size:13px}
.release h3{font-size:1rem;margin-bottom:.15rem}
.release .row{margin:.5rem 0 .1rem}
.batch{border-color:var(--accent)}
details summary{cursor:pointer;font-size:.9rem;color:var(--ink2);padding:.3rem 0}
.confirm{border-left:3px solid var(--warn);padding:.5rem .8rem;margin:.5rem 0 0;
  background:var(--paper)}
.confirm p{font-size:12.5px;line-height:1.65;color:var(--ink2)}
.done{border-left:3px solid var(--ok);padding:.5rem .8rem;margin:.5rem 0 0;
  background:var(--paper);font-size:12.5px}
.done strong{color:var(--ok)}
.done code{font:400 11px/1.5 var(--mono);overflow-wrap:anywhere}
.locale-plan{margin:.5rem 0}
.locale-choices{display:flex;flex-wrap:wrap;gap:.4rem .5rem;margin:.3rem 0}
.locale-choice{display:inline-flex;gap:.3rem;align-items:center;font-size:12px;
  border:1px solid var(--rule);border-radius:2px;padding:.15rem .45rem;cursor:pointer}
.locale-choice:hover{border-color:var(--accent)}
"""


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _page_rows(pages: list[dict], *, with_topic: bool = False) -> str:
    """One line per servable page: where to read it, and the bytes it is."""
    out = []
    for page in sorted(pages, key=lambda item: (item["topic_id"], item["locale"])):
        name = f'{page["topic_id"]} · {page["locale"]}' if with_topic else page["locale"]
        out.append(
            f'<div class="row"><a href="{_e(page["url"])}" target="_blank" rel="noreferrer">'
            f'{_e(name)} ↗</a>'
            f'<span class="hash">{_e(page["page_hash"])}</span></div>'
        )
    return "".join(out)


def _locale_rows(row: dict, locale: str = DEFAULT_DASHBOARD_LOCALE) -> str:
    """Each locale: the link to read it, and how its bytes differ from what is live."""
    s = dashboard_strings(locale)
    out = []
    for page in row["locales"]:
        if not page["live_hash"]:
            verdict = f'<span class="tag wait">{s["new_page"]}</span>'
        elif page["changed"]:
            verdict = f'<span class="tag wait">{s["diff_from_live"]}</span>'
        else:
            verdict = f'<span class="tag">{s["same_as_live"]}</span>'
        out.append(
            f'<div class="row"><a href="{_e(page["url"])}" target="_blank" rel="noreferrer">'
            f'{s["read_locale_link"].format(locale=_e(page["locale"]))}</a>{verdict}'
            + (
                f'<span class="tag live">{s["bytes_approved"]}</span>'
                if page.get("approved_path")
                else ""
            )
            + "</div>"
            f'<div class="hash">{s["candidate_hash_label"].format(hash=_e(page["page_hash"]))}</div>'
            + (
                f'<div class="hash">{s["live_hash_label"].format(hash=_e(page["live_hash"]))}</div>'
                if page["live_hash"]
                else ""
            )
        )
    return "".join(out)


def _locale_plan_html(row: dict, s: Mapping[str, str]) -> str:
    """The language-expansion picker: read-only tags for what is already reviewed,
    checkboxes for anything else in the halo's nine the user wants localized after.

    Lives inside the same ``.confirm`` box as the reason field, so checking a language
    is part of the one decision the confirm button takes — never a separate control that
    could be missed or fired on its own.
    """
    included = {str(item["locale"]) for item in row["locales"]}
    chips = []
    for entry in HALO_LOCALES:
        if entry.locale in included:
            chips.append(
                f'<span class="tag live" lang="{_e(entry.display_lang)}">'
                f'{_e(entry.endonym)} · {s["locale_included_tag"]}</span>'
            )
        else:
            chips.append(
                f'<label class="locale-choice"><input type="checkbox" '
                f'data-locale-choice value="{_e(entry.locale)}"> '
                f'<span lang="{_e(entry.display_lang)}">{_e(entry.endonym)}</span></label>'
            )
    return (
        '<div class="locale-plan">'
        f'<p class="muted">{s["locale_plan_heading"]}</p>'
        f'<div class="locale-choices">{"".join(chips)}</div>'
        f'<p class="muted">{s["locale_plan_hint"]}</p>'
        "</div>"
    )


#: Sentence-final stop and list separator, for locales whose typography does not use the
#: ASCII ``.``/``, ``  dashboard_strings itself carries translated sentences, not these
#: two joiners the dashboard assembles at render time.  A locale absent from either map
#: falls back to ASCII, so a language written with the ASCII forms (``ko``, ``ru``,
#: ``fr``, ``hi``, ``es``, ``en``) never needs an entry here.
_SENTENCE_END: dict[str, str] = {"zh-CN": "。", "ja": "。"}
_LIST_SEPARATOR: dict[str, str] = {"zh-CN": "、", "ja": "、", "ar": "، "}


def _release_cards(rows: list[dict], locale: str = DEFAULT_DASHBOARD_LOCALE) -> str:
    """Touchpoint two and the replacement authorization as one control.

    Unless the automatic verification fails, there is no reason a preview the user has
    already approved should not replace production.  That means the second click was
    asking a question whose answer the first click already contained.  What stops bad
    bytes is ``verify-candidate``, which is mechanical and runs regardless.  So the card
    states both consequences up front and takes both decisions at once.
    """
    s = dashboard_strings(locale)
    end_punct = _SENTENCE_END.get(locale, ".")
    list_sep = _LIST_SEPARATOR.get(locale, ", ")
    cards = []
    for row in rows:
        if row.get("live"):
            cards.append(
                f'<div class="card release" data-topic="{_e(row["topic_id"])}">'
                f'<h3>{_e(row["title"])} <span class="tag live">{s["tag_live"]}</span></h3>'
                f'<div class="muted">{_e(row["topic_id"])} · '
                f'{s["release_live_note"].format(publication_id="<code>" + _e(row["live_publication_id"]) + "</code>")}'
                "</div></div>"
            )
            continue
        problem = row.get("reviewer_locale_problem") or ""
        if problem:
            note = (
                s["release_no_review_locale"]
                if problem == "no_review_locale"
                else s["release_review_locale_absent"].format(
                    locale=_e(row["reviewer_locale"])
                )
            )
            cards.append(
                f'<div class="card release" data-topic="{_e(row["topic_id"])}">'
                f'<h3>{_e(row["title"])}</h3>'
                f'<div class="muted">{_e(row["topic_id"])}</div>'
                f'{_locale_rows(row, locale)}'
                f'<div class="confirm"><p class="muted">{note}</p></div></div>'
            )
            continue
        settled = bool(row["authorization"])
        target = (
            s["target_supersede"].format(
                publication_id="<code>" + _e(row["live_publication_id"]) + "</code>"
            )
            if row["operation"] == "supersede"
            else s["target_first"]
        )
        done = (
            f'<div class="done"><strong>{s["done_title"]}</strong> · {s["done_record_label"]} '
            f'<code>{_e(row["authorization"])}</code>'
            f'<div class="muted">{s["done_hint"]}</div></div>'
            if settled
            else ""
        )
        control = (
            ""
            if settled
            else (
                '<div class="row">'
                f'<button class="go" data-approve-release data-topic="{_e(row["topic_id"])}" '
                f'data-key="{_e(row["preview_key"])}">{s["approve_release_btn"]}</button>'
                f'<button data-note data-subject="{_e(row["topic_id"])}">{s["write_note_btn"]}</button>'
                "</div>"
                '<div class="confirm" hidden><p class="muted">'
                f'{s["confirm_records"]}{target}{end_punct}'
                f'<br>{s["confirm_kept_history"]}'
                f'<br>{s["confirm_not_immediate"]}'
                "</p>"
                f'{_locale_plan_html(row, s)}'
                f'<div class="row"><input type="text" name="reason" '
                f'placeholder="{_e(s["reason_placeholder_each"])}"></div>'
                f'<div class="row"><button class="go" data-confirm-release>{s["confirm_approve_btn"]}</button>'
                f'<button data-cancel>{s["cancel"]}</button></div></div>'
            )
        )
        theme_value = _e(row["theme_token"]) if row["theme_token"] else s["theme_none"]
        category_ids = row.get("categories") or []
        categories_text = (
            list_sep.join(_e(item) for item in category_ids)
            if category_ids
            else s["categories_none"]
        )
        prepared = (
            s["prepared_label"].format(id=_e(row["publication_id"]))
            if row["publication_id"]
            else s["not_prepared_label"]
        )
        cards.append(
            f'<div class="card release" data-topic="{_e(row["topic_id"])}">'
            f'<h3>{_e(row["title"])}</h3>'
            f'<div class="muted">{_e(row["topic_id"])} · '
            f'{s["page_run_label"].format(value=_e(row["page_run_id"]))}'
            f' · {s["theme_label"].format(value=theme_value)}'
            f' · {s["categories_label"].format(value=categories_text)}'
            f" · {prepared}"
            "</div>"
            f"{_locale_rows(row, locale)}{control}{done}</div>"
        )
    return "".join(cards)


#: The subset of ``dashboard_strings`` keys ``DASHBOARD_JS`` reads at runtime — the
#: ``__I18N__`` blob carries exactly these, not the whole table, so a page never leaks a
#: feature's copy into its bytes when that feature has nothing to show.
_JS_STRING_KEYS: tuple[str, ...] = (
    "done_title",
    "done_record_label",
    "done_hint",
    "js_reason_required_each",
    "js_reason_required_all",
    "js_approved_authorized",
    "js_not_approved",
    "js_authorized_n_failed_m",
    "js_approved_all",
    "js_note_prompt",
    "js_note_recorded",
    "js_failed",
    "js_scope_signed",
    "js_scope_not_signed",
)


def render_dashboard(state: dict, locale: str = DEFAULT_DASHBOARD_LOCALE) -> str:
    """Regenerate, never edit: every line below is derived from repo state.

    ``locale`` is purely the tool's own display language — never a topic's
    ``review_locale``, which comes from that topic's manifest because it names what an
    approval hash is keyed to, not what the reviewer's browser happens to be showing.
    """
    s = dashboard_strings(locale)
    halo = halo_locale(locale)
    release = state["release"]
    chrome_facts = state["chrome"]
    production = state["production"]

    prod_html = (
        f'<div class="card"><div class="row"><a href="{_e(production["origin"])}/" '
        f'target="_blank" rel="noreferrer">{s["open_production"]}</a>'
        f'<span class="tag">'
        f'{s["topic_count_page_count"].format(topics=production["topic_count"], pages=production["page_count"])}'
        f'</span>'
        f'<span class="tag">{_e(release.get("producer") or "—")}</span>'
        f'<span class="tag">{s["build_date"].format(value=_e(release.get("build_date") or "—"))}</span>'
        f'<span class="tag">{s["chrome_version"].format(value=_e(chrome_facts["version"]))}</span></div>'
        f'<div class="hash">public_fingerprint {_e(release.get("public_fingerprint") or "—")}</div>'
        f'<div class="hash">base_url {_e(release.get("base_url") or "—")}</div></div>'
        if production["origin"]
        else f'<p class="muted">{s["production_missing"]}</p>'
    )

    releases = state["releases"]
    waiting = [
        row for row in releases if not row["authorization"] and not row.get("live")
    ]
    release_html = _release_cards(releases, locale) or (
        f'<p class="muted">{s["release_empty"]}</p>'
    )
    if releases and not waiting:
        release_html = f'<p class="muted">{s["release_none_pending"]}</p>' + release_html
    list_sep = _LIST_SEPARATOR.get(locale, ", ")
    batch = (
        '<div class="card batch"><div class="row">'
        f'<button class="go" data-approve-all>{s["approve_all"].format(n=len(waiting))}</button>'
        f'<span class="muted">{s["approve_all_hint"]}</span></div>'
        f'<div class="confirm" hidden><p class="muted">{s["approve_all_confirm_prefix"]}'
        + list_sep.join(f"<code>{_e(row['topic_id'])}</code>" for row in waiting)
        + _SENTENCE_END.get(locale, ".")
        + "</p>"
        f'<div class="row"><input type="text" name="reason" '
        f'placeholder="{_e(s["reason_placeholder_all"])}"></div>'
        f'<div class="row"><button class="go" data-confirm-all>{s["confirm_all"]}</button>'
        f'<button data-cancel>{s["cancel"]}</button></div></div></div>'
        if len(waiting) > 1
        else ""
    )

    scope_rows = [row for row in state["scope"] if row["state"] != "signed"]
    signed = len(state["scope"]) - len(scope_rows)
    scope_cards = []
    for row in scope_rows:
        scope_cards.append(
            f'<div class="card"><h3>{_e(row.get("title") or row["topic_id"])} '
            f'<span class="tag wait">{s["tag_unsigned"]}</span></h3>'
            f'<div class="muted">{_e(row["topic_id"])} · {_e(row.get("detail"))}</div>'
            f'<div class="row"><button data-scope="{_e(row["topic_id"])}" '
            f'data-candidates="{"1" if row.get("candidates") else "0"}">{s["sign_in_browser_btn"]}</button></div>'
            '<div class="scope-form" hidden></div></div>'
        )
    if not scope_cards:
        scope_cards.append(f'<p class="muted">{s["scope_empty"].format(n=signed)}</p>')
    elif signed:
        scope_cards.append(f'<p class="muted">{s["scope_more_signed"].format(n=signed)}</p>')

    panels = state.get("panels") or []
    panels_html = ""
    if panels:
        links = "".join(
            f'<div class="row"><a href="{_e(panel["url_path"])}" target="_blank" '
            f'rel="noreferrer">{_e(panel["name"])} ↗</a></div>'
            for panel in panels
        )
        panels_html = (
            f'<h2>{s["section_panels"]}</h2>'
            f'<div class="card">{links}'
            f'<div class="muted">{s["panels_hint"]}</div></div>'
        )

    controls_html = _chrome_controls_html(s, locale)
    # Only the keys DASHBOARD_JS actually reads — not the whole table — so a page whose
    # feature is absent (no panels, nothing waiting) never carries that feature's copy
    # anywhere in its bytes, matching what the visible HTML shows.
    i18n_payload = json.dumps(
        {key: s[key] for key in _JS_STRING_KEYS}, ensure_ascii=False
    )

    return (
        "<!doctype html>\n"
        # ``lang`` names the page's own language (the BCP-47 site-locale code); only
        # ``halo.display_lang`` — the script variant the halo ring's own word renders in —
        # would be wrong here, that field is for that one word, not the whole document.
        f'<html lang="{_e(locale)}" dir="{_e(halo.direction)}">'
        f"<head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{DASHBOARD_TITLE}</title>"
        f"<script>{_early_theme_and_locale_js(locale)}</script>"
        f"<style>{DASHBOARD_CSS}</style></head><body>"
        f"{controls_html}"
        f"<h1>{DASHBOARD_TITLE}</h1>"
        f'<h2>{s["section_production"]}</h2>{prod_html}'
        f'<h2>{s["section_scope"]}</h2>{"".join(scope_cards)}'
        f'<h2>{s["section_release"]}</h2>{batch}{release_html}'
        f"{panels_html}"
        '<div id="toast" role="status"></div>'
        f'<script id="__I18N__" type="application/json">{i18n_payload}</script>'
        f'<script id="__LOCALE__" type="application/json">{json.dumps(locale)}</script>'
        f"<script>{DASHBOARD_JS}</script></body></html>\n"
    )


def _chrome_controls_html(s: Mapping[str, str], locale: str) -> str:
    """The top-right theme and language buttons, same corner on every load.

    The language menu lists all nine halo locales by their own endonym — never by an
    English name — so a visitor who cannot read the current language can still recognize
    their own.
    """
    menu_items = "".join(
        f'<button type="button" data-locale="{_e(entry.locale)}" '
        f'class="{"on" if entry.locale == locale else ""}" '
        f'lang="{_e(entry.display_lang)}">{_e(entry.endonym)}</button>'
        for entry in HALO_LOCALES
    )
    return (
        '<div class="chrome-controls">'
        f'<button type="button" id="themebtn" class="fab" '
        f'title="{_e(s["theme_button_label"])}" aria-label="{_e(s["theme_button_label"])}">'
        "&#9789;</button>"
        '<div class="lang-wrap">'
        f'<button type="button" id="langbtn" class="fab" '
        f'title="{_e(s["language_button_label"])}" aria-label="{_e(s["language_button_label"])}" '
        'aria-haspopup="true" aria-expanded="false">&#127760;</button>'
        f'<div id="langmenu" class="lang-menu" role="menu" hidden>{menu_items}</div>'
        "</div></div>"
    )


def _early_theme_and_locale_js(locale: str) -> str:
    """Runs before the stylesheet paints, so a stored theme never flashes wrong (the same
    pattern as ``render/script.py``) and a stored language redirects before first render.
    """
    current = json.dumps(locale)
    return (
        "(function(){try{"
        "var raw=localStorage.getItem('newsab.dashboardPrefs');"
        "var prefs=raw?JSON.parse(raw):{};"
        "if(prefs.theme==='dark'||prefs.theme==='light'){"
        "document.documentElement.setAttribute('data-theme',prefs.theme);}"
        "var params=new URLSearchParams(location.search);"
        f"if(!params.has('locale')&&prefs.locale&&prefs.locale!=={current}){{"
        "params.set('locale',prefs.locale);"
        "location.replace(location.pathname+'?'+params.toString());}"
        "}catch(e){}})();"
    )


#: The client-side strings come from the ``__I18N__`` blob ``render_dashboard`` injects —
#: the whole ``dashboard_strings(locale)`` table for the page's own language, so JS never
#: carries a second, separately-maintained copy of any UI string.
DASHBOARD_JS = r"""
(function(){
  var toast=document.getElementById('toast');
  function payload(id){
    var node=document.getElementById(id);
    if(!node){return {}}
    try{return JSON.parse(node.textContent)}catch(e){return {}}
  }
  var strings=payload('__I18N__');
  var locale=(function(){
    var node=document.getElementById('__LOCALE__');
    if(!node){return 'zh-CN'}
    try{return JSON.parse(node.textContent)}catch(e){return 'zh-CN'}
  })();
  function fmt(template,values){
    return Object.keys(values||{}).reduce(function(out,key){
      return out.split('{'+key+'}').join(values[key]);
    },template||'');
  }
  function readPrefs(){
    try{return JSON.parse(localStorage.getItem('newsab.dashboardPrefs')||'{}')||{}}
    catch(e){return {}}
  }
  function writePrefs(patch){
    try{
      var all=readPrefs();
      Object.keys(patch).forEach(function(key){all[key]=patch[key]});
      localStorage.setItem('newsab.dashboardPrefs',JSON.stringify(all));
    }catch(e){/* storage refused: the page still works, the choice just resets */}
  }

  function say(text){toast.textContent=text;clearTimeout(say._t);
    say._t=setTimeout(function(){toast.textContent=''},8000)}
  function post(path,body){
    return fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)}).then(function(r){return r.json().then(function(j){
        if(!r.ok||j.error){throw new Error(j.error||('HTTP '+r.status))}return j})})}

  function settle(card,path){
    var confirmBox=card.querySelector('.confirm');
    if(confirmBox)confirmBox.hidden=true;
    var button=card.querySelector('[data-approve-release]');
    if(button)button.remove();
    var done=document.createElement('div');
    done.className='done';
    done.innerHTML='<strong>'+strings.done_title+'</strong> · '+strings.done_record_label+
      ' <code></code><div class="muted">'+strings.done_hint+'</div>';
    done.querySelector('code').textContent=path;
    card.appendChild(done);
  }

  function release(card,reason){
    var button=card.querySelector('[data-approve-release]');
    var addLocales=[].slice.call(card.querySelectorAll('[data-locale-choice]:checked'))
      .map(function(box){return box.value});
    return post('/api/approve-release',{topic_id:button.dataset.topic,
      preview_key:button.dataset.key,reason:reason,add_locales:addLocales})
      .then(function(j){settle(card,j.authorization);return j});
  }

  // ---------------------------------------------------------------- theme + language
  function resolvedDark(){
    var set=document.documentElement.getAttribute('data-theme');
    if(set){return set==='dark'}
    return !!(window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches);
  }
  var themeBtn=document.getElementById('themebtn');
  if(themeBtn){
    themeBtn.addEventListener('click',function(){
      var next=resolvedDark()?'light':'dark';
      document.documentElement.setAttribute('data-theme',next);
      writePrefs({theme:next});
    });
  }
  var langBtn=document.getElementById('langbtn');
  var langMenu=document.getElementById('langmenu');
  if(langBtn&&langMenu){
    langBtn.addEventListener('click',function(event){
      event.stopPropagation();
      var open=langMenu.hidden;
      langMenu.hidden=!open;
      langBtn.setAttribute('aria-expanded',open?'true':'false');
    });
    langMenu.addEventListener('click',function(event){
      var choice=event.target.closest('[data-locale]');
      if(!choice)return;
      var picked=choice.dataset.locale;
      writePrefs({locale:picked});
      var params=new URLSearchParams(location.search);
      params.set('locale',picked);
      location.assign(location.pathname+'?'+params.toString());
    });
    document.addEventListener('click',function(event){
      if(!langMenu.hidden&&!event.target.closest('.lang-wrap')){
        langMenu.hidden=true;langBtn.setAttribute('aria-expanded','false');
      }
    });
  }

  document.addEventListener('click',function(event){
    var open=event.target.closest('[data-approve-release]');
    if(open){
      // The consequence is stated before the click that causes it, in the card itself —
      // never in a modal prompt that leaves nothing behind.
      open.closest('.release').querySelector('.confirm').hidden=false;
      return;
    }
    var openAll=event.target.closest('[data-approve-all]');
    if(openAll){openAll.closest('.batch').querySelector('.confirm').hidden=false;return}

    var cancel=event.target.closest('[data-cancel]');
    if(cancel){cancel.closest('.confirm').hidden=true;return}

    var confirm=event.target.closest('[data-confirm-release]');
    if(confirm){
      var card=confirm.closest('.release');
      var reason=card.querySelector('[name=reason]').value;
      if(!reason.trim()){say(strings.js_reason_required_each);return}
      confirm.disabled=true;
      release(card,reason)
        .then(function(j){say(fmt(strings.js_approved_authorized,{path:j.authorization}))})
        .catch(function(e){confirm.disabled=false;
          say(fmt(strings.js_not_approved,{error:e.message}))});
      return;
    }

    var confirmAll=event.target.closest('[data-confirm-all]');
    if(confirmAll){
      var batch=confirmAll.closest('.batch');
      var reasonAll=batch.querySelector('[name=reason]').value;
      if(!reasonAll.trim()){say(strings.js_reason_required_all);return}
      confirmAll.disabled=true;
      var cards=[].slice.call(document.querySelectorAll('.release'))
        .filter(function(node){return node.querySelector('[data-approve-release]')});
      var done=0,failed=[];
      cards.reduce(function(chain,node){
        return chain.then(function(){
          return release(node,reasonAll).then(function(){done++})
            .catch(function(e){failed.push(node.dataset.topic+'：'+e.message)});
        });
      },Promise.resolve()).then(function(){
        confirmAll.disabled=false;
        batch.querySelector('.confirm').hidden=true;
        say(failed.length
          ?fmt(strings.js_authorized_n_failed_m,{done:done,failed:failed.length,detail:failed.join('；')})
          :fmt(strings.js_approved_all,{n:done}));
      });
      return;
    }

    var noteBtn=event.target.closest('[data-note]');
    if(noteBtn){
      var text=prompt(strings.js_note_prompt,'');
      if(text===null||!text.trim())return;
      post('/api/note',{subject:noteBtn.dataset.subject,text:text})
        .then(function(j){say(fmt(strings.js_note_recorded,{path:j.path}))})
        .catch(function(e){say(fmt(strings.js_failed,{error:e.message}))});
      return;
    }
    var scope=event.target.closest('[data-scope]');
    if(scope){
      var host=scope.closest('.card').querySelector('.scope-form');
      if(!host.hidden){host.hidden=true;return}
      fetch('/api/scope-form?topic_id='+encodeURIComponent(scope.dataset.scope)+
        '&locale='+encodeURIComponent(locale))
        .then(function(r){return r.json()}).then(function(j){
          if(j.error){say(j.error);return}
          host.innerHTML=j.html;host.hidden=false;
        });
    }
  });

  document.addEventListener('submit',function(event){
    var form=event.target.closest('form[data-scope-form]');
    if(!form)return;
    event.preventDefault();
    var marks=[];
    form.querySelectorAll('[data-candidate]').forEach(function(node){
      marks.push({candidate_id:node.dataset.candidate,
        approved:node.querySelector('[name=approved]').checked,
        required:node.querySelector('[name=required]').checked});
    });
    post('/api/scope-signoff',{topic_id:form.dataset.scopeForm,checkmarks:marks,
      note:form.querySelector('[name=note]').value})
      .then(function(j){say(j.ok?strings.js_scope_signed
        :fmt(strings.js_scope_not_signed,{detail:JSON.stringify(j.steps)}));})
      .catch(function(e){say(fmt(strings.js_failed,{error:e.message}))});
  });
})();
"""


# --------------------------------------------------------------------------- style panel


STYLE_PANEL_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font:14px/1.55 "IBM Plex Sans","Noto Sans SC",system-ui,sans-serif;color:#14171A;
  background:#FBFAF7;display:grid;grid-template-columns:22rem 1fr;height:100vh}
@media (prefers-color-scheme:dark){body{background:#171B20;color:#E7E3DB}}
@media (max-width:900px){body{grid-template-columns:1fr;grid-template-rows:auto 1fr}}
aside{padding:1rem 1.1rem;overflow-y:auto;border-right:1px solid #E0DCD2}
h1{font-size:1.05rem;margin-bottom:.2rem}
p.lede{font-size:.8rem;opacity:.7;margin-bottom:.9rem}
fieldset{border:1px solid #E0DCD2;border-radius:4px;padding:.6rem .7rem;margin:.6rem 0}
legend{font-size:.78rem;padding:0 .3rem;opacity:.75}
label{display:grid;grid-template-columns:1fr auto;gap:.4rem;align-items:center;
  font-size:.8rem;margin:.3rem 0}
input[type=color]{width:3rem;height:1.7rem;border:1px solid #E0DCD2;background:none;padding:0}
select,input[type=text]{font:inherit;font-size:.8rem;padding:.25rem .3rem;
  border:1px solid #E0DCD2;border-radius:2px;background:transparent;color:inherit}
.ratio{font:400 11px/1.4 ui-monospace,Menlo,monospace}
.ratio.bad{color:#9A3A2E;font-weight:600}
.ratio.ok{color:#2F6B3B}
button{font:500 12.5px/1 inherit;padding:.55rem .8rem;border:1px solid #8C2F1E;color:#8C2F1E;
  background:none;border-radius:2px;cursor:pointer;margin:.2rem .3rem .2rem 0}
button:disabled{opacity:.45;cursor:not-allowed;border-color:#767D84;color:#767D84}
iframe{width:100%;height:100%;border:0;background:#FBFAF7}
pre{font:400 11px/1.5 ui-monospace,Menlo,monospace;white-space:pre-wrap;
  border:1px solid #E0DCD2;border-radius:2px;padding:.5rem;margin-top:.5rem;max-height:14rem;
  overflow:auto}
"""


def render_style_panel(registry, page_urls: list[str]) -> str:
    """Dev-3: adjust chrome tokens live, export a *proposal*, never CSS.

    The panel and the page it edits are served from the same loopback root on purpose:
    same-origin is what lets a slider move a real production page's custom properties
    instead of a mock-up of one.
    """
    options = "".join(
        f'<option value="{_e(url)}">{_e(url)}</option>' for url in page_urls
    ) or '<option value="">（这个根里没有议题页）</option>'
    controls = []
    for theme in registry.themes:
        controls.append(
            f'<fieldset data-token="{_e(theme.token)}">'
            f'<legend>{_e(theme.labels["zh-CN"])} · {_e(theme.token)}</legend>'
            f'<label>浅色强调<input type="color" name="accent_light" '
            f'value="{_e(theme.accent_light)}"></label>'
            f'<div class="ratio" data-ratio="light"></div>'
            f'<label>深色强调<input type="color" name="accent_dark" '
            f'value="{_e(theme.accent_dark)}"></label>'
            f'<div class="ratio" data-ratio="dark"></div>'
            f'<label>题头细线<select name="decoration">'
            f'<option value="plain"{" selected" if theme.decoration == "plain" else ""}>无</option>'
            f'<option value="fine-rule"{" selected" if theme.decoration == "fine-rule" else ""}>1px</option>'
            "</select></label></fieldset>"
        )
    payload = json.dumps(
        {
            "schema_version": registry.schema_version,
            "default_token": registry.default_token,
            "themes": [theme.model_dump(mode="json") for theme in registry.themes],
        },
        ensure_ascii=False,
    )
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>样式面板 · {_e(site_identity().site_name)}</title><style>{STYLE_PANEL_CSS}</style></head><body>"
        "<aside><h1>样式面板</h1>"
        '<p class="lede">改的是站点 chrome，不是任何议题的内容字节。'
        "导出的是对 <code>theme_tokens.v1.json</code> 的修改提案，要过对比度门禁、"
        "web-gate 与站点运营者 commit 才生效。</p>"
        f'<label>预览页面<select id="target">{options}</select></label>'
        '<label>配色模式<select id="mode"><option value="system">跟随系统</option>'
        '<option value="light">浅色</option><option value="dark">深色</option></select></label>'
        '<label>应用 token<select id="token"></select></label>'
        f"{''.join(controls)}"
        '<button id="reset">还原</button>'
        '<button id="export">导出提案</button>'
        '<pre id="out" hidden></pre></aside>'
        '<main><iframe id="stage" title="预览"></iframe></main>'
        f'<script id="registry" type="application/json">{payload}</script>'
        f"<script>{STYLE_PANEL_JS}</script></body></html>\n"
    )


STYLE_PANEL_JS = r"""
(function(){
  var registry=JSON.parse(document.getElementById('registry').textContent);
  var stage=document.getElementById('stage');
  var target=document.getElementById('target');
  var mode=document.getElementById('mode');
  var tokenPick=document.getElementById('token');
  var out=document.getElementById('out');
  var PAPER={light:'#FBFAF7',dark:'#171B20'};

  registry.themes.forEach(function(theme){
    var option=document.createElement('option');
    option.value=theme.token;option.textContent=theme.labels['zh-CN']+' · '+theme.token;
    if(theme.token===registry.default_token)option.selected=true;
    tokenPick.appendChild(option);
  });

  function channel(v){v/=255;return v<=0.04045?v/12.92:Math.pow((v+0.055)/1.055,2.4)}
  function luminance(hex){
    var r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
    return 0.2126*channel(r)+0.7152*channel(g)+0.0722*channel(b);
  }
  function ratio(a,b){
    var x=luminance(a),y=luminance(b),hi=Math.max(x,y),lo=Math.min(x,y);
    return (hi+0.05)/(lo+0.05);
  }
  function current(){
    var out={};
    document.querySelectorAll('fieldset[data-token]').forEach(function(box){
      out[box.dataset.token]={
        accent_light:box.querySelector('[name=accent_light]').value.toUpperCase(),
        accent_dark:box.querySelector('[name=accent_dark]').value.toUpperCase(),
        decoration:box.querySelector('[name=decoration]').value
      };
    });
    return out;
  }
  function gate(){
    var ok=true;
    document.querySelectorAll('fieldset[data-token]').forEach(function(box){
      [['light','accent_light'],['dark','accent_dark']].forEach(function(pair){
        var value=box.querySelector('[name='+pair[1]+']').value.toUpperCase();
        var r=ratio(value,PAPER[pair[0]]);
        var node=box.querySelector('[data-ratio='+pair[0]+']');
        node.textContent=pair[0]+' 对比度 '+r.toFixed(2)+':1'+(r<4.5?' — 未过 4.5:1 门禁':'');
        node.className='ratio '+(r<4.5?'bad':'ok');
        if(r<4.5)ok=false;
      });
    });
    document.getElementById('export').disabled=!ok;
    return ok;
  }
  function apply(){
    gate();
    var doc=stage.contentDocument;
    if(!doc||!doc.documentElement)return;
    var root=doc.documentElement;
    var token=tokenPick.value;
    var values=current()[token];
    if(!values)return;
    root.setAttribute('data-theme-token',token);
    if(mode.value==='system'){root.removeAttribute('data-theme')}
    else{root.setAttribute('data-theme',mode.value)}
    var dark=mode.value==='dark'||(mode.value==='system'&&
      doc.defaultView.matchMedia('(prefers-color-scheme: dark)').matches);
    root.style.setProperty('--accent',dark?values.accent_dark:values.accent_light);
    root.style.setProperty('--topic-decoration',values.decoration==='fine-rule'?'1px':'0px');
  }

  stage.addEventListener('load',apply);
  target.addEventListener('change',function(){stage.src=target.value});
  document.addEventListener('input',apply);
  document.addEventListener('change',apply);
  document.getElementById('reset').addEventListener('click',function(){
    registry.themes.forEach(function(theme){
      var box=document.querySelector('fieldset[data-token="'+theme.token+'"]');
      box.querySelector('[name=accent_light]').value=theme.accent_light;
      box.querySelector('[name=accent_dark]').value=theme.accent_dark;
      box.querySelector('[name=decoration]').value=theme.decoration;
    });
    out.hidden=true;apply();
  });
  document.getElementById('export').addEventListener('click',function(){
    if(!gate())return;
    var edited=current();
    var proposal={schema_version:registry.schema_version,default_token:registry.default_token,
      themes:registry.themes.map(function(theme){
        return Object.assign({},theme,edited[theme.token]||{});
      })};
    fetch('/__panel__/export',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(proposal)})
      .then(function(r){return r.json()})
      .then(function(j){out.hidden=false;
        out.textContent=j.error?('失败：'+j.error):('已写入 '+j.path+'\n\n'+
          JSON.stringify(proposal,null,2))});
  });

  if(target.value){stage.src=target.value}else{apply()}
})();
"""


# --------------------------------------------------------------------------- the server


@dataclass
class DevShellContext:
    repo_root: Path
    topics_root: Path
    site_paths: SitePaths
    production_dir: Path
    preview_dirs: list[Path]
    reviewer_id: str
    base_port: int
    #: True only when the operator passed ``--port`` explicitly. An explicit port is the
    #: operator's choice and a clash is their problem to fix; the default port is this
    #: command's own choice and a clash is this command's problem to route around.
    port_explicit: bool = False
    roots: list[ServedRoot] = field(default_factory=list)
    style_origin: str = ""

    def state(self) -> dict:
        return collect_state(
            repo_root=self.repo_root,
            topics_root=self.topics_root,
            site_paths=self.site_paths,
            production_dir=self.production_dir,
            roots=self.roots,
        )


class _JsonMixin:
    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1_000_000:
            raise ArtifactError("request body is missing or too large")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ArtifactError(f"invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise ArtifactError("request body must be a JSON object")
        return payload

    def _relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.context.repo_root))
        except ValueError:
            return str(path)


class DashboardHandler(_JsonMixin, OverlayHandler):
    """The dashboard, the chrome assets it needs, and the decision endpoints."""

    context: DevShellContext

    def do_GET(self) -> None:  # noqa: N802
        route = self.path.split("?", 1)[0]
        if route in ("/", "/index.html"):
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            raw_locale = ""
            for part in query.split("&"):
                if part.startswith("locale="):
                    raw_locale = unquote(part.split("=", 1)[1])
            page = render_dashboard(self.context.state(), locale=resolve_ui_locale(raw_locale))
            return self.send_payload(page.encode("utf-8"), content_type="text/html; charset=utf-8")
        if route == "/api/state":
            return self._json(self.context.state())
        if route == "/api/scope-form":
            return self._scope_form()
        if route == "/api/panel-decisions":
            return self._panel_decisions()
        if route.startswith("/panels/"):
            return self._panel(route)
        if route.startswith("/assets/"):
            payload = self.overlay.get(route.lstrip("/"))
            if payload is not None:
                return self.send_payload(payload)
        self.send_error(404)

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        route = self.path.split("?", 1)[0]
        handlers = {
            "/api/approve-release": self._approve_release,
            "/api/note": self._note,
            "/api/scope-signoff": self._scope_signoff,
            "/api/panel-decision": self._panel_decision,
        }
        handler = handlers.get(route)
        if handler is None:
            return self.send_error(404)
        try:
            self._json(handler(self._body()))
        except (ArtifactError, ValueError, OSError) as exc:
            self._json({"error": str(exc)}, status=400)

    # -- local panels --------------------------------------------------------

    def _panel_decisions(self) -> None:
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        panel = ""
        for part in query.split("&"):
            if part.startswith("panel="):
                panel = unquote(part.split("=", 1)[1])
        try:
            self._json(
                {"decisions": latest_panel_decisions(self.context.site_paths, panel)}
            )
        except (ArtifactError, ValueError, OSError) as exc:
            self._json({"error": str(exc)}, status=400)

    def _panel(self, route: str) -> None:
        """Serve one generated operator panel; the name pattern is the whole guard."""
        name = unquote(route[len("/panels/") :])
        if not PANEL_NAME.fullmatch(name):
            return self.send_error(404)
        target = self.context.site_paths.private_dir / PANELS_DIR / name
        if not target.is_file():
            return self.send_error(404)
        return self.send_payload(
            target.read_bytes(), content_type="text/html; charset=utf-8"
        )

    def _panel_decision(self, body: dict) -> dict:
        result = record_panel_decision(
            self.context.site_paths,
            panel=str(body.get("panel") or ""),
            item_id=str(body.get("item_id") or ""),
            decision=str(body.get("decision") or ""),
            reason=str(body.get("reason") or ""),
        )
        return result | {"path": self._relative(Path(result["path"]))}

    # -- decisions -----------------------------------------------------------

    def _approve_release(self, body: dict) -> dict:
        """Touchpoint two and the replacement authorization, from one confirmation.

        The pages are re-read from the served tree here rather than taken from the
        request, so the hashes signed are the ones the server is holding, not ones a stale
        tab remembered.
        """
        topic_id = str(body["topic_id"])
        preview_key = str(body.get("preview_key") or "")
        state = self.context.state()
        rows = [
            row
            for row in state["releases"]
            if row["topic_id"] == topic_id
            and (not preview_key or row["preview_key"] == preview_key)
        ]
        if not rows:
            raise ArtifactError(f"no reviewable candidate for {topic_id}")
        row = rows[0]
        add_locales = body.get("add_locales") or []
        if not isinstance(add_locales, list):
            raise ArtifactError("add_locales must be a list of locale codes")
        result = record_release_approval(
            self.context.site_paths,
            topic_id=topic_id,
            pages=row["locales"],
            reviewer_locale=row["reviewer_locale"],
            reason=str(body.get("reason") or ""),
            reviewer_id=self.context.reviewer_id,
            publication_id=row["publication_id"],
            categories=row["categories"],
            add_locales=[str(item) for item in add_locales],
        )
        return result | {
            "authorization": self._relative(Path(result["authorization"])),
            "reviews": [self._relative(Path(item)) for item in result["reviews"]],
            "locale_plan": self._relative(Path(result["locale_plan"])),
        }

    def _note(self, body: dict) -> dict:
        path = record_note(
            self.context.site_paths,
            subject=str(body.get("subject") or "note"),
            text=str(body.get("text") or ""),
            reviewer_id=self.context.reviewer_id,
        )
        return {"path": self._relative(path)}

    def _scope_signoff(self, body: dict) -> dict:
        checkmarks = body.get("checkmarks") or []
        if not isinstance(checkmarks, list):
            raise ArtifactError("checkmarks must be a list")
        result = sign_scope(
            self.context.repo_root,
            self.context.topics_root,
            topic_id=str(body["topic_id"]),
            checkmarks=checkmarks,
            approved_by=self.context.reviewer_id,
            note=str(body.get("note") or ""),
        )
        return result

    # -- touchpoint one form -------------------------------------------------

    def _scope_form(self) -> None:
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        topic_id = ""
        raw_locale = ""
        for part in query.split("&"):
            if part.startswith("topic_id="):
                topic_id = unquote(part.split("=", 1)[1])
            elif part.startswith("locale="):
                raw_locale = unquote(part.split("=", 1)[1])
        try:
            self._json(
                {
                    "html": scope_form_html(
                        self.context.topics_root,
                        topic_id,
                        locale=resolve_ui_locale(raw_locale),
                    )
                }
            )
        except (ArtifactError, ValueError, OSError) as exc:
            self._json({"error": str(exc)}, status=400)


def _candidate_review_label(raw_text: object, prefer: tuple[str, ...] = ()) -> str:
    """Pick a display string out of a scope artifact's MultiLangText shape.

    ``prefer`` is tried in order and the English pivot last — the scope content is not
    translated here, so this only chooses which of the languages it was *authored* in
    the reader of this form is most likely to read.
    """
    if not isinstance(raw_text, dict):
        return ""
    values = raw_text.get("values")
    if isinstance(values, dict):
        raw_text = values
    for lang in (*prefer, "en"):
        if lang and raw_text.get(lang):
            return str(raw_text[lang])
    return ""


def scope_form_html(
    topics_root: Path, topic_id: str, locale: str = DEFAULT_DASHBOARD_LOCALE
) -> str:
    """Render the scope, its collection plan and its question seeds as a checkable form.

    ``locale`` is the dashboard's own display language for this fragment's chrome
    — headings, buttons, the placeholder text.  It never touches the scope content itself
    (group labels, include/exclude items, question text), which stays in whatever
    languages the manifest and question candidates were authored in.
    """
    s = dashboard_strings(locale)
    paths = TopicPaths.for_topic(topics_root, topic_id)
    manifest = read_yaml(paths.topic_manifest, TopicManifest)
    # Which of the languages the scope was authored in to *show*: the language this
    # dashboard is speaking, else the language this topic is reviewed in, else the pivot.
    # None of the three is a constant, and none of them translates anything.
    prefer = tuple(dict.fromkeys(x for x in (locale, manifest.review_locale or "") if x))
    groups = "".join(
        f'<li>{_e(group.group_id)} · '
        f'{_e(_candidate_review_label(group.label.values, prefer))}</li>'
        for group in manifest.groups
    )
    include = "".join(f"<li>{_e(item)}</li>" for item in manifest.include)
    exclude = "".join(f"<li>{_e(item)}</li>" for item in manifest.exclude) or "<li>—</li>"

    candidates_path = paths.root / "scope" / "question_candidates.yaml"
    rows = []
    if candidates_path.is_file():
        raw = load_yaml_text(candidates_path.read_text(encoding="utf-8")) or {}
        for candidate in raw.get("candidates", []):
            review = candidate.get("review") or {}
            label = _candidate_review_label(candidate.get("text"), prefer)
            rows.append(
                f'<div data-candidate="{_e(candidate.get("candidate_id"))}">'
                f'<label class="check"><input type="checkbox" name="approved"'
                f'{" checked" if review.get("approved") else ""}>'
                f'<span>{_e(candidate.get("candidate_id"))} {_e(label)}</span></label>'
                f'<label class="check"><input type="checkbox" name="required"'
                f'{" checked" if review.get("required") else ""}>'
                f'<span class="muted">{s["form_required"]}</span></label></div>'
            )
    body = "".join(rows) or f'<p class="muted">{s["form_no_candidates"]}</p>'
    window = s["form_window"].format(
        start=_e(manifest.period.start),
        end=_e(manifest.period.end) if manifest.period.end else s["form_ongoing"],
        risk=_e(manifest.risk_level.value),
    )
    return (
        f'<form data-scope-form="{_e(topic_id)}">'
        f'<p class="muted">{window}</p>'
        f'<h3>{s["form_groups"]}</h3><ul>{groups}</ul>'
        f'<h3>{s["form_include"]}</h3><ul>{include}</ul>'
        f'<h3>{s["form_exclude"]}</h3><ul>{exclude}</ul>'
        f'<h3>{s["form_seeds"]}</h3>{body}'
        f'<div class="row"><input type="text" name="note" placeholder="{_e(s["form_note_placeholder"])}"></div>'
        f'<div class="row"><button type="submit" class="go">{s["form_submit"]}</button></div>'
        f'<p class="hash">scope_hash {_e(manifest.scope_hash())}</p></form>'
    )


class StyleHandler(_JsonMixin, OverlayHandler):
    """A static root that also serves the style panel from the *same* origin.

    Same-origin is the requirement, not a convenience: the panel edits custom properties
    on a real page inside an iframe, which cross-origin would forbid.
    """

    context: DevShellContext

    def do_GET(self) -> None:  # noqa: N802
        route = self.path.split("?", 1)[0]
        if route in ("/__panel__", "/__panel__/"):
            urls = [url for _topic, _locale, url in _topic_pages(Path(self.directory))]
            page = render_style_panel(load_theme_registry(), urls)
            return self.send_payload(page.encode("utf-8"), content_type="text/html; charset=utf-8")
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/__panel__/export":
            return self.send_error(404)
        try:
            path = record_theme_proposal(
                self.context.site_paths,
                payload=self._body(),
                author=self.context.reviewer_id,
            )
            self._json({"path": self._relative(path)})
        except (ArtifactError, ValueError, OSError) as exc:
            self._json({"error": str(exc)}, status=400)


def start_dev_shell(context: DevShellContext) -> list:
    """Bind every root and return the running servers, dashboard first."""
    overlay = chrome.chrome_assets(load_theme_registry())
    context.roots = discover_roots(
        context.site_paths,
        context.production_dir,
        context.preview_dirs,
        context.base_port,
        pending_publications(context.site_paths),
    )
    def bound(base: type) -> type:
        handler_class = make_handler(overlay, base)
        handler_class.context = context
        return handler_class

    # The dashboard serves no files of its own, so its directory is only the safe base
    # for path resolution; every route it answers is explicit.  Its port is the one
    # address the reviewer is told.
    if context.port_explicit:
        # An explicit --port is the operator's own choice, so a clash there is fatal and
        # says so — never move a port they named.
        dashboard_server = serve_forever_in_thread(
            context.repo_root,
            context.base_port,
            handler_factory=lambda: bound(DashboardHandler),
        )
        next_port = context.base_port + 1
    else:
        # No port was named, so a clash is this command's problem: two review sessions
        # (touchpoint one and touchpoint two) now run side by side routinely, and the
        # second one moving to the next free block beats it crashing or needing a
        # hand-typed offset every time.
        dashboard_server, next_port = _bind_upward(
            context.repo_root,
            context.base_port,
            handler_factory=lambda: bound(DashboardHandler),
        )
        context.base_port = dashboard_server.server_port
    servers = [dashboard_server]
    assigned: list[ServedRoot] = []
    for root in context.roots:
        server, next_port = _bind_upward(root.path, next_port, overlay=overlay)
        servers.append(server)
        assigned.append(ServedRoot(**{**root.__dict__, "port": server.server_port}))
    context.roots = assigned
    style_source = next(
        (root for root in assigned if root.kind == "production"),
        assigned[0] if assigned else None,
    )
    if style_source is not None:
        server, next_port = _bind_upward(
            style_source.path, next_port, handler_factory=lambda: bound(StyleHandler)
        )
        servers.append(server)
        context.style_origin = f"http://127.0.0.1:{server.server_port}"
    return servers


#: How far above the base port to look before giving up.  Wide enough for every root a
#: real review has, narrow enough that a wrong --port fails fast instead of wandering.
PORT_SEARCH_SPAN = 64


def _bind_upward(path: Path, start: int, **kwargs):
    """Bind the first free loopback port at or above ``start``.

    Ports stay stable across restarts while the same roots and the same free ports are
    there; when something else on the machine holds one, that root moves and the rest of
    the shell still comes up.
    """
    last: OSError | None = None
    for port in range(start, start + PORT_SEARCH_SPAN):
        try:
            server = serve_forever_in_thread(path, port, **kwargs)
        except OSError as exc:
            last = exc
            continue
        return server, port + 1
    raise ArtifactError(
        f"no free loopback port in {start}..{start + PORT_SEARCH_SPAN - 1}: {last}"
    )


def run_dev_shell(
    *,
    repo_root: Path,
    topics_root: Path,
    site_root: Path,
    production_dir: Path,
    preview_dirs: Iterable[Path],
    reviewer_id: str,
    base_port: int,
    port_explicit: bool = False,
    once: bool = False,
) -> DevShellContext:
    context = DevShellContext(
        repo_root=Path(repo_root).resolve(),
        topics_root=Path(topics_root).resolve(),
        site_paths=SitePaths.at(site_root),
        production_dir=Path(production_dir).resolve(),
        preview_dirs=[Path(item).resolve() for item in preview_dirs],
        reviewer_id=reviewer_id,
        base_port=base_port,
        port_explicit=port_explicit,
    )
    try:
        servers = start_dev_shell(context)
    except OSError as exc:
        # Only the explicit-port path can still raise a raw OSError here: the default
        # path's dashboard bind goes through ``_bind_upward``, which already turns a busy
        # range into an ArtifactError of its own (roots always did).
        raise ArtifactError(
            f"dev shell could not bind the requested --port {base_port}: {exc}. "
            "That port is an explicit choice, so it is not moved automatically — "
            "free it or pick another port."
        ) from exc
    # Bind-then-report: print the ports actually bound, not the ones requested. A default
    # base that had to move is called out explicitly, since an operator with an old tab
    # open at 8787 needs to know the second session landed somewhere else.
    if not port_explicit and context.base_port != base_port:
        print(f"默认端口 {base_port} 被占用，改用 {context.base_port}+ 这一段连续空闲端口。")
    print(f"审核台  http://127.0.0.1:{context.base_port}/")
    for root in context.roots:
        print(f"  {root.kind:<10} {root.origin}/  ← {root.path}")
    print(f"  {'style':<10} {context.style_origin}/__panel__/")
    # Flushed because this map is the whole point of the command, and it is routinely read
    # out of a redirected log rather than a terminal.
    print("Ctrl+C 停止。", flush=True)
    if once:
        for server in servers:
            server.shutdown()
            server.server_close()
        return context
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("")
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
    return context
