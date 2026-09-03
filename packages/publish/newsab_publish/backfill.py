"""Locale backfill: bring every live publication to the site's current locale set *and*
its topic's current editorial run.

When the operator edits ``locales`` in ``site_metadata.v1.json`` the site has learned a
language, and every live publication should ship it (``skills/publish/references/
localization.md``). The same machinery also carries a content-only rerun on the
non-reviewed languages — e.g. a lexicon-fill patch round that fixes an untranslated side
badge or an outlet description in eight locales no human ever read — into production
without a second human review, because that is exactly what a rerun on non-reviewed
languages already is: the locale set can stay the same while the topic's active editorial
run moves, and this command backfills either kind of drift the same way. The content
approval carries: a ``PublicationReview`` binds the page the reviewer read, not one
rendering of it, so re-preparing the same approved bytes under a wider locale set (or a
newer run with the reviewed languages unchanged) needs no human reviewer. What does **not**
carry is the lifecycle
authorization — each supersede is a new operation — so this command mints one
``HumanApproval`` per publication from the single decision the operator states with
``--reason``: running the backfill *is* the human act that authorizes the batch.

Everything that guards the bytes stays mechanical: ``prepare`` refuses a locale whose page
is not fully localized (``check_page`` ``required_langs``) and ``activate`` re-verifies the
candidate.  What is different here, and **only** here, is how the user's approval is
re-proved.  A backfill runs months after the review, against the topic's current editorial
run and today's renderer, so two things have moved that no human reviewed: the
run's own provenance line (an expansion run is a new run) and renderer-owned chrome.  The
strict byte re-prove would refuse every publication on those grounds alone, which is why
this path passes a :func:`newsab_publish.builder.signed_baseline` and ``prepare`` proves
equivalence instead — the approved content identical in every reviewed language, and the
rendered bytes differing only inside a closed whitelist
(``newsab_publish.reviewed_equivalence``).  A topic whose active page run drifted in
content still fails, exactly as before, and is reported for the ordinary review path
instead of being silently shipped.  Every touchpoint-two ``prepare`` keeps the strict
byte-for-byte re-prove untouched.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

from newsab_schema.common import LangText
from newsab_schema.io import ArtifactError
from newsab_schema.models.manifest import file_digest
from newsab_schema.models.publication import HumanApproval, PublicationReview
from newsab_schema.paths import SitePaths, TopicPaths
from newsab_schema.store import (
    derive_publish_selector,
    load_publication_events,
    load_publications,
)

from .builder import (
    _publication_id,
    activate_publication,
    bytes_digest,
    prepare_publication,
    resolve_inputs,
    resolve_publication_locales,
    signed_baseline,
)
from .dev_shell import APPROVALS_DIR
from .metadata import SiteMetadata


@dataclass
class BackfillOutcome:
    topic_id: str
    status: str  # "superseded" | "skipped" | "failed"
    detail: str
    old_publication_id: str = ""
    new_publication_id: str = ""
    old_locales: Sequence[str] = field(default_factory=tuple)
    new_locales: Sequence[str] = field(default_factory=tuple)

    def render(self) -> str:
        line = f"{self.topic_id}: {self.status} — {self.detail}"
        if self.status == "superseded":
            line += (
                f" ({self.old_publication_id} {list(self.old_locales)} -> "
                f"{self.new_publication_id} {list(self.new_locales)})"
            )
        return line


def _approval_for(
    site_paths: SitePaths,
    *,
    topic_id: str,
    publication_id: str,
    reviewer_id: str,
    reason: str,
    reason_lang: str,
    when: datetime,
) -> HumanApproval:
    """This publication's backfill authorization, minted once and reread on resume.

    Written under the ordinary ``activate-<publication_id>.json`` name so ``dev-serve``
    and any later audit read it exactly like a dashboard-taken decision.  Never an
    intent: the candidate id exists by the time this runs, and intents are single-use
    records of a *different* decision.
    """
    target = site_paths.private_dir / APPROVALS_DIR / f"activate-{publication_id}.json"
    if target.is_file():
        return HumanApproval.model_validate_json(target.read_text(encoding="utf-8"))
    seed = f"backfill|{publication_id}|{when.isoformat()}"
    approval = HumanApproval(
        approval_id=f"APR-{topic_id}-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:8]}",
        reviewer_id=reviewer_id,
        decided_at=when,
        note=LangText(text=reason, lang=reason_lang),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(approval.model_dump_json() + "\n", encoding="utf-8")
    return approval


def _reviewed_locales(review: PublicationReview, shipped: Sequence[str]) -> PublicationReview:
    """The locale set the signed bytes were rendered under, from the live record.

    Records written before ``reviewed_locales`` existed omit it; the set the review was
    bound into is exactly what its publication shipped, so that is what ``prepare``
    re-proves against — never today's wider set, never memory
    (``skills/publish/references/localization.md``).
    """
    if review.reviewed_locales:
        return review
    return PublicationReview.model_validate(
        review.model_dump(mode="json") | {"reviewed_locales": list(shipped)}
    )


def backfill_locales(
    topics_root: str | Path,
    site_root: str | Path,
    *,
    metadata: SiteMetadata,
    metadata_path: str | Path,
    production_dir: str | Path,
    base_url: str,
    reason: str,
    reason_lang: str = "en",
    reviewer_id: str = "founder",
    build_date: Optional[date] = None,
    only_topics: Optional[Sequence[str]] = None,
    page_runs: Optional[Mapping[str, str]] = None,
) -> list[BackfillOutcome]:
    """Re-prepare + supersede every live publication to the site's locale set.

    Sequential and per-topic independent: one topic's refusal (usually "this language is
    not localized in the page run yet") is reported and the rest proceed, because each
    supersede is its own atomic event.  Re-running after a partial failure is safe — a
    topic already shipping the set is skipped, an already-prepared candidate is reused
    (its id is deterministic), and its approval record is reread rather than re-minted.
    """
    if not reason.strip():
        raise ArtifactError("a locale backfill needs a reason: it goes into every event")
    site_paths = SitePaths.at(site_root).ensure()
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
    metadata_fingerprint = bytes_digest(Path(metadata_path).read_bytes())
    when = datetime.now(timezone.utc).replace(microsecond=0)
    outcomes: list[BackfillOutcome] = []
    wanted = set(only_topics) if only_topics else None

    for topic_id, live_id in sorted(selector.publications.items()):
        if wanted is not None and topic_id not in wanted:
            continue
        record = publications[live_id]
        shipped = tuple(bundle.locale for bundle in record.locales)
        try:
            target_locales = resolve_publication_locales(metadata, record.review.locale)
            page_run_id = (page_runs or {}).get(topic_id) or TopicPaths.for_topic(
                topics_root, topic_id
            ).active_run_id("editorial")
            if not page_run_id:
                raise ArtifactError(f"{topic_id} has no active editorial run")
            # Skip only when *nothing* this command exists to fix has moved: neither
            # the site's locale set (the original reason this command was built) nor
            # the topic's pinned editorial run (an append-only content-only rerun on
            # non-reviewed languages — e.g. a lexicon-fill patch round — leaves the
            # locale set untouched but the page run id does move; without this second
            # condition such a rerun could never reach a live publication at all,
            # since the locale-set check alone would skip it forever).  Either kind of
            # drift is proved equivalent the same way, by the same call below.
            if set(shipped) == set(target_locales) and page_run_id == record.page_run_id:
                outcomes.append(
                    BackfillOutcome(
                        topic_id,
                        "skipped",
                        f"already ships the site locale set {list(target_locales)} "
                        f"from its current editorial run {page_run_id}",
                        old_publication_id=live_id,
                    )
                )
                continue
            review = _reviewed_locales(record.review, shipped)
            resolved = resolve_inputs(topics_root, topic_id, page_run_id)
            publication_id = _publication_id(
                resolved, review, metadata_fingerprint, target_locales, record.theme_token
            )
            if site_paths.publication_record(publication_id).is_file():
                detail = "reusing the already-prepared candidate"
            else:
                prepare_publication(
                    topics_root,
                    site_root,
                    topic_id,
                    page_run_id=page_run_id,
                    review=review,
                    metadata=metadata,
                    metadata_path=metadata_path,
                    locales=target_locales,
                    default_locale=record.default_locale,
                    theme_token=record.theme_token,
                    baseline=signed_baseline(topics_root, site_paths, record),
                )
                detail = "prepared a new candidate"
            approval = _approval_for(
                site_paths,
                topic_id=topic_id,
                publication_id=publication_id,
                reviewer_id=reviewer_id,
                reason=reason,
                reason_lang=reason_lang,
                when=when,
            )
            event = activate_publication(
                topics_root,
                site_root,
                publication_id,
                approval=approval,
                metadata=metadata,
                production_dir=production_dir,
                base_url=base_url,
                build_date=build_date or when.date(),
                reason=LangText(text=reason, lang=reason_lang),
            )
            outcomes.append(
                BackfillOutcome(
                    topic_id,
                    "superseded",
                    f"{detail}; event {event.event_id}",
                    old_publication_id=live_id,
                    new_publication_id=publication_id,
                    old_locales=shipped,
                    new_locales=target_locales,
                )
            )
        except ArtifactError as exc:
            outcomes.append(
                BackfillOutcome(
                    topic_id, "failed", str(exc), old_publication_id=live_id
                )
            )
    return outcomes
