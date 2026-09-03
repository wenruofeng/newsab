"""All record types, re-exported.  Import from here, not from the submodules."""

from .analysis import (
    AngleMetrics,
    BlindSpotCheck,
    BlindSpotCondition,
    CandidateAngle,
    Claim,
    Comparison,
    DeltaInterval,
    Editorial,
    EScore,
    Feature,
    GroupComparison,
    GroupMetric,
    QuantifierCheck,
    ResamplingSpec,
    RGate,
    ScalarMetric,
    Selection,
    SupportCount,
)
from .annotation import (
    ArticleAnnotation,
    Concept,
    ConceptOntology,
    ConceptSurface,
    MergedBy,
    NotableLanguage,
    Observation,
    OverallStance,
)
from .editorial import (
    AngleCard,
    AngleSection,
    EditorialPage,
    NotablePhrase,
    PageNote,
)
from .corpus import (
    BACKFILL_RETRY_BUDGET,
    AngleHypothesis,
    Article,
    BackfillDebt,
    Contributor,
    CorpusRun,
    Group,
    LocalEdits,
    Origin,
    Paragraph,
    Period,
    QuestionSeed,
    RunArticle,
    ScopeApproval,
    Sentence,
    SourceChannel,
    SourceEntry,
    SourceRegistry,
    TopicManifest,
    WithdrawnArticle,
    article_content_hash,
    compute_set_hash,
)
from .category_map import (
    CategoryMap,
    CategoryMerge,
)
from .findings import (
    FindingDelta,
    GroupAnswerStats,
    QAFinding,
)
from .page import (
    AngleBlock,
    CountBadge,
    HowWeCounted,
    PageClaim,
    Quote,
    ReaderPage,
    SideAnswerBlock,
    Visual,
)
from .qa import (
    ANSWER_CATEGORY_UNCLEAR,
    ClusterAnswer,
    Question,
    QuestionSet,
    validate_answer_category,
)
from .gold import (
    Annotator,
    GoldAngleScore,
    GoldObservation,
    GoldStandardSet,
    HumanAngleScore,
)
from .manifest import (
    ArtifactReference,
    CorrectionMapping,
    Escalation,
    ManifestEntry,
    TopicManifestLog,
    content_digest,
    file_digest,
)
from .publication import (
    CatalogAngle,
    CatalogRecord,
    CatalogSide,
    HumanApproval,
    LocaleBundle,
    LocalePlan,
    PublicationEvent,
    PublicationEventLog,
    PublicationRecord,
    PublicationReview,
    PublishSelector,
    ShareAsset,
    SponsorAttribution,
    TopicRunPin,
    WorkerAttribution,
)

#: Which blueprint section defines each schema, and whether it is settled or still draft
#: (§4.6).  The exporter writes this into the generated JSON Schema descriptions so a
#: contributor can see at a glance which shapes are safe to build against.
SCHEMA_STATUS: dict[str, tuple[str, str]] = {
    "Question": ("value_chain.md Q×A model / V-1", "settled"),
    "QuestionSet": ("value_chain.md Q×A model / V-1", "settled"),
    "ClusterAnswer": ("value_chain.md Q×A model / V-1", "settled"),
    "CategoryMap": ("value_chain.md stage 3.5 / analyze refactor D-c", "settled"),
    "QAFinding": ("value_chain.md stage 4 / V-3", "settled"),
    "ReaderPage": ("value_chain.md The product", "draft"),
    "Observation": ("§4.2", "settled"),
    "ArticleAnnotation": ("§4.2.3", "settled"),
    "Concept": ("§4.3", "settled"),
    "ConceptOntology": ("§4.3", "settled"),
    "CandidateAngle": ("§4.4", "settled"),
    "Claim": ("§4.5", "settled"),
    "AngleCard": ("§2.4 / §3.3 S5 / §4.6", "draft"),
    "AngleSection": ("§2.4 / §3.3 S7 / §4.6", "draft"),
    "EditorialPage": ("§2.4 / §3.3 S7 / §4.6", "draft"),
    "TopicManifest": ("§3.3 S0 / §4.6", "draft"),
    "SourceEntry": ("§1.5 / §3.3 S1 / §4.6", "draft"),
    "SourceRegistry": ("§3.3 S1 / §4.6", "draft"),
    "Article": ("§3.3 S2 / §4.6", "draft"),
    "CorpusRun": ("§3.2 / §3.3 S2 / §4.6", "draft"),
    "AngleHypothesis": ("§3.3 S3", "draft"),
    "GoldStandardSet": ("⑤ / §4.6", "draft"),
    "ManifestEntry": ("§3.2 / §4.6", "draft"),
    "CorrectionMapping": ("§3.2 / §4.6", "draft"),
    "PublicationRecord": ("value_chain.md stage 8", "settled"),
    "PublicationEvent": ("value_chain.md stage 8", "settled"),
    "CatalogRecord": ("value_chain.md stage 8", "settled"),
    "PublishSelector": ("artifact_versioning.md site-level artifacts", "settled"),
    "LocalePlan": ("value_chain.md stage 8", "settled"),
}

__all__ = [name for name in dir() if name[0].isupper()] + [
    "ANSWER_CATEGORY_UNCLEAR",
    "SCHEMA_STATUS",
    "article_content_hash",
    "compute_set_hash",
    "content_digest",
    "file_digest",
    "validate_answer_category",
]
