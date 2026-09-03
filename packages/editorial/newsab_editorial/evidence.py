"""Deterministic evidence assembly for the reader page.

Everything a reader can click down into is built here, from artifacts only — no model,
no writer input, nothing retyped (non-negotiable 4):

* **the evidence set behind one side of one angle** — one entry per *reporting cluster*
  the badge counts, so "9 of 12 independent reports" comes with nine clickable
  originals, not with however many sentences the writer felt like quoting.  The writer's
  pick leads the list; the rest are the same shape, folded;
* **the sentence card** behind every `[source]` chip — which article, which outlet, which
  date, which cluster, where in the piece — so the reader meets our own record of a
  sentence before being thrown out to a news site;
* **the annotation appendix** — every question in the set, both sides' answer
  distributions, every cluster's annotated answer with its anchors, ordered by the
  analyze stage's own ranking.  The storyline is what the writer chose; this is
  everything the same statistics saw.

The appendix carries the annotation layer verbatim (each cluster's own-language answer
summary).  That is the point: it is what a reviewer needs to see what the writer picked
*from*, and it is written by the annotate stage, not by the writer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AbstractSet, Iterable, Optional

from newsab_schema.enums import FindingKind
from newsab_schema.ids import SentenceId
from newsab_schema.models.corpus import Article, SourceRegistry
from newsab_schema.models.findings import QAFinding
from newsab_schema.models.page import AngleBlock, Quote, SideAnswerBlock
from newsab_schema.models.qa import ANSWER_CATEGORY_UNCLEAR, ClusterAnswer, QuestionSet
from newsab_schema.readability import readable_clusters_of_articles

#: Order the appendix falls back to for questions the analyze stage produced no finding
#: for.  Findings keep their own rank; these come after, biggest coverage gap first.
_NO_FINDING_RANK = 10_000

#: Non-negotiable 7 says full article text never ships — quotes are URL + verbatim
#: sentence.  One click, one sentence honours that; an appendix listing every anchor of
#: every question does not, because a four-sentence wire item would arrive whole.  So a
#: render never shows more than half of any single article, and never more than this
#: many of its sentences.  Storyline writer picks claim the budget first but do not
#: bypass it: any anchor past an article's budget — storyline or appendix — renders as a
#: position reference with no text.
MAX_ARTICLE_SHARE = 0.5
MAX_ARTICLE_SENTENCES = 10


# --------------------------------------------------------------------------------------
# the sentence card — what sits behind every [source] chip
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SentenceCard:
    """Our record of one quoted sentence, for the intermediate detail view."""

    sentence_id: str
    article_id: str
    cluster_id: str
    group_id: str
    lang: str
    text: str
    title: str
    url: str
    source_id: str
    source_name: str
    publish_date: str
    origin_type: str
    wire_source: Optional[str]
    paragraph: int
    sentence: int
    cluster_articles: int

    def to_json(self) -> dict:
        return {
            "sentence_id": self.sentence_id,
            "text": self.text,
            "lang": self.lang,
            "title": self.title,
            "url": self.url,
            "source": self.source_name,
            "source_id": self.source_id,
            "date": self.publish_date,
            "origin": self.origin_type,
            "wire_source": self.wire_source,
            "cluster": self.cluster_id,
            "cluster_articles": self.cluster_articles,
            "paragraph": self.paragraph,
            "sentence": self.sentence,
        }


class SentenceIndex:
    """Resolves sentence IDs to :class:`SentenceCard`s against one pinned corpus run."""

    def __init__(
        self,
        articles: Iterable[Article],
        registry: Optional[SourceRegistry] = None,
        *,
        lang: str = "en",
    ) -> None:
        self._articles = {a.article_id: a for a in articles}
        self._lang = lang
        self._names: dict[str, str] = {}
        #: The registry entry behind every outlet the page names, so a reader can ask
        #: "who is this outlet?" of any byline on the page.
        self.sources: dict[str, object] = {}
        #: Outlets the render actually named — the media payload is built from these.
        self.used_sources: set[str] = set()
        if registry is not None:
            for source in registry.sources:
                self._names[source.id] = (
                    source.name.get(lang) or source.name.get("en") or source.id
                )
                self.sources[source.id] = source
        #: Sentence IDs the renderer actually put on the page — the detail-view payload
        #: is built from this, so a sentence never ships without being displayed.
        self.used: set[str] = set()
        self._shown: dict[str, int] = {}
        #: Articles whose display budget stopped an appendix anchor from being shown.
        self.withheld: dict[str, int] = {}
        self._denied: set[str] = set()
        self._sentence_count = {
            a.article_id: sum(len(p.sentences) for p in a.structured_text)
            for a in self._articles.values()
        }
        self._cluster_size: dict[str, int] = {}
        for article in self._articles.values():
            self._cluster_size[article.reporting_cluster_id] = (
                self._cluster_size.get(article.reporting_cluster_id, 0) + 1
            )
        #: The counted universe (qa-0.5.0): clusters with a fully readable member.  The
        #: badge is computed over exactly these, so the evidence list must be too.
        self.readable_clusters: AbstractSet[str] = readable_clusters_of_articles(
            self._articles.values()
        )

    def source_name(self, source_id: str) -> str:
        return self._names.get(source_id, source_id)

    def cluster_size(self, cluster_id: str) -> int:
        return self._cluster_size.get(cluster_id, 1)

    def article(self, sentence_id: str) -> Optional[Article]:
        return self._articles.get(SentenceId.parse(sentence_id).article_id)

    def cluster_of(self, sentence_id: str) -> Optional[str]:
        article = self.article(sentence_id)
        return article.reporting_cluster_id if article else None

    def budget(self, article_id: str) -> int:
        """How many of one article's sentences a single render may ever show."""
        total = self._sentence_count.get(article_id, 0)
        return max(1, min(int(total * MAX_ARTICLE_SHARE), MAX_ARTICLE_SENTENCES))

    def shown(self, article_id: str) -> int:
        return self._shown.get(article_id, 0)

    def mark(self, sentence_id: str) -> str:
        """Record that this sentence is rendered on the page; returns it unchanged.

        Callers that choose whether text is public must use :meth:`allow`; this lower-level
        primitive only records a decision already made there.
        """
        if sentence_id not in self.used:
            self.used.add(sentence_id)
            article_id = SentenceId.parse(sentence_id).article_id
            self._shown[article_id] = self._shown.get(article_id, 0) + 1
        return sentence_id

    def allow(self, sentence_id: str) -> bool:
        """Whether the appendix may show this sentence's text, spending the budget if so.

        Already-shown sentences are free — showing the same sentence twice ships nothing
        new.
        """
        if sentence_id in self.used:
            return True
        article_id = SentenceId.parse(sentence_id).article_id
        if self.shown(article_id) >= self.budget(article_id):
            # The same anchor may be asked about more than once (the storyline pre-pass
            # plus the real render); the withheld tally counts distinct anchors.
            if sentence_id not in self._denied:
                self._denied.add(sentence_id)
                self.withheld[article_id] = self.withheld.get(article_id, 0) + 1
            return False
        self.mark(sentence_id)
        return True

    def card(self, sentence_id: str) -> Optional[SentenceCard]:
        parsed = SentenceId.parse(sentence_id)
        article = self._articles.get(parsed.article_id)
        if article is None or not article.has_sentence(sentence_id):
            return None
        return SentenceCard(
            sentence_id=sentence_id,
            article_id=article.article_id,
            cluster_id=article.reporting_cluster_id,
            group_id=parsed.group.lower(),
            lang=article.lang,
            text=article.sentence_text(sentence_id),
            title=article.title,
            url=article.url,
            source_id=article.source_id,
            source_name=self._names.get(article.source_id, article.source_id),
            publish_date=article.publish_date.isoformat(),
            origin_type=article.origin.type.value,
            wire_source=article.origin.wire_source,
            paragraph=parsed.paragraph,
            sentence=parsed.sentence,
            cluster_articles=self._cluster_size.get(article.reporting_cluster_id, 1),
        )


