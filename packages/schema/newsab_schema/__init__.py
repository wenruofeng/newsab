"""``newsab_schema`` — the single machine-checkable definition of the project's data.

Blueprint ④ describes five schemas (observation, article annotation, concept ontology,
candidate angle, claim); this package makes them executable, together with the corpus-side
records they depend on, the controlled vocabularies (§4.1), the sentence-ID grammar, the
lint lexicons, and the §4.2.2 / §4.4.1 invariant checkers.

Everything else in the repo — every skill script, the A1 statistics package, and one day
the frontend — reads its definitions from here or from the generated ``dist/`` copies.
There is deliberately no second place to define an enum value.

Quick start::

    from newsab_schema import Observation, TopicPaths, validate_observations
    from newsab_schema.io import load_articles, read_jsonl

    paths = TopicPaths.for_topic("topics", "aabb-river-light-2026")
    report = validate_observations(
        read_jsonl(paths.observations, Observation), load_articles(paths.articles_dir)
    )
    raise SystemExit(report.exit_code())
"""

from __future__ import annotations

__version__ = "0.6.0"

from . import enums, ids, lints, paths
from .common import GateRecord, LangText, MultiLangText, Provenance, Record
from .i18n_merge import assert_matching_shape, merge_lang_leaf
from .locales import (
    EXTRA_HALO_LOCALES,
    HALO_LOCALE_CODES,
    HALO_LOCALES,
    HaloLocale,
    direction,
    halo_locale,
)
from .enums import (
    AccessLevel,
    AngleOrigin,
    AngleStatus,
    AngleType,
    ClaimType,
    Dimension,
    LintVerdict,
    OriginType,
    PublicationEventType,
    RecommendedVisual,
    SourceCategory,
    SpeakerCategory,
    StancePolarity,
    TensionType,
    Valence,
)
from .ids import SentenceId, make_sentence_id
from .models import *  # noqa: F401,F403  — re-export every record type
from .models import SCHEMA_STATUS
from .paths import SitePaths, TopicPaths
from .validate import (
    ConstraintReport,
    ValidationReport,
    check_selection_constraints,
    validate_angles,
    validate_article_annotations,
    validate_claims,
    validate_observations,
    verify_quote,
)
