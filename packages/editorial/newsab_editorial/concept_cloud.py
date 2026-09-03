"""The concept cloud: what each side's coverage talks about, questions set aside.

An *unsupervised* contrast, and the only one on the page: it collapses the question
dimension and shows the two sides' answer vocabularies side by side.  It asserts no
finding, runs no test and draws no comparison — it puts two raw distributions next to each
other and lets the reader look.  That is why V-3 ("no unsupported contrast may be drawn")
does not bite here: nothing is being claimed.

Everything below is arithmetic over stored artifacts — no model, no judgement, no writer
input — from one of two sources:

* ``build`` sums the pinned analyze run's ``question_stats.json``: each side's
  ``category_counts`` across every question, over that side's total of classified answers.
  What the coverage *answers*.
* ``build_from_topics`` counts the collect stage's ``topics_raised`` phrases, once per
  independent report, over that side's whole set of reports.  What the coverage is
  *about* — asked before any question existed.

Which one a page draws is a render-time switch (``page-render --concept-cloud``); both
produce the same two ranked columns, and both assert exactly nothing.

Two rules the shape of the thing depends on:

* **Size is share, never count.**  A side with four times the reporting clusters would
  otherwise look four times louder about everything it says.  Each side is normalized by
  its own total; the font map is shared, so heights stay comparable across the midline.
* **Below the threshold is not silence.**  The cloud draws only concepts represented by
  at least ``MIN_COUNT`` classified answers and at least ``SHARE_THRESHOLD`` of the
  side's total. Every concept keeps its real numbers for the hover panel, with the reason
  it is not drawn (below the threshold / past the per-side cap / never said at all).
  "Not shown" must never be readable as "never said" — the same discipline the blindspot
  semantics carry.

Layout and parameters are the user's, iterated on a live prototype and signed off: two
columns each ranked by its own share, percentages hugging the midline, hover shows data
only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from newsab_schema.readability import readable_clusters_of_articles

#: Counting machinery, not concepts: ``unclear`` is "this cluster answered but the answer
#: resists bucketing", ``none_reported`` is an explicit absence.  Neither is something a
#: side *talks about*, so both leave the numerator and the denominator.
MECHANISM_CATEGORIES = frozenset({"unclear", "none_reported"})

#: Render parameters, chosen by the user.  Provisional in the same sense as the analyze
#: thresholds: chosen by eye on real topics, tunable here and nowhere else.
SHARE_THRESHOLD = 0.02
MIN_COUNT = 2
MAX_PER_SIDE = 20
FONT_MIN_PX = 10.0
FONT_MAX_PX = 30.0


@dataclass(frozen=True)
class Concept:
    """One concept on one side — drawn or not, its real numbers either way."""

    category: str
    count: int
    share: float
    #: ``""`` when drawn, else why it is not: ``below_threshold`` / ``capped``.
    hidden_reason: str = ""

    @property
    def shown(self) -> bool:
        return not self.hidden_reason


@dataclass
class SideCloud:
    """One side's whole vocabulary: what is drawn, what is not, and the denominator."""

    group_id: str
    total: int
    concepts: dict[str, Concept] = field(default_factory=dict)
    #: Categories in display order (own share, descending; ties broken by name).
    shown: list[str] = field(default_factory=list)

    @property
    def below_threshold(self) -> int:
        return sum(1 for c in self.concepts.values() if c.hidden_reason == "below_threshold")

    @property
    def capped(self) -> int:
        return sum(1 for c in self.concepts.values() if c.hidden_reason == "capped")

    @property
    def top_share(self) -> float:
        return self.concepts[self.shown[0]].share if self.shown else 0.0


def tally(question_stats: dict) -> dict[str, tuple[int, dict[str, int]]]:
    """Per side: its classified-answer total and its per-concept counts.

    The unit is (reporting cluster × question): one cluster answering ten questions
    contributes ten classified answers.  That is the natural denominator for "how much of
    what this side says is about X" — and it is exactly what ``category_counts`` counts.
    """
    counts: dict[str, dict[str, int]] = {}
    for stats in question_stats.values():
        for group_id, gstats in (stats.get("groups") or {}).items():
            side = counts.setdefault(group_id, {})
            for category, n in (gstats.get("category_counts") or {}).items():
                if category in MECHANISM_CATEGORIES:
                    continue
                side[category] = side.get(category, 0) + int(n)
    return {gid: (sum(side.values()), side) for gid, side in counts.items()}


