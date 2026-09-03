"""Which reporting clusters count — one rule, and every stage reads it here.

A cluster is **readable** when *any* member article is ``access_level: full``.  The
"any" is the same one ``cluster_relevance`` uses: one fully readable carrier means the
reporting is readable, so the cluster's annotation may be counted.  A cluster whose
members are all partial/blocked drops out of the numerator *and* the denominator — its
answer never enters a count at all.

The rule lives in the schema package because it is a fact about the corpus, not about
any one stage's arithmetic, and because at least three stages must agree on it exactly:

* **analyze** builds the statistical universe from it (``newsab_a1.qa_analyze``), so a
  badge reads "9 of 26" rather than "9 of 42";
* **write / render-localize** build the reader's evidence list from it
  (``newsab_editorial.evidence``) — a badge that promises nine reports has to be able to
  show nine, and it may not offer a tenth the statistics did not count.

Two implementations of "any member full" would drift, and the first symptom would be a
page whose badge and clickable evidence disagree — which is exactly what happened when
only analyze had been taught the rule.
"""

from __future__ import annotations

from typing import Iterable, Union

from .enums import AccessLevel

#: The one access level that makes a cluster countable.
READABLE_ACCESS_LEVEL = AccessLevel.FULL

AccessLevelLike = Union[AccessLevel, str, None]


def is_readable_access(level: AccessLevelLike) -> bool:
    """``True`` for ``full`` alone, given the enum or its string value.

    Anything unknown — including ``None`` for an article missing from a partial mapping —
    is not-full, so an incomplete mapping can only shrink the universe, never inflate it.
    """
    if isinstance(level, AccessLevel):
        return level is READABLE_ACCESS_LEVEL
    return level == READABLE_ACCESS_LEVEL.value


def readable_cluster_ids(
    members: Iterable[tuple[str, AccessLevelLike]],
) -> set[str]:
    """The cluster ids with at least one ``full`` member.

    ``members`` is any iterable of ``(reporting_cluster_id, access_level)`` pairs, which
    is the shape both callers already have: the analyze stage joins the corpus run's
    article list against the store's access levels, and the editorial stage reads
    ``Article.access_level`` straight off the articles it loaded.
    """
    return {
        cluster_id for cluster_id, level in members if is_readable_access(level)
    }


def split_clusters(
    members: Iterable[tuple[str, AccessLevelLike]],
) -> tuple[set[str], set[str]]:
    """``(readable, unreadable)`` over the same pairs — the unreadable half is the
    "sampled but excluded" count a run record reports."""
    pairs = list(members)
    readable = readable_cluster_ids(pairs)
    every: set[str] = {cluster_id for cluster_id, _ in pairs}
    return readable, every - readable


def readable_clusters_of_articles(articles: Iterable[object]) -> set[str]:
    """Convenience for callers holding whole ``Article`` records."""
    return readable_cluster_ids(
        (article.reporting_cluster_id, getattr(article, "access_level", None))
        for article in articles
    )


__all__ = [
    "READABLE_ACCESS_LEVEL",
    "is_readable_access",
    "readable_cluster_ids",
    "readable_clusters_of_articles",
    "split_clusters",
]
