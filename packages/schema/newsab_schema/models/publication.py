"""Site-level publication records (value chain stage 8).

Topic runs remain inside ``topics/<topic_id>``.  These records live in the sibling
``site/`` artifact root and bind one reviewed page to its complete topic-run closure.
The immutable publication is a release candidate; an append-only event makes it live.
Catalog rows and the production selector are derived caches, never additional facts.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import PurePosixPath
import re
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator

from ..common import LangText, Provenance, Record, normalize_lang
from ..enums import FindingKind, FindingStrength, PublicationEventType
from ..ids import RUN_ID_RE, parse_prefixed_id, validate_topic_id
from .manifest import HASH_RE, content_digest


PUBLICATION_ID_RE = r"^PUB-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{12}$"
PUBLICATION_EVENT_ID_RE = r"^EVT-\d{14}-[0-9a-f]{8}$"
#: The one Phase-0 scope artifact that predates the suffixed run-id contract.  This is a
#: closed list of literal ids, not a shape: a merely shape-matching id minted later must
#: not inherit the legacy exemption from RUN_ID_RE.
LEGACY_SCOPE_RUN_IDS = frozenset({"scope-20260823055138"})
REQUIRED_PUBLICATION_STAGES = frozenset(
    {"scope", "corpus", "questions", "answers", "normalization", "analysis", "page"}
)


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _publication_belongs(publication_id: str, topic_id: str) -> bool:
    """Exact structural binding: ``PUB-<topic_id>-<12 hex>`` and nothing looser.

    A prefix test is not enough — with hyphenated topic ids, ``PUB-aabb-river-light-2026-…``
    also starts with ``PUB-aabb-river-light-``, so a sibling topic could claim it.
    """
    prefix = f"PUB-{topic_id}-"
    if not publication_id.startswith(prefix):
        return False
    return re.fullmatch(r"[0-9a-f]{12}", publication_id[len(prefix):]) is not None


def _site_url(value: str) -> str:
    """Accept one root-relative static URL and reject filesystem/navigation tricks."""
    if not value.startswith("/") or value.startswith("//"):
        raise ValueError("site URL must be root-relative and start with one slash")
    path = PurePosixPath(value.split("#", 1)[0].split("?", 1)[0])
    if ".." in path.parts or "\\" in value:
        raise ValueError("site URL may not contain parent traversal or backslashes")
    return value


class TopicRunPin(Record):
    """One cross-root dependency edge from a publication to a topic run."""

    topic_id: str
    stage: Literal["scope", "corpus", "questions", "answers", "normalization", "analysis", "page"]
    # One Phase-0 topic predates the suffixed run-id contract. Publication must be able
    # to pin that exact immutable scope artifact without rewriting history; the exception
    # is deliberately limited to the scope stage and its one legacy shape.
    run_id: str
    artifact_fingerprint: str = Field(pattern=HASH_RE)

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, value: str) -> str:
        return validate_topic_id(value)

    @model_validator(mode="after")
    def _run(self) -> "TopicRunPin":
        if RUN_ID_RE.fullmatch(self.run_id):
            return self
        if self.stage == "scope" and self.run_id in LEGACY_SCOPE_RUN_IDS:
            return self
        raise ValueError("run_id must be canonical, except for the known legacy scope pins")


class HumanApproval(Record):
    """A human decision authorizing a final page or lifecycle operation.

    This is deliberately human-only.  The scope stage has a separately recorded and
    explicitly limited stand-in path; final review and publication lifecycle changes do
    not acquire that authority by reuse.
    """

    approval_id: str = Field(pattern=r"^APR-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{8}$")
    reviewer_id: str = Field(min_length=1)
    decided_at: datetime
    decision: Literal["approved"] = "approved"
    note: Optional[LangText] = None

    @field_validator("decided_at")
    @classmethod
    def _decided_at(cls, value: datetime) -> datetime:
        return _utc(value)


class PublicationReview(HumanApproval):
    """Touchpoint-two approval of the exact localized page bytes."""

    locale: str
    page_hash: str = Field(pattern=HASH_RE)
    #: The locale set the reviewed bytes were rendered under.  A page states which other
    #: languages it exists in, so its bytes depend on the whole set — yet the reviewer
    #: approved the *page*, and the set is a site-owned decision they did not make in
    #: this sitting.  Recording it lets a later build re-prove these exact bytes while
    #: shipping a wider set, so adding a language never forces a human to re-approve an
    #: article they already read.  Absent on records written before this field existed.
    reviewed_locales: Optional[list[str]] = None

    @field_validator("locale")
    @classmethod
    def _locale(cls, value: str) -> str:
        return normalize_lang(value)

    @field_validator("reviewed_locales")
    @classmethod
    def _reviewed_locales(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        normalized = [normalize_lang(locale) for locale in value]
        if not normalized:
            raise ValueError("reviewed_locales must not be empty when present")
        if len(normalized) != len(set(normalized)):
            raise ValueError("reviewed_locales must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def _reviewed_here(self) -> "PublicationReview":
        if self.reviewed_locales is not None and self.locale not in self.reviewed_locales:
            raise ValueError(
                "the reviewed locale must be among the locales the reviewed bytes were "
                f"rendered under: {self.locale!r} not in {self.reviewed_locales}"
            )
        return self


class LocalePlan(Record):
    """Touchpoint two's authorization of which halo locales a topic's page should reach.

    Recorded in the same confirmation as the ``PublicationReview``: the user's one
    click also states the full target locale set.  ``included_locales`` is read-only in the dashboard card
    — it is exactly the set the reviewed candidate already ships (English pivot plus the
    reviewer's own language, at minimum).  ``target_locales`` is what the user
    actually authorized, a superset that may add any of the halo's other locales without
    a second sitting.  A later render-localize expansion run and ``prepare --locales``
    cite this record's ``reason`` as their human authorization; adding a language never
    returns to touchpoint two — site operation is not a third editorial pass
    (``value_chain.md``).  Single-use like the activation intent it sits beside: a
    consumer marks it spent rather than re-reading it as though the user can revise
    the plan out of band.
    """

    approval_id: str = Field(pattern=r"^APR-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{8}$")
    topic_id: str
    reviewer_id: str = Field(min_length=1)
    decided_at: datetime
    #: The reviewed candidate's page hash — the same bytes the sibling
    #: ``PublicationReview`` binds — so a plan can never be read back against the wrong
    #: candidate.
    reviewed_hash: str = Field(pattern=HASH_RE)
    included_locales: list[str] = Field(min_length=1)
    target_locales: list[str] = Field(min_length=1)
    reason: LangText

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, value: str) -> str:
        return validate_topic_id(value)

    @field_validator("decided_at")
    @classmethod
    def _decided_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("included_locales", "target_locales")
    @classmethod
    def _locales(cls, values: list[str]) -> list[str]:
        normalized = [normalize_lang(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("locale-plan locale lists must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def _target_covers_included(self) -> "LocalePlan":
        missing = sorted(set(self.included_locales) - set(self.target_locales))
        if missing:
            raise ValueError(
                "target_locales must include every already-shipped locale: missing "
                f"{missing}"
            )
        return self


class SponsorAttribution(Record):
    """Public sponsor credit; control credentials never belong in this record."""

    anonymous: bool = False
    display_name: Optional[str] = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _identity(self) -> "SponsorAttribution":
        if self.anonymous and self.display_name is not None:
            raise ValueError("an anonymous sponsor must not leak a display name")
        if not self.anonymous and self.display_name is None:
            raise ValueError("a named sponsor needs display_name")
        return self


class WorkerAttribution(Record):
    """One AI model's actual stage contribution, backed by run ids."""

    model_id: str = Field(min_length=1)
    stages: list[str] = Field(min_length=1)
    run_ids: list[str] = Field(min_length=1)

    @field_validator("stages", "run_ids")
    @classmethod
    def _unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("worker stages and run_ids must not contain duplicates")
        return values

    @field_validator("run_ids")
    @classmethod
    def _runs_shape(cls, values: list[str]) -> list[str]:
        bad = [
            value
            for value in values
            if not RUN_ID_RE.fullmatch(value) and value not in LEGACY_SCOPE_RUN_IDS
        ]
        if bad:
            raise ValueError(f"worker run_ids are invalid: {bad}")
        return values

    @model_validator(mode="after")
    def _legacy_scope_only(self) -> "WorkerAttribution":
        if any(value in LEGACY_SCOPE_RUN_IDS for value in self.run_ids):
            if "scope" not in self.stages:
                raise ValueError("a legacy scope run_id requires scope attribution")
        return self


class LocaleBundle(Record):
    """The final static page for one supported reader locale."""

    locale: str
    page_url: str
    page_hash: str = Field(pattern=HASH_RE)

    @field_validator("locale")
    @classmethod
    def _locale(cls, value: str) -> str:
        return normalize_lang(value)

    @field_validator("page_url")
    @classmethod
    def _url(cls, value: str) -> str:
        return _site_url(value)


class ShareAsset(Record):
    """One angle's public-safe share landing, generated from the same pinned page.

    The landing page is what the share button hands a system share sheet and what a
    crawler reads for the per-angle ``og:title`` / ``og:description``.  Producers up to
    ``publish-0.7.0`` also drew one SVG card per angle and locale and pinned it here as
    ``url`` / ``sha256`` (retired: no platform renders SVG as a card image, and the
    release had already pointed every crawler at the site's PNG card).
    A record minted since carries the landing alone and leaves the image fields ``None``;
    the historical records keep theirs, so a verifier must accept both shapes.
    """

    locale: str
    question_id: str
    landing_url: str
    landing_sha256: str = Field(pattern=HASH_RE)
    url: Optional[str] = None
    sha256: Optional[str] = Field(default=None, pattern=HASH_RE)
    mime_type: Optional[Literal["image/svg+xml"]] = None
    width: Optional[Literal[1200]] = None
    height: Optional[Literal[630]] = None

    @model_validator(mode="before")
    @classmethod
    def _image_all_or_nothing(cls, data):
        if not isinstance(data, dict):
            return data
        has_image = data.get("url") is not None
        if has_image:
            # A pinned card is always the one shape the retired renderer drew; a
            # historical record spelled the constants out, a caller need not.
            data = {
                "mime_type": "image/svg+xml",
                "width": 1200,
                "height": 630,
                **{key: value for key, value in data.items() if value is not None},
            }
        image_fields = ("url", "sha256", "mime_type", "width", "height")
        present = [key for key in image_fields if data.get(key) is not None]
        if present and len(present) != len(image_fields):
            raise ValueError(
                "share asset image url, sha256, mime_type, width and height appear together"
            )
        return data

    @field_validator("locale")
    @classmethod
    def _locale(cls, value: str) -> str:
        return normalize_lang(value)

    @field_validator("question_id")
    @classmethod
    def _question_id(cls, value: str) -> str:
        parse_prefixed_id(value, "QST")
        return value

    @field_validator("url")
    @classmethod
    def _url(cls, value: Optional[str]) -> Optional[str]:
        return _site_url(value) if value is not None else None

    @field_validator("landing_url")
    @classmethod
    def _landing_url(cls, value: str) -> str:
        return _site_url(value)


class DataAsset(Record):
    """One content-addressed, language-neutral data island the page bytes reference.

    These files are content, not chrome — they enter the candidate bundle's closed
    file list, the bundle fingerprint covers their bytes, and this record pins them by
    name and hash.  The filename embeds the content hash, so the approved page bytes
    (which reference each asset by that name) transitively bind the asset bytes.
    """

    name: str = Field(pattern=r"^[a-z][a-z0-9-]*\.[0-9a-f]{16}\.json$")
    url: str
    sha256: str = Field(pattern=HASH_RE)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        return _site_url(value)


class ReviewedEquivalence(Record):
    """Why a re-prepared publication still carries the bytes a human approved.

    ``prepare`` normally re-renders the reviewed locale set and demands the user's
    exact bytes back.  The site-wide locale backfill cannot: it re-prepares an
    already-approved publication against the topic's current editorial run and today's
    renderer, purely to ship languages the site has since learned, so the run's own
    provenance line and the renderer's chrome have both moved for reasons the user
    never reviewed.  That path proves the same thing in two mechanical layers instead
    (``newsab_publish.reviewed_equivalence``): the approved *content* is identical in
    every reviewed language, and the rendered bytes differ only inside a closed,
    code-owned whitelist.

    This record is the proof's receipt.  ``redacted_digest`` is the hash both renders
    produced once the whitelist was erased — a later ``verify-candidate`` re-renders the
    reviewed set and requires that same digest back, so the proof replays without needing
    the superseded bundle.  Its presence is also the audit trail: a publication that
    reproduces the signed bytes exactly does not carry one.
    """

    #: The locale whose bytes the human signed — the only page compared.
    reviewed_locale: str
    #: The approval this stands in for; equals ``PublicationRecord.review.page_hash``.
    signed_page_hash: str = Field(pattern=HASH_RE)
    #: The editorial run the candidate was measured against — the run that produced the
    #: signed bytes on a publication's first backfill, and the standing (already proven
    #: equivalent) publication's run on every later one, because equivalence composes
    #: through the digest below and the record holding the original bytes is superseded.
    signed_page_run_id: str = Field(min_length=1)
    #: What the reviewed locale renders to when this candidate's page run is put through
    #: the *reviewed* locale set — the apples-to-apples counterpart of
    #: ``signed_page_hash``, and not any bundle this publication ships (those are rendered
    #: under the wider set).  ``verify-candidate`` re-derives exactly this.
    candidate_page_hash: str = Field(pattern=HASH_RE)
    #: Identical on both sides by construction: this is what makes it a proof.
    redacted_digest: str = Field(pattern=HASH_RE)
    whitelist_version: str = Field(min_length=1)
    #: Per whitelist rule, how many of its regions actually differed. Evidence, not a
    #: gate: a record never hides which regions the whitelist absorbed.
    whitelisted_differences: dict[str, int] = Field(default_factory=dict)
    #: ``sha256`` over the reviewed-locale projection of the signed and candidate
    #: ``page.json``.  Layer 1's receipt: equal by construction, and stronger than any
    #: HTML diff because it compares the artifact the writer produced.
    content_digest: str = Field(pattern=HASH_RE)

    @field_validator("reviewed_locale")
    @classmethod
    def _locale(cls, value: str) -> str:
        return normalize_lang(value)


class PublicationRecord(Record):
    """An immutable, reviewed release candidate produced by stage 8.

    It intentionally carries neither ``status`` nor ``published_at``.  Before a publish
    event it means "approved but not published"; the event timestamp is the only
    publication time.  This separation prevents a lifecycle change from rewriting the
    reviewed bytes or their provenance.
    """

    publication_id: str = Field(pattern=PUBLICATION_ID_RE)
    topic_id: str
    page_run_id: str = Field(pattern=RUN_ID_RE.pattern)
    run_closure: list[TopicRunPin]
    review: PublicationReview
    default_locale: str
    locales: list[LocaleBundle] = Field(min_length=1)
    sponsor: SponsorAttribution
    workers: list[WorkerAttribution] = Field(min_length=1)
    share_assets: list[ShareAsset] = Field(default_factory=list)
    #: Data islands (empty for publications minted by earlier producers, whose
    #: pages inline everything).  Shared across locales: one entry per unique asset file.
    data_assets: list[DataAsset] = Field(default_factory=list)
    theme_token: Optional[str] = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,31}$")
    theme_registry_version: Optional[str] = Field(
        default=None, pattern=r"^theme-tokens-\d+\.\d+\.\d+$"
    )
    theme_registry_fingerprint: Optional[str] = Field(default=None, pattern=HASH_RE)
    #: The site-owned taxonomy/home metadata is an input to catalog derivation.  Pinning
    #: both its version and bytes prevents a later category edit from silently changing
    #: an already prepared publication's catalog row.
    site_metadata_version: str = Field(pattern=r"^site-metadata-\d+\.\d+\.\d+$")
    site_metadata_fingerprint: str = Field(pattern=HASH_RE)
    #: Public-safe render inputs that legacy corpus runs did not version (currently the
    #: normalized per-article ``topics_raised`` map).  Prepare archives these exact bytes
    #: under the private site audit root; the public bundle never receives them as a
    #: standalone file.
    render_input_hashes: dict[str, str] = Field(default_factory=dict)
    #: Present only when this candidate does **not** reproduce the reviewed bytes exactly
    #: — today only the site-wide locale backfill, which proves equivalence instead (see
    #: :class:`ReviewedEquivalence`).  Absent means the strict byte re-prove held.
    reviewed_equivalence: Optional[ReviewedEquivalence] = None
    public_bundle_fingerprint: str = Field(pattern=HASH_RE)
    submission_id: Optional[str] = Field(default=None, min_length=1)
    submission_archive_hash: Optional[str] = Field(default=None, pattern=HASH_RE)
    audit_run_id: Optional[str] = Field(default=None, pattern=RUN_ID_RE.pattern)
    prepared_at: datetime
    provenance: Provenance

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, value: str) -> str:
        return validate_topic_id(value)

    @field_validator("default_locale")
    @classmethod
    def _default_locale(cls, value: str) -> str:
        return normalize_lang(value)

    @field_validator("prepared_at")
    @classmethod
    def _prepared_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _pins_reviewed_bytes(self) -> "PublicationRecord":
        if not _publication_belongs(self.publication_id, self.topic_id):
            raise ValueError("publication_id must include its topic_id")
        stages = [pin.stage for pin in self.run_closure]
        if len(stages) != len(set(stages)):
            raise ValueError("run_closure has more than one pin for a stage")
        missing = sorted(REQUIRED_PUBLICATION_STAGES - set(stages))
        if missing:
            raise ValueError(f"run_closure is missing required stages: {missing}")
        wrong_topics = sorted({pin.topic_id for pin in self.run_closure if pin.topic_id != self.topic_id})
        if wrong_topics:
            raise ValueError(f"run_closure crosses into other topics: {wrong_topics}")
        page_pin = next(pin for pin in self.run_closure if pin.stage == "page")
        if page_pin.run_id != self.page_run_id:
            raise ValueError("page_run_id does not match the page pin in run_closure")
        locale_map = {bundle.locale: bundle for bundle in self.locales}
        if len(locale_map) != len(self.locales):
            raise ValueError("locales contains duplicate locale bundles")
        if self.default_locale not in locale_map:
            raise ValueError("default_locale has no static page bundle")
        reviewed = locale_map.get(self.review.locale)
        if reviewed is None:
            raise ValueError("the human-reviewed locale is not in the publication")
        # A page names the other languages it exists in, so widening the locale set moves
        # every page's bytes.  When the publication ships exactly the set that was
        # reviewed, the shipped bytes must *be* the reviewed bytes.  When it ships a
        # superset, the reviewed bytes are re-proved by re-rendering the reviewed set
        # (`verify_candidate`), and what this record asserts is that the set only grew —
        # so a review can never be carried onto a publication that dropped a language.
        shipped = sorted(locale_map)
        reviewed_set = sorted(self.review.reviewed_locales or shipped)
        if reviewed_set == shipped:
            if reviewed.page_hash != self.review.page_hash:
                raise ValueError("publication page bytes differ from the human-reviewed bytes")
        elif not set(reviewed_set) <= set(shipped):
            raise ValueError(
                "a review only carries onto a publication that shipped every locale it "
                f"was taken under: reviewed {reviewed_set}, shipped {shipped}"
            )
        # An equivalence proof stands in for the byte re-prove, so it has to be *about*
        # this record's review and this record's bytes — otherwise it is a receipt for
        # some other page pasted onto this one.
        proof = self.reviewed_equivalence
        if proof is not None:
            if reviewed_set == shipped:
                raise ValueError(
                    "a publication shipping exactly the reviewed locale set must carry "
                    "the reviewed bytes themselves, not an equivalence proof"
                )
            if proof.reviewed_locale != self.review.locale:
                raise ValueError("the equivalence proof names a different reviewed locale")
            if proof.signed_page_hash != self.review.page_hash:
                raise ValueError("the equivalence proof names different human-reviewed bytes")
            if proof.candidate_page_hash == proof.signed_page_hash:
                raise ValueError(
                    "bytes that reproduce the signed page exactly need no equivalence proof"
                )
        unsupported_share_locales = sorted(
            {asset.locale for asset in self.share_assets} - set(locale_map)
        )
        if unsupported_share_locales:
            raise ValueError(
                f"share assets use unsupported locales: {unsupported_share_locales}"
            )
        share_keys = [(asset.locale, asset.question_id) for asset in self.share_assets]
        if len(share_keys) != len(set(share_keys)):
            raise ValueError("share_assets repeats a locale/question pair")
        for asset in self.share_assets:
            page_url = locale_map[asset.locale].page_url
            if asset.url is not None and not asset.url.startswith(
                f"{page_url}share/angle-{asset.question_id}."
            ):
                raise ValueError(
                    f"share asset {asset.question_id} does not belong to its locale page"
                )
            if asset.landing_url != f"{page_url}share/angle-{asset.question_id}.html":
                raise ValueError(
                    f"share landing {asset.question_id} does not belong to its locale page"
                )
        if self.share_assets:
            question_sets = {
                locale: {
                    asset.question_id
                    for asset in self.share_assets
                    if asset.locale == locale
                }
                for locale in locale_map
            }
            if any(not questions for questions in question_sets.values()):
                raise ValueError("share_assets must cover every publication locale")
            if len({frozenset(questions) for questions in question_sets.values()}) != 1:
                raise ValueError("share_assets must cover the same angles in every locale")
        theme_fields = (
            self.theme_token,
            self.theme_registry_version,
            self.theme_registry_fingerprint,
        )
        if any(value is not None for value in theme_fields) and not all(
            value is not None for value in theme_fields
        ):
            raise ValueError(
                "theme token, registry version and registry fingerprint must appear together"
            )
        bad_render_inputs = {}
        for key, digest in self.render_input_hashes.items():
            path = PurePosixPath(key)
            # Keys must be normalized relative paths so two spellings ("x.json",
            # "./x.json") can never name the same archived file in one pinned map.
            if (
                not key
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in key
                or not path.parts
                or key != path.as_posix()
                or not re.fullmatch(HASH_RE, digest)
            ):
                bad_render_inputs[key] = digest
        if bad_render_inputs:
            raise ValueError(
                f"render_input_hashes contains invalid paths or hashes: {bad_render_inputs}"
            )
        if (self.submission_id is None) != (self.submission_archive_hash is None):
            raise ValueError("submission_id and submission_archive_hash must appear together")
        if self.submission_id is not None and self.audit_run_id is None:
            raise ValueError("an external submission publication must pin its audit_run_id")
        worker_runs = {run_id for worker in self.workers for run_id in worker.run_ids}
        model_runs = {pin.run_id for pin in self.run_closure}
        if not worker_runs <= model_runs:
            raise ValueError("worker attribution names a run outside run_closure")
        if not self.provenance.deterministic:
            raise ValueError("publish is deterministic; PublicationRecord model_id must be null")
        if self.prepared_at < self.review.decided_at:
            raise ValueError("publication cannot be prepared before its human review")
        return self