# --------------------------------------------------------------------------------------
# the evidence set behind one side of one angle
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceItem:
    """One counted cluster's verbatim sentence, ready to render."""

    cluster_id: str
    sentence_id: str
    #: True for the sentence the writer chose as this side's representative quote.
    writer_pick: bool
    translation: Optional[dict] = None
    #: The cluster's annotated category for this question (raw, from annotate).
    category: Optional[str] = None


class AnswerIndex:
    """The annotate stage's answers, keyed the way the page needs to read them.

    ``excluded_clusters`` are the reporting clusters the analysis run left out of its
    denominators — clusters the collector judged peripheral to this topic.  They
    are dropped here, at the single place every consumer reads answers from, because the
    alternative is a page whose badge says twelve reports and whose evidence list can
    produce thirteen: the analysis and the reader would be counting different things.
    The clusters keep their annotations on disk; what they lose is a vote.
    """

    def __init__(
        self,
        answers: Iterable[ClusterAnswer],
        excluded_clusters: Iterable[str] = (),
    ) -> None:
        self.excluded_clusters = frozenset(excluded_clusters)
        self._by_question: dict[str, dict[str, ClusterAnswer]] = {}
        for answer in answers:
            if answer.reporting_cluster_id in self.excluded_clusters:
                continue
            self._by_question.setdefault(answer.question_id, {})[
                answer.reporting_cluster_id
            ] = answer

    def for_question(self, question_id: str) -> dict[str, ClusterAnswer]:
        return self._by_question.get(question_id, {})

    def for_group(self, question_id: str, group_id: str) -> dict[str, ClusterAnswer]:
        return {
            cluster: answer
            for cluster, answer in self.for_question(question_id).items()
            if answer.group_id == group_id
        }


