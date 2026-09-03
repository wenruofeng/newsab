"""The public-safe corpus index, and the dual-unit statistics (§1.5, §2.3).

Two things live here:

* ``index.jsonl`` — one row per article with metadata and cluster assignment, but **no
  body text**.  This is the file a submission or a published repo may contain (D14).
* :class:`CorpusStats` — the publication-instance / independent-cluster pair that D7 makes
  mandatory, per group and per source category, plus the homogeneity figure component C3
  renders and the category thresholds §3.3 S2 escalates on.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional, Sequence

from newsab_schema.enums import AccessLevel, OriginType, SourceCategory
from newsab_schema.ids import group_id_of
from newsab_schema.models.corpus import Article, SourceRegistry

#: §3.3 S2's escalation thresholds, as initial values ("初值").  Below these, a category is
#: labelled "not compared" on the page rather than compared on thin evidence.  The old
#: five-way taxonomy set a lower bar for `state` on the grounds that state outlets repeat
#: each other, so fewer of them still describe the category.  `other` is the opposite kind
#: of bucket — a magazine, a trade service and a portal have nothing in common — so it
#: carries the same bar as `serious` rather than inheriting the loophole.
DEFAULT_MIN_CLUSTERS: dict[str, int] = {"serious": 6, "other": 6}

#: How far the two sides' *vertical* (trade/sector press) share of clusters may diverge
#: before the build says so.  Provisional like every other threshold here: it
#: raises a warning that points a top-up at the missing kind of outlet, and it never
#: changes a number.
BEAT_IMBALANCE_LIMIT = 0.40
#: …and only once each side has enough clusters for a share to mean anything.
BEAT_IMBALANCE_MIN_CLUSTERS = 3

#: A report-only sampling-composition heuristic, not a language quota and not a
#: statement about which languages the signed scope expects.  Once a group has actually
#: yielded at least two languages and one observed language supplies this share of its
#: publication instances, the build points out the observed minority language(s).  The
#: 80% line catches the measured 86% / 93% English shape without trying to parse
#: natural-language group definitions into an invented machine rule.
LANGUAGE_DOMINANCE_HINT_SHARE = 0.80
#: Shares from one or two articles are noise rather than a useful collection hint.
LANGUAGE_HINT_MIN_INSTANCES = 3

#: RETIRED (analyze refactor): the core/peripheral label no longer moves
#: any denominator — statistics count every cluster — so this warning and the
#: DENOMINATOR WIPEOUT refusal below it are inert on new labels (new staging leaves
#: everything `core`).  The code stays because historical corpora carry the labels.
#: Original rationale: how far the two sides' `peripheral` rates may diverge before the
#: build says so.  The
#: label is a per-side denominator lever: removing clusters from one side only raises every
#: prevalence measured on that side relative to the other, so an asymmetric relabelling
#: pass moves every comparison on the page without anyone deciding to.  A real asymmetry is
#: possible and legitimate — one side's sample can genuinely contain more market wraps —
#: which is why this reports rather than refuses.
PERIPHERAL_IMBALANCE_LIMIT = 0.20
#: Below this many clusters a rate is noise, not a composition fact.
PERIPHERAL_IMBALANCE_MIN_CLUSTERS = 5


@dataclass(frozen=True)
class IndexRow:
    """One article, reduced to what may leave the machine (D14)."""

    article_id: str
    group_id: str
    source_id: str
    category: str
    beat_scope: str
    url: str
    title: str
    publish_date: str
    lang: str
    access_level: str
    origin_type: str
    wire_source: Optional[str]
    reporting_cluster_id: str
    paragraphs: int
    sentences: int

    def to_dict(self) -> dict:
        return asdict(self)


def build_index(articles: Sequence[Article], sources: SourceRegistry) -> list[IndexRow]:
    rows: list[IndexRow] = []
    for article in sorted(articles, key=lambda a: a.article_id):
        source = sources.by_id(article.source_id)
        rows.append(
            IndexRow(
                article_id=article.article_id,
                group_id=group_id_of(article.article_id),
                source_id=article.source_id,
                category=source.category.value,
                beat_scope=source.beat_scope,
                url=article.url,
                title=article.title,
                publish_date=article.publish_date.isoformat(),
                lang=article.lang,
                access_level=article.access_level.value,
                origin_type=article.origin.type.value,
                wire_source=article.origin.wire_source,
                reporting_cluster_id=article.reporting_cluster_id,
                paragraphs=len(article.structured_text),
                sentences=sum(len(p.sentences) for p in article.structured_text),
            )
        )
    return rows


@dataclass
class GroupStats:
    group_id: str
    publication_instances: int = 0
    independent_clusters: int = 0
    by_category: dict[str, dict[str, int]] = field(default_factory=dict)
    #: Instances and clusters per ``category × beat_scope`` cell.
    #: Category alone hides the worst composition bias we have measured: a side covered
    #: only by trade press and a side covered only by general newsrooms can land in the
    #: same "serious" bucket, and the balance check would call them comparable.
    by_beat: dict[str, dict[str, int]] = field(default_factory=dict)
    #: Publication instances and distinct reporting clusters per observed article
    #: language.  A multilingual cluster may appear under more than one language, so the
    #: cluster cells are independently useful counts and are not promised to sum to the
    #: group's denominator.
    by_language: dict[str, dict[str, int]] = field(default_factory=dict)
    by_access: dict[str, int] = field(default_factory=dict)
    by_origin: dict[str, int] = field(default_factory=dict)
    distinct_sources: int = 0
    #: Clusters excluded from every prevalence denominator because the collector judged
    #: their reporting peripheral to this topic.  They stay in the corpus and stay
    #: quotable; what they do not do is dilute "how many independent reports said X".
    peripheral_clusters: int = 0
    earliest: Optional[str] = None
    latest: Optional[str] = None

    @property
    def core_clusters(self) -> int:
        """The actual denominator: independent clusters minus the peripheral ones.

        ``independent_clusters`` counts everything in the sample and is the sampling
        figure; this is what a prevalence statement divides by.  They were the same number
        until relevance labels existed, and reading the first where the second was meant
        is how a relabelling pass can empty a side without any count on the page appearing
        to change.
        """
        return self.independent_clusters - self.peripheral_clusters

    @property
    def peripheral_rate(self) -> Optional[float]:
        if self.independent_clusters == 0:
            return None
        return self.peripheral_clusters / self.independent_clusters

    @property
    def homogeneity(self) -> Optional[float]:
        """``1 - clusters/instances``: 0 means every piece is independent, near 1 means one
        wire story reprinted.  This is component C3's headline number (§2.3)."""
        if self.publication_instances == 0:
            return None
        return 1.0 - self.independent_clusters / self.publication_instances

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["homogeneity"] = self.homogeneity
        payload["core_clusters"] = self.core_clusters
        payload["peripheral_rate"] = self.peripheral_rate
        return payload