class PublicationEvent(Record):
    """One append-only lifecycle transition for an immutable publication."""

    event_id: str = Field(pattern=PUBLICATION_EVENT_ID_RE)
    event_type: PublicationEventType
    publication_id: str = Field(pattern=PUBLICATION_ID_RE)
    publication_hash: str = Field(pattern=HASH_RE)
    replacement_publication_id: Optional[str] = Field(default=None, pattern=PUBLICATION_ID_RE)
    replacement_publication_hash: Optional[str] = Field(default=None, pattern=HASH_RE)
    reason: Optional[LangText] = None
    approval: HumanApproval
    occurred_at: datetime
    previous_event_hash: Optional[str] = Field(default=None, pattern=HASH_RE)
    provenance: Provenance

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _shape(self) -> "PublicationEvent":
        is_supersede = self.event_type == PublicationEventType.SUPERSEDE
        has_replacement = self.replacement_publication_id is not None
        if is_supersede != has_replacement:
            raise ValueError("only supersede events require a replacement publication")
        if has_replacement != (self.replacement_publication_hash is not None):
            raise ValueError("replacement id and hash must appear together")
        if self.replacement_publication_id == self.publication_id:
            raise ValueError("a publication cannot supersede itself")
        if self.event_type in {
            PublicationEventType.WITHDRAW,
            PublicationEventType.RESTORE,
            PublicationEventType.AUDIT_DELETE,
            PublicationEventType.SUPERSEDE,
        } and self.reason is None:
            raise ValueError(f"{self.event_type.value} requires a reason")
        if not self.provenance.deterministic:
            raise ValueError("publication lifecycle changes are deterministic; model_id must be null")
        if self.occurred_at < self.approval.decided_at:
            raise ValueError("event cannot occur before its human approval")
        return self