def badge_selector(side: SideAnswerBlock) -> str:
    """``addressed`` or ``top_category`` — what the side's badge actually counts."""
    _, _, selector = side.badge.computed_from.partition(":")
    return selector or "addressed"


def counted_clusters(
    side: SideAnswerBlock,
    angle: AngleBlock,
    finding: Optional[QAFinding],
    answers: AnswerIndex,
    readable: Optional[AbstractSet[str]] = None,
) -> list[str]:
    """The clusters the side's badge numerator is made of, sorted by cluster ID.

    This is the set the reader is entitled to see: a badge that says nine reports must
    be able to show nine reports — and may not offer a tenth.

    ``readable`` is the analysis universe (``newsab_schema.readability``): since
    qa-0.5.0 the badge is counted over clusters with a fully readable member only, so a
    cluster that answered from behind a paywall is in neither the count nor this list.
    ``None`` keeps every addressed cluster, for callers with no article records at hand
    and for pages pinned to a pre-0.5.0 run, whose universe was every sampled cluster.
    """
    per_cluster = answers.for_group(angle.question_id, side.group_id)
    if readable is not None:
        per_cluster = {
            cluster: answer
            for cluster, answer in per_cluster.items()
            if cluster in readable
        }
    selector = badge_selector(side)
    if selector == "top_category":
        top = None
        if finding is not None:
            stats = next((g for g in finding.groups if g.group_id == side.group_id), None)
            top = stats.top_category if stats else None
        if top is None:
            return []
        return sorted(
            cluster
            for cluster, answer in per_cluster.items()
            if answer.addressed and answer.answer_category == top
        )
    return sorted(
        cluster for cluster, answer in per_cluster.items() if answer.addressed
    )


def side_evidence(
    side: SideAnswerBlock,
    angle: AngleBlock,
    finding: Optional[QAFinding],
    answers: AnswerIndex,
    index: SentenceIndex,
) -> list[EvidenceItem]:
    """One entry per counted cluster, the writer's picks first.

    Within a cluster the writer's chosen sentence wins; otherwise the cluster shows the
    first anchor its annotation recorded — deterministic, and the same on every render.
    """
    per_cluster = answers.for_group(angle.question_id, side.group_id)
    if side.is_silent_side:
        # qa-0.4.0: the quiet side of an attention gap may still hold a mention or
        # two.  List them — the data stays on the table — from each addressed
        # cluster's first recorded anchor; no answer is asserted for this side, so
        # there are no writer picks.  Total silence yields the empty list naturally.
        # The quiet side's rate is counted over readable clusters like any other, so a
        # mention from outside that universe is not one of the mentions being counted.
        items = []
        for cluster in sorted(
            c
            for c, a in per_cluster.items()
            if a.addressed and c in index.readable_clusters
        ):
            answer = per_cluster[cluster]
            if not answer.evidence or index.card(answer.evidence[0]) is None:
                continue
            items.append(
                EvidenceItem(
                    cluster_id=cluster,
                    sentence_id=answer.evidence[0],
                    writer_pick=False,
                    translation=None,
                    category=answer.answer_category,
                )
            )
        return items
    counted = counted_clusters(
        side, angle, finding, answers, readable=index.readable_clusters
    )

    picked: dict[str, Quote] = {}
    order: list[str] = []
    for quote in side.quotes:
        cluster = index.cluster_of(quote.sentence_id)
        if cluster is None or cluster in picked:
            continue
        picked[cluster] = quote
        if cluster in counted:
            order.append(cluster)
    order += [c for c in counted if c not in picked]

    items: list[EvidenceItem] = []
    for cluster in order:
        answer = per_cluster.get(cluster)
        quote = picked.get(cluster)
        if quote is not None:
            sentence_id = quote.sentence_id
        elif answer is not None and answer.evidence:
            sentence_id = answer.evidence[0]
        else:
            continue
        if index.card(sentence_id) is None:
            continue
        items.append(
            EvidenceItem(
                cluster_id=cluster,
                sentence_id=sentence_id,
                writer_pick=quote is not None,
                translation=(
                    dict(quote.translation.values)
                    if quote is not None and quote.translation is not None
                    else None
                ),
                category=answer.answer_category if answer else None,
            )
        )
    return items