@dataclass
class CorpusStats:
    topic_id: str
    groups: dict[str, GroupStats] = field(default_factory=dict)
    #: (group_id, category) pairs below the comparison threshold — these must be shown as
    #: "sample too small, not compared" rather than compared (§1.5).
    thin_categories: list[tuple[str, str, int, int]] = field(default_factory=list)
    #: Groups with no independent reporting at all.  Silence is a finding (D5), so it is
    #: surfaced here rather than left as an empty row.
    silent_groups: list[str] = field(default_factory=list)
    #: ``(group_id, vertical_share)`` per side when the two sides' trade-press shares
    #: differ by more than :data:`BEAT_IMBALANCE_LIMIT`.  Not an error and not a
    #: finding about the media: it says the two samples are made of different kinds of
    #: newsroom, which is a fact about our collecting, and it points the next top-up at
    #: the kind the other side is missing.
    beat_imbalance: list[tuple[str, float]] = field(default_factory=list)
    #: ``(group_id, language, instances, total_instances, share)`` for observed minority
    #: languages in a group dominated by another observed language.  Report only: this
    #: neither declares an expected language nor gates the build.
    thin_languages: list[tuple[str, str, int, int, float]] = field(default_factory=list)
    #: Groups that have independent reporting in the sample and **no core clusters left**
    #: after the relevance labels are applied.  This is not silence and must never be
    #: reported as silence: the media published, and a labelling decision took the whole
    #: side out of every denominator.  The build refuses on it, because the alternative is
    #: a page that says one side addressed nothing — a finding manufactured by our own
    #: labels.
    denominator_wipeouts: list[str] = field(default_factory=list)
    #: ``(group_id, peripheral_rate)`` per side when the two rates differ by more than
    #: :data:`PERIPHERAL_IMBALANCE_LIMIT`.  Reported, not refused — see that constant.
    peripheral_imbalance: list[tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "topic_id": self.topic_id,
            "groups": {g: s.to_dict() for g, s in sorted(self.groups.items())},
            "thin_categories": [
                {"group_id": g, "category": c, "clusters": n, "required": r}
                for g, c, n, r in self.thin_categories
            ],
            "silent_groups": self.silent_groups,
            "denominator_wipeouts": self.denominator_wipeouts,
            "peripheral_imbalance": [
                {"group_id": g, "peripheral_rate": round(rate, 3)}
                for g, rate in self.peripheral_imbalance
            ],
            "beat_imbalance": [
                {"group_id": g, "vertical_share": round(share, 3)}
                for g, share in self.beat_imbalance
            ],
            "thin_languages": [
                {
                    "group_id": g,
                    "lang": lang,
                    "instances": n,
                    "total_instances": total,
                    "instance_share": round(share, 3),
                }
                for g, lang, n, total, share in self.thin_languages
            ],
        }

    def sample_note(self, group_id: str) -> str:
        """The standard footnote wording from §2.3, ready to paste under a figure."""
        stats = self.groups[group_id]
        return (
            f"based on {stats.independent_clusters} independent reporting cluster(s) "
            f"across {stats.publication_instances} publication instance(s) in the "
            f"{group_id} sample"
        )


