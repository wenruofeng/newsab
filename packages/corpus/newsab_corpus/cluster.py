"""Reporting-origin clustering — publication instances -> independent reporting clusters.

This is the foundation D7 rests on: "37 publication instances, 4 independent reporting
sources" is the single most informative number on a topic page (§2.3, component C3), and
every prevalence statement on the site divides by the cluster count rather than the article
count.  So the clustering has to be plain, deterministic, explicable code — a reader who
disputes a number must be able to re-run this and get the same clusters.

Method: character n-gram shingles + **containment** similarity, single-linkage within a
group.  Containment (``|A∩B| / min(|A|,|B|)``) rather than Jaccard because the common case
is a wire story embedded in a longer local piece — Jaccard punishes the added local
paragraphs and would score a clear syndication as unrelated.

Scope limit worth knowing: clustering runs *within* a language group.  A wire story
published in Chinese and in English is not detected as one cluster, because character
shingles do not survive translation.  That is a real gap; it is recorded in the run report
rather than papered over, and cross-language origin detection is S2's problem.

Within a group, traditional and simplified Chinese *are* folded together before shingling
(an ettoday zh-TW reprint of a zh-CN original measured 0.052 containment on raw
characters).  See :mod:`newsab_corpus.han_fold`; the fold touches fingerprints only, never
stored text, and each run record names the fold version it ran under.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Sequence

from newsab_schema.enums import OriginType
from newsab_schema.ids import group_of, make_cluster_id
from newsab_schema.models.corpus import Article

from .han_fold import HAN_FOLD_VERSION, fold_han

#: Character n-gram width.  5 works for both Chinese (≈5 characters is a phrase) and
#: English (≈one short word plus context).
SHINGLE_N = 5
#: Containment above which two articles are treated as the same reporting cluster.
#: PROVISIONAL — to be checked against the Phase 0 corpus (calibration checks the metric
#: family, this threshold rides along).  Recorded in the run record so any number is re-derivable.
DEFAULT_THRESHOLD = 0.60
#: Articles shorter than this (in shingles) are too short to cluster reliably; they stay
#: singletons and are reported, rather than being merged on a coincidence.
MIN_SHINGLES = 20
#: A title/standfirst-only record can be long enough to clear ``MIN_SHINGLES`` while still
#: carrying too little text to join independent reports safely.  It may keep its single
#: strongest qualifying similarity edge, but it may not contribute the several edges
#: needed to bridge otherwise separate connected components.  256 shingles is roughly a
#: 260-character news lead; the measured title/lead-only records were 59–215 shingles,
#: while the shortest full article was 588.
SHORT_BRIDGE_MAX_SHINGLES = 256

_NOISE = re.compile(r"[\s　]+")


@dataclass
class ClusterAssignment:
    """Result of one clustering run, including everything needed to reproduce it."""

    cluster_ids: dict[str, str]
    threshold: float
    shingle_n: int
    #: Name of the script fold the fingerprints ran under (han_fold.HAN_FOLD_VERSION).
    han_fold: str = HAN_FOLD_VERSION
    #: cluster_id -> article_ids, in assignment order.
    members: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: article_id -> number of shingles, for the "too short to judge" cases.
    sizes: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def cluster_count(self) -> int:
        return len(self.members)


def article_text(article: Article) -> str:
    """The text clustering sees: body only, headline excluded.

    Headlines are excluded on purpose — a syndicating outlet routinely rewrites the
    headline while keeping the body verbatim (that is exactly what ``local_edits`` records),
    so including it would push real syndications below the threshold.
    """
    return " ".join(
        s.text for p in article.structured_text if p.index > 0 for s in p.sentences
    )


def shingles(text: str, n: int = SHINGLE_N) -> set[str]:
    cleaned = fold_han(_NOISE.sub("", text))
    if len(cleaned) < n:
        return set()
    return {cleaned[i : i + n] for i in range(len(cleaned) - n + 1)}


def containment(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class _UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:  # path compression
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Lower article_id wins, so cluster membership does not depend on input order.
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def assign_clusters(
    articles: Sequence[Article],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    shingle_n: int = SHINGLE_N,
) -> ClusterAssignment:
    """Group articles into independent reporting clusters, one group at a time."""
    result = ClusterAssignment(cluster_ids={}, threshold=threshold, shingle_n=shingle_n)
    by_group: dict[str, list[Article]] = {}
    for article in articles:
        by_group.setdefault(group_of(article.article_id), []).append(article)

    for group, members in sorted(by_group.items()):
        members = sorted(members, key=lambda a: a.article_id)
        fingerprints = {a.article_id: shingles(article_text(a), shingle_n) for a in members}
        result.sizes.update({aid: len(s) for aid, s in fingerprints.items()})

        short = [aid for aid, s in fingerprints.items() if len(s) < MIN_SHINGLES]
        for aid in short:
            result.warnings.append(
                f"{aid}: only {len(fingerprints[aid])} shingles — too short to judge "
                "syndication; left as its own cluster"
            )

        uf = _UnionFind(a.article_id for a in members)
        qualifying: dict[str, list[tuple[float, str]]] = {
            article.article_id: [] for article in members
        }
        for i, left in enumerate(members):
            if len(fingerprints[left.article_id]) < MIN_SHINGLES:
                continue
            for right in members[i + 1 :]:
                if len(fingerprints[right.article_id]) < MIN_SHINGLES:
                    continue
                score = containment(
                    fingerprints[left.article_id], fingerprints[right.article_id]
                )
                if score >= threshold:
                    left_short = len(fingerprints[left.article_id]) <= SHORT_BRIDGE_MAX_SHINGLES
                    right_short = len(fingerprints[right.article_id]) <= SHORT_BRIDGE_MAX_SHINGLES
                    if not left_short and not right_short:
                        uf.union(left.article_id, right.article_id)
                    else:
                        qualifying[left.article_id].append((score, right.article_id))
                        qualifying[right.article_id].append((score, left.article_id))

        # A short node chooses at most one edge.  In the resulting undirected graph a path
        # cannot enter a short node from one long component and leave it for another: its
        # sole chosen edge is already consumed.  Selection is independent of input order.
        for article_id in sorted(qualifying):
            if len(fingerprints[article_id]) > SHORT_BRIDGE_MAX_SHINGLES:
                continue
            candidates = sorted(qualifying[article_id], key=lambda item: (-item[0], item[1]))
            if not candidates:
                continue
            score, neighbour = candidates[0]
            uf.union(article_id, neighbour)
            if len(candidates) > 1:
                result.warnings.append(
                    f"{article_id}: {len(fingerprints[article_id])} shingles and "
                    f"{len(candidates)} similarity edges at threshold {threshold:.3f}; "
                    f"short-edge bridge guard kept only strongest match {neighbour} "
                    f"({score:.3f}) so a title/lead fragment cannot join distinct reports"
                )

        # The cluster is named after its representative member (the lexicographically
        # smallest article_id in it, which is what _UnionFind keeps as the root).  A
        # positional serial would renumber every later cluster whenever one article
        # entered or left the set — the same defect content addressing removed from
        # article_id (R-1/R-2).
        roots: dict[str, str] = {}
        for article in members:
            root = uf.find(article.article_id)
            if root not in roots:
                roots[root] = make_cluster_id(group, root)
            cluster_id = roots[root]
            result.cluster_ids[article.article_id] = cluster_id
            result.members.setdefault(cluster_id, []).append(article.article_id)

    result.warnings.extend(check_origin_consistency(articles, result))
    return result


def check_origin_consistency(
    articles: Sequence[Article], assignment: ClusterAssignment
) -> list[str]:
    """Cross-check the declared ``origin`` against what the text similarity found.

    Two disagreements matter:

    * a cluster with several articles all declared ``original`` — either the origin labels
      are wrong or the threshold merged unrelated pieces.  Either way a human must look,
      because this is the number that becomes "n independent sources";
    * an article declared as wire copy that matched nothing — plausible (the wire original
      may not be in the corpus), but worth listing so it is a decision rather than a
      default.
    """
    by_id = {a.article_id: a for a in articles}
    problems: list[str] = []

    for cluster_id, member_ids in sorted(assignment.members.items()):
        if len(member_ids) < 2:
            continue
        originals = [
            aid for aid in member_ids if by_id[aid].origin.type == OriginType.ORIGINAL
        ]
        if len(originals) > 1:
            problems.append(
                f"{cluster_id}: {len(originals)} articles in one text cluster are all declared "
                f"origin=original ({', '.join(originals)}). Either the labels are wrong or the "
                "similarity threshold merged distinct reporting — this directly changes the "
                "independent-cluster count (D7), so resolve it before running A1."
            )

    for article in articles:
        if article.origin.type == OriginType.ORIGINAL:
            continue
        # A press release's "original" is the statement itself, which is never an article
        # in the corpus — so a lone rewrite of one is the normal case, not an unlogged
        # gap.  The disclosure this check exists to force is already structural there:
        # `origin.wire_source` names the issuing body.
        if article.origin.type == OriginType.PRESS_RELEASE:
            continue
        cluster = assignment.cluster_ids.get(article.article_id)
        if cluster and len(assignment.members.get(cluster, [])) == 1:
            problems.append(
                f"{article.article_id}: declared origin={article.origin.type.value} but matched no "
                "other article in the corpus; if the wire original was never collected, say so "
                "in the collection log rather than leaving it implicit (D5)"
            )
    return problems


def similarity_matrix(
    articles: Sequence[Article], *, shingle_n: int = SHINGLE_N
) -> list[tuple[str, str, float, float]]:
    """All within-group pairs as ``(a, b, containment, jaccard)`` — for threshold tuning."""
    by_group: dict[str, list[Article]] = {}
    for article in articles:
        by_group.setdefault(group_of(article.article_id), []).append(article)

    rows: list[tuple[str, str, float, float]] = []
    for members in by_group.values():
        members = sorted(members, key=lambda a: a.article_id)
        fps = {a.article_id: shingles(article_text(a), shingle_n) for a in members}
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                a, b = fps[left.article_id], fps[right.article_id]
                rows.append(
                    (left.article_id, right.article_id, containment(a, b), jaccard(a, b))
                )
    return sorted(rows, key=lambda r: -r[2])