# --------------------------------------------------------------------------------------
# the annotation appendix — every question, both sides, every cluster
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClusterRow:
    """One cluster's annotated answer to one question."""

    cluster_id: str
    group_id: str
    addressed: bool
    category: Optional[str]
    summary: Optional[str]
    summary_lang: Optional[str]
    confidence: Optional[float]
    notes: Optional[str]
    evidence: list[str]
    source_id: str
    source_name: str
    publish_date: str
    articles: int


@dataclass(frozen=True)
class GroupRow:
    """One side's answer distribution for one question."""

    group_id: str
    clusters_total: int
    clusters_addressed: int
    category_counts: dict[str, int]
    top_categories: list[str]
    clusters: list[ClusterRow]

    @property
    def addressed_rate(self) -> float:
        return self.clusters_addressed / self.clusters_total if self.clusters_total else 0.0


@dataclass(frozen=True)
class QuestionRow:
    """One question as the appendix shows it: stats, ranking, and every annotation."""

    question_id: str
    text: dict
    tier: str
    kind: str
    stability: Optional[float]
    rate_diff: Optional[dict]
    groups: list[GroupRow]
    #: The best (lowest) rank of a finding on this question, if the analyze stage made one.
    finding_rank: Optional[int] = None
    finding_id: Optional[str] = None
    strength: Optional[str] = None
    secondary: bool = False
    interest: Optional[float] = None
    delta: Optional[dict] = None
    #: The storyline angle that used this question, if any.
    angle_rank: Optional[int] = None
    #: The question's attention_gap finding, when the analyze run emitted one alongside
    #: (or instead of) the modal finding.
    #: Keys: finding_id, rank, strength, stability, total_silence.
    attention_gap: Optional[dict] = None
    #: The side the analyze run called quiet — the lower observed answer rate.  Read it
    #: only alongside ``attention_gap``: the run records it whenever it computed a rate
    #: assertion, including the ones that did not fire.
    quiet_group: Optional[str] = None

    @property
    def sort_key(self) -> tuple:
        best_rank = min(
            (
                rank
                for rank in (
                    self.finding_rank,
                    (self.attention_gap or {}).get("rank"),
                )
                if rank is not None
            ),
            default=_NO_FINDING_RANK,
        )
        return (best_rank, -(self.interest or 0.0), self.question_id)


def modal_categories(category_counts: dict) -> list[str]:
    """The modal comparable categories, ties included — the analyze stage's own rule.

    Derived here rather than read off ``question_stats.json`` so a page pinned to an
    older analysis run still highlights the right answers (immutable runs are never
    rewritten; they are upgraded in memory).
    """
    comparable = {k: v for k, v in category_counts.items() if k != ANSWER_CATEGORY_UNCLEAR}
    maximum = max(comparable.values(), default=0)
    return sorted(k for k, v in comparable.items() if v == maximum and maximum > 0)