def compute_stats(
    articles: Sequence[Article],
    sources: SourceRegistry,
    *,
    topic_id: str,
    declared_groups: Optional[Sequence[str]] = None,
    min_clusters: Optional[dict[str, int]] = None,
    cluster_relevance: Optional[dict[str, str]] = None,
) -> CorpusStats:
    """Both counting units, per group, per category and per ``category × beat_scope``.

    ``cluster_relevance`` is the run's per-cluster topic-centrality map; anything it does
    not mention counts as ``core``, so omitting it reproduces the unlabelled numbers
    exactly.
    """
    thresholds = dict(DEFAULT_MIN_CLUSTERS if min_clusters is None else min_clusters)
    relevance = cluster_relevance or {}
    stats = CorpusStats(topic_id=topic_id)

    clusters_seen: dict[str, set[str]] = {}
    category_clusters: dict[tuple[str, str], set[str]] = {}
    beat_clusters: dict[tuple[str, str], set[str]] = {}
    language_clusters: dict[tuple[str, str], set[str]] = {}
    peripheral_seen: dict[str, set[str]] = {}
    sources_seen: dict[str, set[str]] = {}

    for article in articles:
        group = group_id_of(article.article_id)
        source = sources.by_id(article.source_id)
        entry = stats.groups.setdefault(group, GroupStats(group_id=group))

        entry.publication_instances += 1
        entry.by_access[article.access_level.value] = (
            entry.by_access.get(article.access_level.value, 0) + 1
        )
        entry.by_origin[article.origin.type.value] = (
            entry.by_origin.get(article.origin.type.value, 0) + 1
        )
        bucket = entry.by_category.setdefault(
            source.category.value, {"instances": 0, "clusters": 0}
        )
        bucket["instances"] += 1
        cell = f"{source.category.value}/{source.beat_scope}"
        beat_bucket = entry.by_beat.setdefault(cell, {"instances": 0, "clusters": 0})
        beat_bucket["instances"] += 1
        language_bucket = entry.by_language.setdefault(
            article.lang, {"instances": 0, "clusters": 0}
        )
        language_bucket["instances"] += 1

        clusters_seen.setdefault(group, set()).add(article.reporting_cluster_id)
        category_clusters.setdefault((group, source.category.value), set()).add(
            article.reporting_cluster_id
        )
        beat_clusters.setdefault((group, cell), set()).add(article.reporting_cluster_id)
        language_clusters.setdefault((group, article.lang), set()).add(
            article.reporting_cluster_id
        )
        if relevance.get(article.reporting_cluster_id, "core") != "core":
            peripheral_seen.setdefault(group, set()).add(article.reporting_cluster_id)
        sources_seen.setdefault(group, set()).add(article.source_id)

        iso = article.publish_date.isoformat()
        entry.earliest = iso if entry.earliest is None else min(entry.earliest, iso)
        entry.latest = iso if entry.latest is None else max(entry.latest, iso)

    for group, entry in stats.groups.items():
        entry.independent_clusters = len(clusters_seen.get(group, ()))
        entry.distinct_sources = len(sources_seen.get(group, ()))
        entry.peripheral_clusters = len(peripheral_seen.get(group, ()))
        for category, bucket in entry.by_category.items():
            bucket["clusters"] = len(category_clusters.get((group, category), ()))
            required = thresholds.get(category)
            if required is not None and bucket["clusters"] < required:
                stats.thin_categories.append((group, category, bucket["clusters"], required))
        for cell, beat_bucket in entry.by_beat.items():
            beat_bucket["clusters"] = len(beat_clusters.get((group, cell), ()))
        for lang, language_bucket in entry.by_language.items():
            language_bucket["clusters"] = len(
                language_clusters.get((group, lang), ())
            )
        if entry.independent_clusters == 0:
            stats.silent_groups.append(group)

        # Composition of what was actually collected, not a machine interpretation of
        # what the signed scope's prose might mean.  In particular, a completely absent
        # language cannot be inferred here and is never silently turned into a quota.
        if (
            entry.publication_instances >= LANGUAGE_HINT_MIN_INSTANCES
            and len(entry.by_language) >= 2
        ):
            dominant_lang, dominant = max(
                entry.by_language.items(), key=lambda item: item[1]["instances"]
            )
            if dominant["instances"] / entry.publication_instances >= LANGUAGE_DOMINANCE_HINT_SHARE:
                for lang, bucket in entry.by_language.items():
                    if lang == dominant_lang:
                        continue
                    stats.thin_languages.append(
                        (
                            group,
                            lang,
                            bucket["instances"],
                            entry.publication_instances,
                            bucket["instances"] / entry.publication_instances,
                        )
                    )

    # What the relevance labels did to each side's denominator.  `silent_groups` cannot
    # see this: a side with six clusters all labelled peripheral has independent reporting
    # and an empty denominator at the same time.
    for group, entry in stats.groups.items():
        if entry.independent_clusters > 0 and entry.core_clusters == 0:
            stats.denominator_wipeouts.append(group)
    stats.denominator_wipeouts.sort()

    peripheral_rate: dict[str, float] = {}
    for group, entry in stats.groups.items():
        if entry.independent_clusters >= PERIPHERAL_IMBALANCE_MIN_CLUSTERS:
            peripheral_rate[group] = entry.peripheral_rate or 0.0
    if len(peripheral_rate) == 2:
        (ga, ra), (gb, rb) = sorted(peripheral_rate.items())
        if abs(ra - rb) > PERIPHERAL_IMBALANCE_LIMIT:
            stats.peripheral_imbalance = [(ga, ra), (gb, rb)]

    # Composition, not volume: two sides can have the same cluster count and be made of
    # entirely different kinds of newsroom.
    vertical_share: dict[str, float] = {}
    for group, entry in stats.groups.items():
        total = sum(b["clusters"] for b in entry.by_beat.values())
        if total >= BEAT_IMBALANCE_MIN_CLUSTERS:
            vertical = sum(
                b["clusters"] for cell, b in entry.by_beat.items() if cell.endswith("/vertical")
            )
            vertical_share[group] = vertical / total
    if len(vertical_share) == 2:
        (ga, sa), (gb, sb) = sorted(vertical_share.items())
        if abs(sa - sb) > BEAT_IMBALANCE_LIMIT:
            stats.beat_imbalance = [(ga, sa), (gb, sb)]

    # A group the topic declared but that produced nothing is silence too (D5), and the
    # loop above would never see it.  The list comes from the topic manifest because the
    # source registry is global and knows nothing about this comparison's sides (R-3).
    for group_id in declared_groups or ():
        if group_id not in stats.groups:
            stats.groups[group_id] = GroupStats(group_id=group_id)
            stats.silent_groups.append(group_id)

    stats.silent_groups = sorted(set(stats.silent_groups))
    stats.thin_categories.sort()
    stats.thin_languages.sort()
    return stats