class PublicationEventLog(Record):
    """A validated hash chain of publication lifecycle events."""

    events: list[PublicationEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def _chain(self) -> "PublicationEventLog":
        ids = [event.event_id for event in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate publication event_id")
        previous: Optional[PublicationEvent] = None
        for event in self.events:
            expected = None if previous is None else content_digest(previous.model_dump(mode="json"))
            if event.previous_event_hash != expected:
                raise ValueError(
                    f"{event.event_id}: previous_event_hash does not match the prior event"
                )
            # The event time is the only publication time, so the chain must not be
            # backdatable: a restore stamped before the withdrawal it reverses would
            # derive an impossible published_at.
            if previous is not None and event.occurred_at < previous.occurred_at:
                raise ValueError(
                    f"{event.event_id}: occurred_at precedes the prior event in the chain"
                )
            previous = event
        return self


class CatalogSide(Record):
    group_id: str = Field(pattern=r"^[a-z]{2,5}$")
    short_label: LangText
    definition: LangText


class CatalogAngle(Record):
    question_id: str
    question: LangText
    finding_kind: FindingKind
    answers: dict[str, Optional[LangText]]
    counts: dict[str, str] = Field(default_factory=dict)
    strength: Optional[FindingStrength] = None
    stability: Optional[float] = Field(default=None, ge=0, le=1)
    fragment_url: str
    share_card_url: Optional[str] = None
    share_url: Optional[str] = None

    @field_validator("question_id")
    @classmethod
    def _question_id(cls, value: str) -> str:
        parse_prefixed_id(value, "QST")
        return value

    @field_validator("fragment_url")
    @classmethod
    def _fragment(cls, value: str) -> str:
        value = _site_url(value)
        if "#" not in value:
            raise ValueError("catalog angle URL must deep-link to a page fragment")
        return value

    @field_validator("share_card_url")
    @classmethod
    def _share_card(cls, value: Optional[str]) -> Optional[str]:
        return _site_url(value) if value is not None else None

    @field_validator("share_url")
    @classmethod
    def _share_url(cls, value: Optional[str]) -> Optional[str]:
        return _site_url(value) if value is not None else None


class CatalogRecord(Record):
    """One locale's rebuildable home/search row derived from a publication."""

    publication_id: str = Field(pattern=PUBLICATION_ID_RE)
    publication_hash: str = Field(pattern=HASH_RE)
    public_bundle_fingerprint: str = Field(pattern=HASH_RE)
    topic_id: str
    locale: str
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    page_url: str
    title: LangText
    brief: LangText
    sides: list[CatalogSide] = Field(min_length=2, max_length=2)
    scope_start: date
    scope_end: date
    published_at: datetime
    category_ids: list[str] = Field(min_length=1)
    source_languages: list[str] = Field(min_length=1)
    reader_locales: list[str] = Field(min_length=1)
    #: How many **readable independent reports** the whole comparison rests on — the
    #: site's one counting universe (``newsab_schema.readability``), the same one every
    #: badge denominator and the topic page's timeline are drawn from.  A per-answer
    #: badge counts only the reports that addressed that question, so no badge states the
    #: size of the corpus; a home card that wants to say it has to be told.  It counted
    #: raw articles in earlier producers, which put a number on the home card that
    #: nothing on the topic page it linked to could reproduce.
    report_count: int = Field(ge=1)
    #: A comparison needs at least **two** angles to be one: with a single card the page
    #: is a claim, not a comparison.  The floor was 3 until aabb-museum-metal-2026
    #: landed 2 supported/weak findings out of 12 and the rule became that a thin but
    #: honest page ships rather than padding the storyline with
    #: unsupported findings — the evidence bar in ``page-authoring.md`` outranks the count.
    angles: list[CatalogAngle] = Field(min_length=2, max_length=6)
    sponsor: SponsorAttribution
    workers: list[WorkerAttribution] = Field(min_length=1)
    share_card_url: Optional[str] = None
    theme_accent: Optional[str] = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,31}$")
    curation_refs: list[str] = Field(default_factory=list)
    popularity_snapshot_id: Optional[str] = Field(default=None, min_length=1)
    catalog_version: str = Field(pattern=r"^catalog-\d+\.\d+\.\d+$")

    @field_validator("topic_id")
    @classmethod
    def _topic(cls, value: str) -> str:
        return validate_topic_id(value)

    @field_validator("locale")
    @classmethod
    def _locale(cls, value: str) -> str:
        return normalize_lang(value)

    @field_validator("page_url")
    @classmethod
    def _page_url(cls, value: str) -> str:
        return _site_url(value)

    @field_validator("share_card_url")
    @classmethod
    def _share_url(cls, value: Optional[str]) -> Optional[str]:
        return _site_url(value) if value is not None else None

    @field_validator("published_at")
    @classmethod
    def _published_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("category_ids")
    @classmethod
    def _categories(cls, values: list[str]) -> list[str]:
        if any(not value or value.strip() != value for value in values):
            raise ValueError("category_ids must be non-blank canonical ids")
        if len(values) != len(set(values)):
            raise ValueError("category_ids must not contain duplicates")
        return values

    @field_validator("source_languages", "reader_locales")
    @classmethod
    def _languages(cls, values: list[str]) -> list[str]:
        normalized = [normalize_lang(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("language lists must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def _localized_derived_row(self) -> "CatalogRecord":
        if not _publication_belongs(self.publication_id, self.topic_id):
            raise ValueError("catalog publication_id belongs to another topic")
        if self.scope_start > self.scope_end:
            raise ValueError("scope_start must not be after scope_end")
        if self.locale not in self.reader_locales:
            raise ValueError("catalog locale is absent from reader_locales")
        texts = [self.title, self.brief]
        texts += [side.short_label for side in self.sides]
        texts += [side.definition for side in self.sides]
        texts += [angle.question for angle in self.angles]
        texts += [answer for angle in self.angles for answer in angle.answers.values() if answer]
        wrong = sorted({text.lang for text in texts if text.lang != self.locale})
        if wrong:
            raise ValueError(f"catalog row mixes reader languages: {wrong}")
        groups = {side.group_id for side in self.sides}
        if len(groups) != 2:
            raise ValueError("catalog sides must have two distinct group_ids")
        for angle in self.angles:
            if set(angle.answers) != groups:
                raise ValueError(
                    f"{angle.question_id}: answer sides do not match catalog sides"
                )
            if angle.counts and set(angle.counts) != groups:
                raise ValueError(
                    f"{angle.question_id}: count sides do not match catalog sides"
                )
            for count in angle.counts.values():
                if not re.fullmatch(r"\d+/\d+", count):
                    raise ValueError(
                        f"{angle.question_id}: counts must use numerator/denominator"
                    )
                numerator, denominator = (int(part) for part in count.split("/"))
                if denominator < 1 or numerator > denominator:
                    raise ValueError(
                        f"{angle.question_id}: count {count} is not a recomputable "
                        "fraction of reporting clusters"
                    )
            if not angle.fragment_url.startswith(f"{self.page_url}#"):
                raise ValueError(
                    f"{angle.question_id}: fragment URL does not belong to page_url"
                )
            if angle.share_card_url is not None and not angle.share_card_url.startswith(
                f"{self.page_url}share/angle-{angle.question_id}."
            ):
                raise ValueError(
                    f"{angle.question_id}: share card does not belong to its page/angle"
                )
            if angle.share_url is not None and angle.share_url != (
                f"{self.page_url}share/angle-{angle.question_id}.html"
            ):
                raise ValueError(
                    f"{angle.question_id}: share landing does not belong to its page/angle"
                )
        if self.share_card_url is not None and self.share_card_url != self.angles[0].share_card_url:
            raise ValueError("catalog share_card_url must be the first angle's derived card")
        question_ids = [angle.question_id for angle in self.angles]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("catalog repeats an angle question")
        legacy_kinds = sorted(
            {
                angle.finding_kind.value
                for angle in self.angles
                if angle.finding_kind
                not in {
                    FindingKind.CONSENSUS,
                    FindingKind.DIVERGENCE,
                    FindingKind.ATTENTION_GAP,
                }
            }
        )
        if legacy_kinds:
            raise ValueError(f"catalog cannot publish legacy finding kinds: {legacy_kinds}")
        if len(self.curation_refs) != len(set(self.curation_refs)):
            raise ValueError("curation_refs must not contain duplicates")
        return self


class PublishSelector(Record):
    """Atomic, rebuildable cache of the one live publication per topic."""

    publications: dict[str, str] = Field(default_factory=dict)
    event_count: int = Field(ge=0)
    event_log_hash: str = Field(pattern=HASH_RE)

    @field_validator("publications")
    @classmethod
    def _mapping(cls, value: dict[str, str]) -> dict[str, str]:
        for topic_id, publication_id in value.items():
            validate_topic_id(topic_id)
            import re

            if not re.fullmatch(PUBLICATION_ID_RE, publication_id):
                raise ValueError(f"invalid publication id for {topic_id}: {publication_id}")
            if not _publication_belongs(publication_id, topic_id):
                raise ValueError(f"publication {publication_id} belongs to another topic")
        return value