def build_question_rows(
    question_set: QuestionSet,
    question_stats: dict,
    findings: list[QAFinding],
    answers: AnswerIndex,
    index: SentenceIndex,
    page_angles: Iterable[AngleBlock] = (),
) -> list[QuestionRow]:
    """Every active question, in the analyze stage's own ranking order.

    "Interestingness" here is not a second opinion: it *is* the ranking the analyze stage
    computed (`rank`, which already folds strength, the secondary flag and the interest
    score), extended to the questions it produced no finding for — those come last, since
    nothing about them cleared the bar.
    """
    angle_by_question = {a.question_id: a.rank for a in page_angles}
    best_finding: dict[str, QAFinding] = {}
    gap_finding: dict[str, QAFinding] = {}
    for finding in findings:
        # attention_gap is tracked separately from the modal finding: qa-0.4.0 runs emit
        # at most one finding per question, but pre-0.4.0 runs could emit both and the
        # appendix must keep rendering those pages.
        if finding.kind == FindingKind.ATTENTION_GAP:
            gap_finding[finding.question_id] = finding
            continue
        current = best_finding.get(finding.question_id)
        if current is None or finding.rank < current.rank:
            best_finding[finding.question_id] = finding

    rows: list[QuestionRow] = []
    for question in question_set.active:
        stats = question_stats.get(question.question_id) or {}
        finding = best_finding.get(question.question_id)
        groups: list[GroupRow] = []
        for group_id, gstats in sorted((stats.get("groups") or {}).items()):
            # The row's own `clusters_total` / `clusters_addressed` come from the analyze
            # run, which since qa-0.5.0 counts the readable universe only.  The table
            # beneath them has to be that same set or it lists more reports than its own
            # header claims — which is exactly what the browser gate refuses.
            per_cluster = {
                cluster_id: answer
                for cluster_id, answer in answers.for_group(
                    question.question_id, group_id
                ).items()
                if cluster_id in index.readable_clusters
            }
            cluster_rows = []
            for cluster_id, answer in sorted(per_cluster.items()):
                card = next(
                    (index.card(sid) for sid in answer.evidence if index.card(sid)),
                    None,
                )
                cluster_rows.append(
                    ClusterRow(
                        cluster_id=cluster_id,
                        group_id=group_id,
                        addressed=answer.addressed,
                        category=answer.answer_category,
                        summary=answer.answer_summary.text if answer.answer_summary else None,
                        summary_lang=answer.answer_summary.lang if answer.answer_summary else None,
                        confidence=answer.confidence,
                        notes=answer.notes.text if answer.notes else None,
                        evidence=list(answer.evidence),
                        source_id=card.source_id if card else "",
                        source_name=card.source_name if card else "",
                        publish_date=card.publish_date if card else "",
                        articles=card.cluster_articles if card else 0,
                    )
                )
            groups.append(
                GroupRow(
                    group_id=group_id,
                    clusters_total=gstats.get("clusters_total") or 0,
                    clusters_addressed=gstats.get("clusters_addressed") or 0,
                    category_counts=dict(gstats.get("category_counts") or {}),
                    top_categories=(
                        list(gstats.get("top_categories"))
                        if gstats.get("top_categories")
                        else modal_categories(dict(gstats.get("category_counts") or {}))
                    ),
                    clusters=cluster_rows,
                )
            )
        gap = gap_finding.get(question.question_id)
        rows.append(
            QuestionRow(
                question_id=question.question_id,
                text=dict(question.text.values),
                tier=question.tier.value,
                kind=stats.get("kind") or "insufficient",
                stability=stats.get("stability"),
                rate_diff=stats.get("addressed_rate_diff"),
                quiet_group=stats.get("attention_gap_quiet_group"),
                groups=groups,
                finding_rank=finding.rank if finding else None,
                finding_id=finding.finding_id if finding else None,
                strength=finding.strength.value if finding else None,
                secondary=bool(finding.secondary) if finding else False,
                interest=finding.interest if finding else None,
                delta=finding.delta.model_dump(mode="json") if finding and finding.delta else None,
                angle_rank=angle_by_question.get(question.question_id),
                attention_gap=(
                    {
                        "finding_id": gap.finding_id,
                        "rank": gap.rank,
                        "strength": gap.strength.value,
                        "stability": gap.stability,
                        "total_silence": gap.total_silence,
                    }
                    if gap
                    else None
                ),
            )
        )
    rows.sort(key=lambda row: row.sort_key)
    return rows


def quoted_sentence_load(rows: Iterable[QuestionRow], extra: Iterable[str] = ()) -> dict:
    """How much of any single article the page would ship, as a fraction of its sentences.

    Non-negotiable 7 is "URL + verbatim sentence", not "a sentence budget", but an
    appendix that shows every anchor of every question can add up.  The renderer reports
    the worst article so the number is on the record rather than assumed harmless.
    """
    per_article: dict[str, set[str]] = {}
    for row in rows:
        for group in row.groups:
            for cluster in group.clusters:
                for sid in cluster.evidence:
                    per_article.setdefault(SentenceId.parse(sid).article_id, set()).add(sid)
    for sid in extra:
        per_article.setdefault(SentenceId.parse(sid).article_id, set()).add(sid)
    return {article_id: len(sids) for article_id, sids in per_article.items()}