def tally_topics(
    topics_by_article: dict[str, list[dict]],
    articles: Iterable,
) -> dict[str, tuple[int, dict[str, int]]]:
    """Per side: its independent-report total and how many of them raise each phrase.

    The other source for this section.  ``topics_raised`` is what the collect
    agent wrote down while reading each article — the few things the piece is actually
    about — before any question existed.  Two rules make it comparable with the answer
    cloud rather than a different kind of object:

    * **the unit is the reporting cluster**, exactly as everywhere else on the site: a
      wire item and its twelve reprints raise their phrases once between them, and a
      phrase repeated inside one cluster counts once;
    * **the denominator is that side's whole set of readable independent reports**, not
      the ones that happen to carry a ``topics_raised`` record — a corpus extended before
      the artifact existed would otherwise inflate every share.  Readable is the site's
      one counting universe (``newsab_schema.readability``): a cluster nobody can read is
      not part of any other count on the page, and it is not part of this one either.

    These phrases are reading notes, never evidence: they say what a report is about and
    nothing about what it answers, and the section that draws them says so.
    """
    articles = list(articles)
    readable = readable_clusters_of_articles(articles)
    per_side_clusters: dict[str, set[str]] = {}
    phrase_clusters: dict[str, dict[str, set[str]]] = {}
    for article in articles:
        group_id = article.article_id.split("_", 1)[0].lower()
        cluster_id = article.reporting_cluster_id
        if cluster_id not in readable:
            continue
        per_side_clusters.setdefault(group_id, set()).add(cluster_id)
        for entry in topics_by_article.get(article.article_id) or ():
            phrase = (entry.get("pivot_en") or "").strip()
            if not phrase:
                continue
            phrase_clusters.setdefault(group_id, {}).setdefault(phrase, set()).add(cluster_id)
    return {
        group_id: (
            len(clusters),
            {
                phrase: len(hits)
                for phrase, hits in (phrase_clusters.get(group_id) or {}).items()
            },
        )
        for group_id, clusters in per_side_clusters.items()
    }


def build_from_topics(
    topics_by_article: dict[str, list[dict]],
    articles: Iterable,
    *,
    threshold: float = SHARE_THRESHOLD,
    min_count: int = MIN_COUNT,
    cap: int = MAX_PER_SIDE,
) -> dict[str, SideCloud]:
    """The same two columns, built from ``topics_raised`` instead of answer categories."""
    return _rank(tally_topics(topics_by_article, articles), threshold, min_count, cap)


def build(
    question_stats: dict,
    *,
    threshold: float = SHARE_THRESHOLD,
    min_count: int = MIN_COUNT,
    cap: int = MAX_PER_SIDE,
) -> dict[str, SideCloud]:
    """The two clouds, each ranked by its own share — never mirrored against the other.

    Same concept, different rank on the two sides: the rank difference is itself the
    finding a reader can see.
    """
    return _rank(tally(question_stats), threshold, min_count, cap)


def _rank(
    tallied: dict[str, tuple[int, dict[str, int]]],
    threshold: float,
    min_count: int,
    cap: int,
) -> dict[str, SideCloud]:
    """Rank one tally into two drawable columns — the one shape both sources share."""
    clouds: dict[str, SideCloud] = {}
    for group_id, (total, counts) in tallied.items():
        cloud = SideCloud(group_id=group_id, total=total)
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        drawn = 0
        for category, count in ranked:
            share = count / total if total else 0.0
            if count < min_count or share < threshold:
                reason = "below_threshold"
            elif drawn >= cap:
                reason = "capped"
            else:
                reason = ""
                drawn += 1
                cloud.shown.append(category)
            cloud.concepts[category] = Concept(category, count, share, reason)
        clouds[group_id] = cloud
    return clouds


def font_px(
    share: float,
    top_share: float,
    *,
    fmin: float = FONT_MIN_PX,
    fmax: float = FONT_MAX_PX,
) -> float:
    """Proportional map against the larger of the two columns' leaders.

    Both sides share one map, so a bigger word really does mean a bigger share wherever it
    sits.  The old map added a fixed 13px base before applying the share; that made a 2%
    phrase look much closer to a 20% phrase than the data warranted.  The leader is now
    ``fmax`` and every other phrase receives exactly its share ratio of that size, subject
    only to a small readability floor.
    """
    if top_share <= 0:
        return fmin
    ratio = min(max(share / top_share, 0.0), 1.0)
    return max(fmin, ratio * fmax)
