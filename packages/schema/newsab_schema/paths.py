"""The on-disk topic directory (§3.3 S10) as a typed object.

Every stage and every script resolves artifact locations through :class:`TopicPaths` so
the layout is defined once.  Full scraped text lives in the append-only article store
``corpus/articles/`` and **never leaves the machine** (D14); a corpus run stores which
members of that store it saw, not a copy of them (R-2).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .ids import validate_topic_id

#: Paths that must never appear in a published page bundle or any public tree (D14,
#: §1.3(2)).  Staging files contain the same full text as article records.  The gold
#: worksheet embeds every sentence of each sampled article so the user can copy
#: anchors without typing; it is private for the same reason even though the gold labels
#: themselves are publishable.  One deliberate carve-out: a submission archive carries
#: the pinned article store as its source snapshots —
#: that archive travels only over the private upload channel, never through public Git,
#: and the staging buffer and gold worksheet stay out of it too.
PRIVATE_SUBPATHS: tuple[str, ...] = (
    "corpus/articles",
    "corpus/staging",
    "gold/worksheet.json",
)

#: Where the cross-topic outlet registry lives, relative to the repo root (R-3).  It is
#: global on purpose: collection knowledge and source classification outlive any one topic.
SOURCE_REGISTRY_SUBPATH = "sources/registry.yaml"

#: The site tree is a build/audit input, not a directory to copy wholesale.  Only these
#: subtrees contain records whose schemas are intentionally public-safe.  Event reasons,
#: selectors and future operational records remain internal even when they carry no full
#: article text; secrets, submissions and audit corpora are private.
SITE_PUBLIC_SUBPATHS: tuple[str, ...] = ("publications", "catalog")
SITE_PRIVATE_SUBPATHS: tuple[str, ...] = ("private", "submissions", "audit")

STAGE_NAMES: tuple[str, ...] = (
    "corpus",
    "observations",
    "ontology",
    "questions",
    "answers",
    "normalization",
    "angles",
    "cards",
    "editorial",
)


@dataclass(frozen=True)
class TopicPaths:
    """Resolved artifact paths for one topic."""

    root: Path
    topic_id: str

    @classmethod
    def for_topic(cls, topics_root: str | Path, topic_id: str) -> "TopicPaths":
        validate_topic_id(topic_id)
        return cls(root=Path(topics_root) / topic_id, topic_id=topic_id)

    # -- S0 ----------------------------------------------------------------------------
    @property
    def topic_manifest(self) -> Path:
        return self.root / "topic_manifest.yaml"

    # -- S2 ----------------------------------------------------------------------------
    @property
    def corpus_dir(self) -> Path:
        return self.root / "corpus"

    @property
    def corpus_index(self) -> Path:
        """Public-safe article index: metadata and cluster assignment, no body text."""
        run_id = self.active_run_id("corpus")
        return (
            self.stage_run_dir("corpus", run_id) / "index.jsonl"
            if run_id
            else self.corpus_dir / "index.jsonl"
        )

    @property
    def articles_dir(self) -> Path:
        """The append-only article store: every article ever ingested for this topic.

        One directory, not one per run (R-2).  A run records *which* members it saw; the
        store itself only grows, so adding an article costs one file and leaves every
        existing sentence anchor untouched.  PRIVATE (D14).
        """
        return self.corpus_dir / "articles"

    @property
    def superseded_articles_dir(self) -> Path:
        """Prior bytes of any article that was re-collected with different content.

        Kept so a run that pinned the old content hash stays restorable — which is what
        "records are immutable" means once the store is append-only.  PRIVATE (D14).
        """
        return self.articles_dir / "_superseded"

    @property
    def withdrawn_articles(self) -> Path:
        """Articles held in the store but excluded from new runs, with reasons (R-2)."""
        return self.corpus_dir / "withdrawn.jsonl"

    def corpus_run_file(self, run_id: str | None = None) -> Path:
        """The set snapshot one build produced (:class:`CorpusRun`)."""
        return self.stage_run_dir("corpus", run_id or self.active_run_id("corpus")) / "corpus_run.json"

    def article_file(self, article_id: str) -> Path:
        return self.articles_dir / f"{article_id}.json"

    @property
    def collection_log(self) -> Path:
        """Retrieval failures and blocked sources — recorded, never omitted (§3.3 S2)."""
        return self.corpus_dir / "collection_log.jsonl"

    @property
    def staging_dir(self) -> Path:
        """Fetched pages awaiting a build, one YAML each.  PRIVATE (D14)."""
        return self.corpus_dir / "staging"

    @property
    def topics_raised(self) -> Path:
        """The collect agent's reading notes: a few phrases each article actually raises.

        Never evidence — nothing on the page is ever anchored to one of them, and no
        finding may rest on one.  They *are* displayable as what a report is about
        the reader page shows them as an article's keywords and, on the
        ``topics_raised`` cloud, as what each side's coverage talks about.  Each phrase
        is a short verbatim fragment of the article plus our English pivot for it, so
        showing them ships nothing D14 or non-negotiable 7 withholds.
        """
        return self.corpus_dir / "topics_raised.jsonl"

    # -- S3 / S4 -----------------------------------------------------------------------
    @property
    def hypotheses(self) -> Path:
        return self.root / "hypotheses.jsonl"

    @property
    def observations_dir(self) -> Path:
        return self.root / "observations"

    @property
    def observations(self) -> Path:
        run_id = self.active_run_id("observations")
        return (
            self.stage_run_dir("observations", run_id) / "observations.jsonl"
            if run_id
            else self.observations_dir / "observations.jsonl"
        )

    @property
    def article_annotations(self) -> Path:
        run_id = self.active_run_id("observations")
        return (
            self.stage_run_dir("observations", run_id) / "article_annotations.jsonl"
            if run_id
            else self.observations_dir / "article_annotations.jsonl"
        )

    @property
    def ontology_dir(self) -> Path:
        return self.root / "ontology"

    @property
    def concepts(self) -> Path:
        run_id = self.active_run_id("ontology")
        return (
            self.stage_run_dir("ontology", run_id) / "concepts.yaml"
            if run_id
            else self.ontology_dir / "concepts.yaml"
        )

    # -- Q×A annotate (value_chain stage 3) ---------------------------------------------
    @property
    def questions_dir(self) -> Path:
        return self.root / "questions"

    @property
    def questions(self) -> Path:
        """The active versioned question set (``QuestionSet`` as YAML)."""
        run_id = self.active_run_id("questions")
        return (
            self.stage_run_dir("questions", run_id) / "questions.yaml"
            if run_id
            else self.questions_dir / "questions.yaml"
        )

    @property
    def answers_dir(self) -> Path:
        return self.root / "answers"

    @property
    def answers(self) -> Path:
        """The active per-cluster-per-question answers (``ClusterAnswer`` JSONL)."""
        run_id = self.active_run_id("answers")
        return (
            self.stage_run_dir("answers", run_id) / "answers.jsonl"
            if run_id
            else self.answers_dir / "answers.jsonl"
        )

    # -- Q×A normalize (value_chain stage 3.5, analyze refactor D-c) ---------------------
    @property
    def normalization_dir(self) -> Path:
        return self.root / "normalization"

    @property
    def category_map(self) -> Path:
        """The active versioned category map (``CategoryMap`` as JSON)."""
        run_id = self.active_run_id("normalization")
        return (
            self.stage_run_dir("normalization", run_id) / "category_map.json"
            if run_id
            else self.normalization_dir / "category_map.json"
        )

    # -- A1 ----------------------------------------------------------------------------
    @property
    def analysis_dir(self) -> Path:
        return self.root / "analysis"

    def a1_run_dir(self, a1_run_id: str) -> Path:
        return self.analysis_dir / a1_run_id

    # -- S6 ----------------------------------------------------------------------------
    @property
    def angles_dir(self) -> Path:
        return self.root / "angles"
    @property
    def candidate_angles(self) -> Path:
        run_id = self.active_run_id("angles")
        return (
            self.stage_run_dir("angles", run_id) / "candidate_angles.jsonl"
            if run_id
            else self.angles_dir / "candidate_angles.jsonl"
        )

    @property
    def constraint_report(self) -> Path:
        run_id = self.active_run_id("angles")
        return (
            self.stage_run_dir("angles", run_id) / "constraint_report.json"
            if run_id
            else self.angles_dir / "constraint_report.json"
        )

    # -- S5 -----------------------------------------------------------------------------
    @property
    def cards_dir(self) -> Path:
        return self.root / "cards"

    @property
    def angle_cards(self) -> Path:
        run_id = self.active_run_id("cards")
        return (
            self.stage_run_dir("cards", run_id) / "angle_cards.jsonl"
            if run_id
            else self.cards_dir / "angle_cards.jsonl"
        )

    # -- S7 -----------------------------------------------------------------------------
    @property
    def editorial_dir(self) -> Path:
        return self.root / "editorial"

    @property
    def claims(self) -> Path:
        run_id = self.active_run_id("editorial")
        return (
            self.stage_run_dir("editorial", run_id) / "claims.jsonl"
            if run_id
            else self.editorial_dir / "claims.jsonl"
        )

    @property
    def editorial_page(self) -> Path:
        run_id = self.active_run_id("editorial")
        return (
            self.stage_run_dir("editorial", run_id) / "page.json"
            if run_id
            else self.editorial_dir / "page.json"
        )

    # -- G2 / S8 / eval ------------------------------------------------------------------
    @property
    def dossier_dir(self) -> Path:
        return self.root / "dossier"

    @property
    def qa_dir(self) -> Path:
        return self.root / "qa"

    @property
    def gold_dir(self) -> Path:
        return self.root / "gold"

    @property
    def gold_standard(self) -> Path:
        return self.gold_dir / "gold_standard.yaml"

    @property
    def gold_worksheet(self) -> Path:
        """Sentence-by-sentence annotation worksheet. PRIVATE because it contains full text."""
        return self.gold_dir / "worksheet.json"

    # -- manifest ----------------------------------------------------------------------
    @property
    def manifest_dir(self) -> Path:
        return self.root / "manifest"

    @property
    def manifest(self) -> Path:
        return self.manifest_dir / "manifest.jsonl"

    @property
    def corrections(self) -> Path:
        return self.manifest_dir / "corrections.jsonl"

    @property
    def active_versions(self) -> Path:
        return self.manifest_dir / "active.json"

    def active_run_id(self, stage: str) -> str | None:
        """Selected immutable run, or ``None`` for a legacy topic."""
        if stage not in STAGE_NAMES:
            raise ValueError(f"unknown versioned stage {stage!r}; expected one of {STAGE_NAMES}")
        if not self.active_versions.exists():
            return None
        try:
            payload = json.loads(self.active_versions.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"invalid active selector {self.active_versions}: {exc}") from exc
        value = payload.get(stage)
        return str(value) if value is not None else None

    def stage_versions_dir(self, stage: str) -> Path:
        if stage not in STAGE_NAMES:
            raise ValueError(f"unknown versioned stage {stage!r}; expected one of {STAGE_NAMES}")
        base = {
            "corpus": self.corpus_dir,
            "observations": self.observations_dir,
            "ontology": self.ontology_dir,
            "questions": self.questions_dir,
            "answers": self.answers_dir,
            "normalization": self.normalization_dir,
            "angles": self.angles_dir,
            "cards": self.cards_dir,
            "editorial": self.editorial_dir,
        }[stage]
        return base / "versions"

    def stage_run_dir(self, stage: str, run_id: str | None) -> Path:
        if not run_id:
            raise ValueError(f"run_id is required for stage {stage}")
        from .ids import validate_run_id

        return self.stage_versions_dir(stage) / validate_run_id(run_id)

    def activate(self, stage: str, run_id: str) -> None:
        """Atomically update the mutable selector after manifest commit."""
        run_dir = self.stage_run_dir(stage, run_id)
        if not run_dir.is_dir():
            raise ValueError(f"cannot activate missing run directory: {run_dir}")
        payload: dict[str, str] = {}
        if self.active_versions.exists():
            payload = json.loads(self.active_versions.read_text(encoding="utf-8"))
        payload[stage] = run_id
        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_dir / f".active-{os.getpid()}.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.active_versions)

    def deactivate(self, stage: str) -> str | None:
        """Atomically remove a stage from the mutable selector.

        Deactivation retires only the routing pointer.  The immutable run directory and
        its manifest entry remain untouched, so historical runs stay restorable (R-2).
        Returns the run id that was active, or ``None`` when the stage was already
        inactive.
        """
        if stage not in STAGE_NAMES:
            raise ValueError(f"unknown versioned stage {stage!r}; expected one of {STAGE_NAMES}")
        if not self.active_versions.exists():
            return None
        try:
            payload = json.loads(self.active_versions.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"invalid active selector {self.active_versions}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"invalid active selector {self.active_versions}: top level is not an object")
        previous = payload.pop(stage, None)
        if previous is None:
            return None
        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_dir / f".active-{os.getpid()}.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.active_versions)
        return str(previous)

    # -- helpers -----------------------------------------------------------------------
    def ensure(self) -> "TopicPaths":
        """Create the directory skeleton the current value chain writes to.

        Safe to call repeatedly.  ``STAGE_NAMES`` still names the retired S0–S8 stages
        because Phase-0 run records cite them, but scaffolding their directories left
        every new topic with seven dirs an eight-stage run never touches
        (``observations``, ``ontology``, ``angles``, ``cards``, ``dossier``, ``qa``,
        ``gold``) — a map of a road not taken.  Their accessors remain for reading the
        old topics that do use them.
        """
        for d in (
            self.corpus_dir,
            self.articles_dir,
            self.superseded_articles_dir,
            self.questions_dir,
            self.answers_dir,
            self.normalization_dir,
            self.analysis_dir,
            self.editorial_dir,
            self.manifest_dir,
            *(
                self.stage_versions_dir(stage)
                for stage in ("corpus", "questions", "answers", "normalization", "editorial")
            ),
        ):
            d.mkdir(parents=True, exist_ok=True)
        return self

    def private_paths(self) -> list[Path]:
        return [self.root / sub for sub in PRIVATE_SUBPATHS]

    def is_private(self, path: str | Path) -> bool:
        """True when ``path`` is inside a directory that must not be published (D14)."""
        resolved = Path(path).resolve()
        try:
            relative = resolved.relative_to(self.root.resolve())
            # Pre-R-2 corpora kept a copy of every article inside each run directory.
            # Those copies are gone from new builds but stay private wherever they survive.
            if (
                len(relative.parts) >= 4
                and relative.parts[0] == "corpus"
                and relative.parts[1] == "versions"
                and relative.parts[3] == "articles"
            ):
                return True
        except ValueError:
            pass
        for private in self.private_paths():
            try:
                resolved.relative_to(private.resolve())
                return True
            except ValueError:
                continue
        return False


def source_registry_path(topics_root: str | Path) -> Path:
    """Locate ``sources/registry.yaml`` (R-3).

    Resolution order: ``$NEWSAB_SOURCE_REGISTRY``, then ``<topics_root>/../sources/``.
    The registry is a sibling of ``topics/`` rather than a child of one topic because it
    spans topics — a channel learned while collecting nickel coverage is the same channel
    the next topic needs.
    """
    override = os.environ.get("NEWSAB_SOURCE_REGISTRY")
    if override:
        return Path(override)
    return Path(topics_root).resolve().parent / SOURCE_REGISTRY_SUBPATH


@dataclass(frozen=True)
class SitePaths:
    """The cross-topic artifact root used by stage 8.

    It is deliberately separate from :class:`TopicPaths`: topic active pointers select
    work-in-progress runs, while this root stores reviewed release candidates, their
    lifecycle event stream and rebuildable production indexes.
    """

    root: Path

    @classmethod
    def at(cls, site_root: str | Path) -> "SitePaths":
        return cls(Path(site_root))

    @property
    def publications_dir(self) -> Path:
        return self.root / "publications"

    def publication_dir(self, publication_id: str) -> Path:
        from .models.publication import PUBLICATION_ID_RE

        import re

        if not re.fullmatch(PUBLICATION_ID_RE, publication_id):
            raise ValueError(f"invalid publication_id: {publication_id!r}")
        return self.publications_dir / publication_id

    def publication_record(self, publication_id: str) -> Path:
        return self.publication_dir(publication_id) / "publication.json"

    @property
    def imported_submissions_dir(self) -> Path:
        """Where the operator's intake put each verified submission's own namespace.

        The site knows this path because a publication may *come from* a submission: its
        topic tree lives here rather than under the repo's ``topics/``, and every rebuild
        has to find it from the record alone.
        """
        return self.root / "submissions" / "imported"

    def imported_submission_dir(self, submission_id: str) -> Path:
        import re

        if not re.fullmatch(r"SUB-[0-9a-f]{16}", submission_id):
            raise ValueError(f"invalid submission_id: {submission_id!r}")
        return self.imported_submissions_dir / submission_id

    @property
    def events_dir(self) -> Path:
        return self.root / "events"

    @property
    def publication_events(self) -> Path:
        return self.events_dir / "publication_events.jsonl"

    @property
    def catalog_dir(self) -> Path:
        return self.root / "catalog"

    def catalog(self, locale: str) -> Path:
        from .common import normalize_lang

        return self.catalog_dir / f"{normalize_lang(locale)}.jsonl"

    @property
    def production_dir(self) -> Path:
        return self.root / "production"

    @property
    def production_selector(self) -> Path:
        return self.production_dir / "selector.json"

    @property
    def curation_dir(self) -> Path:
        """Reserved site-level root; its record shape is intentionally deferred."""
        return self.root / "curation"

    @property
    def private_dir(self) -> Path:
        return self.root / "private"

    @property
    def submissions_dir(self) -> Path:
        return self.root / "submissions"

    @property
    def audit_dir(self) -> Path:
        return self.root / "audit"

    def ensure(self) -> "SitePaths":
        for directory in (
            self.publications_dir,
            self.events_dir,
            self.catalog_dir,
            self.production_dir,
            self.curation_dir,
            self.private_dir,
            self.submissions_dir,
            self.audit_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def visibility(self, path: str | Path) -> str:
        """Return ``public_source``, ``internal`` or ``private`` for a site path.

        ``public_source`` means the record is safe for a bundle builder to read; it does
        not authorize copying the source tree.  Production output is always assembled
        from a closed output list and rechecked independently.
        """
        resolved = Path(path).resolve()
        try:
            relative = resolved.relative_to(self.root.resolve())
        except ValueError:
            raise ValueError(f"path is outside site root: {resolved}")
        if relative.parts and relative.parts[0] in SITE_PRIVATE_SUBPATHS:
            return "private"
        if relative.parts and relative.parts[0] in SITE_PUBLIC_SUBPATHS:
            return "public_source"
        return "internal"

    def is_private(self, path: str | Path) -> bool:
        return self.visibility(path) == "private"

    def is_public_source(self, path: str | Path) -> bool:
        return self.visibility(path) == "public_source"
