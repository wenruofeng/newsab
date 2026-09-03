"""``newsab_corpus`` — deterministic corpus construction for Phase 0.

Turns hand-staged articles into `Article` records with permanent sentence IDs, groups
publication instances into independent reporting clusters (D7), and reports both counting
units (§1.5).  No model calls anywhere in this package: everything here is the kind of work
D10 reserves for plain code, and everything here has to be re-runnable by a reviewer.

When S2 is built it takes over fetching and cleaning and calls into this package
for segmentation, ID assignment and clustering, rather than reimplementing them.
"""

from __future__ import annotations

__version__ = "0.6.0"

from .collection_log import CollectionLogEntry, variant_coverage
from .cluster import (
    DEFAULT_THRESHOLD,
    ClusterAssignment,
    assign_clusters,
    containment,
    jaccard,
    shingles,
    similarity_matrix,
)
from .han_fold import HAN_FOLD_VERSION, fold_han
from .index import CorpusStats, GroupStats, IndexRow, build_index, compute_stats
from .segment import SPLITTER_VERSION, segment, split_paragraphs, split_sentences
from .staging import (
    RESIDUE_RULES_VERSION,
    StagingArticle,
    build_articles,
    load_staging,
    rewrite_clusters,
    strip_residue,
)

__all__ = [
    "ClusterAssignment",
    "CollectionLogEntry",
    "CorpusStats",
    "DEFAULT_THRESHOLD",
    "GroupStats",
    "HAN_FOLD_VERSION",
    "IndexRow",
    "RESIDUE_RULES_VERSION",
    "SPLITTER_VERSION",
    "StagingArticle",
    "assign_clusters",
    "build_articles",
    "build_index",
    "compute_stats",
    "containment",
    "fold_han",
    "jaccard",
    "load_staging",
    "rewrite_clusters",
    "segment",
    "shingles",
    "similarity_matrix",
    "split_paragraphs",
    "split_sentences",
    "strip_residue",
    "variant_coverage",
]
