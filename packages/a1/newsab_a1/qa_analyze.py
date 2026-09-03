"""The analyze stage over Q×A answers (value_chain stage 4; assertion-based since the
analyze refactor).

Code only, end to end (non-negotiable 4): input is the annotate stage's answer records
plus an optional normalize-stage category map, output is a ranked candidate pool of
findings.  Every judgement an agent made upstream is frozen in the versioned category
map; every number here recomputes deterministically from (answers, category_map,
thresholds).  No LLM anywhere in this stage.

The statistical frame:

* **a finding is one concrete assertion** — "both sides' most common answer is X"
  (consensus), "A most often answers X while B most often answers Y" (divergence),
  "A barely addresses this question (rate below ``silent_max_rate``) while B addresses
  it at least ``attention_gap_min_abs_diff`` more" (attention_gap — the blindspot-like
  reading; a mere rate difference between two sides that both plainly speak is not a
  finding);
* **stability is the posterior probability that the assertion is true.**  The posterior
  comes from injecting pseudo-votes: category counts get a Dirichlet posterior with
  ``pseudo_total`` mass spread over the question's merged vocabulary plus one *unseen*
  slot (a draw where the unseen slot wins counts against every concrete assertion), and
  addressed rates get a Beta(addressed+1, unaddressed+1) posterior.  Small samples widen
  on their own — there are no hard sample-size thresholds anywhere;
* **the effect size is the posterior distribution of the asserted quantity**, computed
  from the same draws and anchored to the asserted categories;
* **"interesting" is an editorial judgement**: the mechanical ranking (significance
  gate, kind rotation, effect size) only orders the writer's candidate pool;
* **one question emits at most one finding.**  When the attention-gap assertion clears
  the weak gate the question's story *is* the gap: a modal assertion riding on the
  quiet side's one or two answers is suppressed (the counts stay in question_stats).
  The three kinds are disjoint readings of a question, never simultaneous.

Statistics count **readable** reporting clusters: the
statistical universe is the clusters with at least one ``access_level: full`` member.
A partial-only (title+lead) cluster leaves numerator and denominator together — it stays
in the corpus, the timeline and the sampled-but-unreadable counts, but retrievability
must never impersonate media attention.  The core/peripheral denominator lever stays
retired; ``topic_relevance`` remains on the corpus record as history.
Access levels live in the article store, not on the corpus run record, so the caller
reads the store and passes them in (old run records keep their bytes).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from newsab_schema.common import LangText, Provenance
from newsab_schema.enums import FindingKind, FindingStrength
from newsab_schema.ids import parse_prefixed_id
from newsab_schema.models.category_map import CategoryMap
from newsab_schema.models.corpus import CorpusRun
from newsab_schema.models.findings import FindingDelta, GroupAnswerStats, QAFinding
from newsab_schema.models.qa import ANSWER_CATEGORY_UNCLEAR, ClusterAnswer, QuestionSet
from newsab_schema.readability import split_clusters

PACKAGE_VERSION = "analyze-0.5.0"

_YEAR_SUFFIX = re.compile(r"-\d{4}$")

#: Emission order of the candidate pool's kind rotation (D-f).
_KIND_ROTATION = (FindingKind.DIVERGENCE, FindingKind.CONSENSUS, FindingKind.ATTENTION_GAP)

_STRENGTH_ORDER = {
    FindingStrength.SUPPORTED: 0,
    FindingStrength.WEAK: 1,
    FindingStrength.UNSUPPORTED: 2,
}


@dataclass(frozen=True)
class QAThresholds:
    """Versioned thresholds.  ``calibrated: true`` = the user signed these values on
    a calibration table.  The modal side is unchanged since 2026-08-22:
    ``pseudo_total=1`` with a 0.95/0.70 gate keeps "2 votes, both the same" at weak
    (0.925), one-vote leads (4:3, 30:29 ≈ 0.55–0.59) out of the pool, and full-vote
    divergences (≈0.99) supported.

    qa-0.5.0 (the user signed package **P3** on the calibration table — Jeffreys rate
    prior, ``silent_max_rate`` 0.20, the inherited 0.25 relative separation clause — so
    the defaults below *are* P3 and ``calibrated`` is true) changes only the attention-gap
    machinery, for reasons that are each an internal-consistency fix, not a tune-to-fire:

    * **prior alignment** — qa-0.4.0's rate posterior Beta(k+1, n−k+1) injected 2
      pseudo-votes while the modal machine injects ``pseudo_total``=1; under it the
      docstring's own design case ("one mention in six clusters is near-silent") had
      P≈0.15 against a 0.70 gate, so the silence tab was closed by the prior, not by
      data.  ``rate_pseudo_total`` (default = ``pseudo_total``) makes the rate prior
      Beta(k+m/2, n−k+m/2) — Jeffreys at m=1.
    * **``silent_max_rate``** moves to the region the design intent actually covers
      (candidates 0.15/0.20 on the table; 0.20 is the recommended P3 package).
    * **``loud_min_rate``** (experimental): when set, the
      separation clause becomes an *independent loud-side floor* — the joint assertion
      reads "quiet below ``silent_max_rate`` ∧ loud at least ``loud_min_rate``" and
      ``attention_gap_min_abs_diff`` is not consulted.  ``None`` keeps the earlier
      relative-difference clause.  Exactly one separation clause is ever in force.

    The attention gap stays one joint assertion whose stability passes the same
    0.95/0.70 gates as the modal kinds.  Changing any value is a calibration-track
    change: bump ``thresholds_version``, never tune in place to let a finding through.
    """

    thresholds_version: str = "qa-0.5.0"
    calibrated: bool = True
    #: Posterior draws per question (was ``n_resamples`` under the bootstrap).
    n_draws: int = 1000
    seed: int = 20260820
    interval_level: float = 0.90
    #: Total pseudo-vote mass per side and question, spread evenly over the question's
    #: merged vocabulary plus one unseen slot.  The small-sample penalty lives here.
    pseudo_total: float = 1.0
    #: supported / weak: the assertion's posterior probability alone decides.
    supported_min_probability: float = 0.95
    weak_min_probability: float = 0.70
    #: The attention-gap assertion's separation clause: the loud side out-addresses the
    #: quiet side by at least this much.  Part of what the assertion *says*, not a
    #: significance knob (the 25% value is inherited).  Ignored
    #: when ``loud_min_rate`` is set.
    attention_gap_min_abs_diff: float = 0.25
    #: The assertion's silence clause: the quiet side's addressed rate is below this.
    silent_max_rate: float = 0.20
    #: Pseudo-vote mass on the rate Beta prior, split evenly over addressed/silent
    #: (Beta(k+m/2, n−k+m/2)).  qa-0.4.0's uniform Beta(+1,+1) equals m=2; qa-0.5.0
    #: aligns with the modal machine's ``pseudo_total``=1 (Jeffreys).
    rate_pseudo_total: float = 1.0
    #: Experimental alternative separation clause: an absolute loud-side floor
    #: replacing the relative ``attention_gap_min_abs_diff``.  ``None`` = not in force.
    loud_min_rate: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QuestionGroupStats:
    """One side's counts for one question — the recomputable layer.

    ``category_counts`` are the **merged** (category-map-projected) counts every
    statistic and every downstream display eats; ``category_counts_raw`` keeps the
    annotate-stage spellings for audit and merge-sensitivity checks.  With no map (or
    no merges for this question) the two are identical.
    """

    group_id: str
    clusters_total: int
    clusters_addressed: int
    category_counts: dict[str, int]
    category_counts_raw: dict[str, int]
    #: Modal category among comparable (non-unclear) merged answers.
    top_category: Optional[str]
    #: All modal categories; more than one means the observed lead is tied (display
    #: metadata only — the assertion machine never branches on ties).
    top_categories: list[str]
    sample_evidence: list[str]

    @property
    def addressed_rate(self) -> float:
        return self.clusters_addressed / self.clusters_total if self.clusters_total else 0.0

    def comparable_counts(self) -> dict[str, int]:
        return {c: n for c, n in self.category_counts.items() if c != ANSWER_CATEGORY_UNCLEAR}

    def comparable_counts_raw(self) -> dict[str, int]:
        return {c: n for c, n in self.category_counts_raw.items() if c != ANSWER_CATEGORY_UNCLEAR}

    @property
    def top_category_tied(self) -> bool:
        return len(self.top_categories) > 1

    def to_record(self) -> GroupAnswerStats:
        return GroupAnswerStats(
            group_id=self.group_id,
            clusters_total=self.clusters_total,
            clusters_addressed=self.clusters_addressed,
            category_counts=dict(sorted(self.category_counts.items())),
            top_category=self.top_category,
            top_categories=self.top_categories,
            top_category_tied=self.top_category_tied,
            sample_evidence=self.sample_evidence,
        )


def _modes(counts: dict[str, int]) -> list[str]:
    """Every modal category, lexical only for stable serialization."""
    if not counts:
        return []
    maximum = max(counts.values())
    return sorted(category for category, count in counts.items() if count == maximum)


def _group_stats(
    group_id: str,
    clusters: Sequence[str],
    answers_by_cluster: dict[str, ClusterAnswer],
    project: Callable[[str], str],
    *,
    max_evidence: int = 3,
) -> QuestionGroupStats:
    addressed = [
        answers_by_cluster[c]
        for c in clusters
        if c in answers_by_cluster and answers_by_cluster[c].addressed
    ]
    raw_counts: dict[str, int] = {}
    counts: dict[str, int] = {}
    merged_of: dict[str, str] = {}
    for a in addressed:
        raw_counts[a.answer_category] = raw_counts.get(a.answer_category, 0) + 1
        merged = (
            ANSWER_CATEGORY_UNCLEAR
            if a.answer_category == ANSWER_CATEGORY_UNCLEAR
            else project(a.answer_category)
        )
        merged_of[a.answer_category] = merged
        counts[merged] = counts.get(merged, 0) + 1
    modes = _modes({c: n for c, n in counts.items() if c != ANSWER_CATEGORY_UNCLEAR})
    top = modes[0] if modes else None
    # Sample anchors: modal (merged) category first, then answers with more evidence
    # sentences, then id for a stable order.  Confidence is retired (D-b) and unread.
    ranked = sorted(
        addressed,
        key=lambda a: (merged_of[a.answer_category] != top, -len(a.evidence), a.answer_id),
    )
    evidence: list[str] = []
    for a in ranked:
        if a.evidence:
            evidence.append(a.evidence[0])
        if len(evidence) >= max_evidence:
            break
    return QuestionGroupStats(
        group_id=group_id,
        clusters_total=len(clusters),
        clusters_addressed=len(addressed),
        category_counts=counts,
        category_counts_raw=raw_counts,
        top_category=top,
        top_categories=modes,
        sample_evidence=evidence,
    )


# --- the posterior machine (D-d) ------------------------------------------------------


def _dirichlet_shares(rng: random.Random, alphas: Sequence[float]) -> list[float]:
    draws = [rng.gammavariate(a, 1.0) for a in alphas]
    total = sum(draws)
    return [d / total for d in draws]


def _beta_draw(rng: random.Random, successes: int, failures: int, pseudo_each: float) -> float:
    """Beta(successes+pseudo_each, failures+pseudo_each) via two Gammas — the rate
    posterior, with the prior mass a threshold (``rate_pseudo_total``/2 per slot)."""
    x = rng.gammavariate(successes + pseudo_each, 1.0)
    y = rng.gammavariate(failures + pseudo_each, 1.0)
    return x / (x + y)


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    return sorted_values[int(q * (len(sorted_values) - 1))]


def top_probability(
    counts: dict[str, int],
    thresholds: QAThresholds,
    rng: random.Random,
    *,
    extra_vocab: Sequence[str] = (),
) -> float:
    """P(the observed top stays the argmax) for one side's tally — the §5.1 recipe.

    Calibration/regression utility, not part of the finding machine: vocabulary is the
    tally's own categories (plus ``extra_vocab``) and one unseen slot, with
    ``pseudo_total`` mass spread evenly.  The observed top is the lexical-first modal
    category; a draw the unseen slot wins counts against it.
    """
    if not counts:
        return 0.0
    vocab = sorted(set(counts) | set(extra_vocab))
    k = len(vocab)
    pseudo = thresholds.pseudo_total / (k + 1)
    alphas = [counts.get(c, 0) + pseudo for c in vocab] + [pseudo]
    top_index = vocab.index(_modes(counts)[0])
    wins = 0
    for _ in range(thresholds.n_draws):
        shares = _dirichlet_shares(rng, alphas)
        if max(range(len(shares)), key=shares.__getitem__) == top_index:
            wins += 1
    return wins / thresholds.n_draws


@dataclass
class ModalAssertion:
    """The most probable (top_A, top_B) combination and its posterior probability."""

    kind: FindingKind  # CONSENSUS or DIVERGENCE
    top_a: str
    top_b: str
    #: P(argmax_A = top_a  ∧  argmax_B = top_b) under the pseudo-vote posterior.
    stability: float
    #: Effect-size draws for the asserted quantity (D-e), one per posterior draw.
    effect_draws: list[float]
    #: Observed effect size (from the merged counts, anchored to the assertion).
    effect_value: float

    @property
    def quantity(self) -> str:
        return (
            "consensus_dominance"
            if self.kind == FindingKind.CONSENSUS
            else "divergence_share_gap"
        )


def modal_assertion(
    counts_a: dict[str, int],
    counts_b: dict[str, int],
    thresholds: QAThresholds,
    rng: random.Random,
) -> Optional[ModalAssertion]:
    """The most probable top-answer combination for one question.

    ``counts_a`` / ``counts_b`` are one side's comparable (non-unclear) category counts.
    Returns ``None`` when a side has no comparable answers — an assertion about the most
    common answer of a side that gave none is not an assertion (``too_thin``).

    Each side gets a Dirichlet posterior over the question's shared vocabulary (the
    union of both sides' categories) plus one unseen slot; ``pseudo_total`` mass is
    spread evenly over vocabulary + unseen.  A draw in which the unseen slot wins a side
    counts against every concrete combination — that is what keeps "2 votes, both the
    same" from reading as certainty.
    """
    if not counts_a or not counts_b:
        return None
    vocab = sorted(set(counts_a) | set(counts_b))
    k = len(vocab)
    pseudo = thresholds.pseudo_total / (k + 1)
    alphas_a = [counts_a.get(c, 0) + pseudo for c in vocab] + [pseudo]
    alphas_b = [counts_b.get(c, 0) + pseudo for c in vocab] + [pseudo]

    combo_counts: dict[tuple[str, str], int] = {}
    shares_a: list[list[float]] = []
    shares_b: list[list[float]] = []
    for _ in range(thresholds.n_draws):
        sa = _dirichlet_shares(rng, alphas_a)
        sb = _dirichlet_shares(rng, alphas_b)
        shares_a.append(sa)
        shares_b.append(sb)
        ia = max(range(len(sa)), key=sa.__getitem__)
        ib = max(range(len(sb)), key=sb.__getitem__)
        if ia >= k or ib >= k:  # the unseen slot won a side: no concrete assertion holds
            continue
        combo_counts[(vocab[ia], vocab[ib])] = combo_counts.get((vocab[ia], vocab[ib]), 0) + 1
    if not combo_counts:
        return None
    (top_a, top_b), wins = min(combo_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    stability = wins / thresholds.n_draws

    idx_a, idx_b = vocab.index(top_a), vocab.index(top_b)
    total_a, total_b = sum(counts_a.values()), sum(counts_b.values())
    if top_a == top_b:
        kind = FindingKind.CONSENSUS
        effect_draws = [
            (sa[idx_a] + sb[idx_a]) / 2 for sa, sb in zip(shares_a, shares_b)
        ]
        effect_value = (counts_a.get(top_a, 0) / total_a + counts_b.get(top_a, 0) / total_b) / 2
    else:
        kind = FindingKind.DIVERGENCE
        effect_draws = [
            (abs(sa[idx_a] - sb[idx_a]) + abs(sa[idx_b] - sb[idx_b])) / 2
            for sa, sb in zip(shares_a, shares_b)
        ]
        effect_value = (
            abs(counts_a.get(top_a, 0) / total_a - counts_b.get(top_a, 0) / total_b)
            + abs(counts_a.get(top_b, 0) / total_a - counts_b.get(top_b, 0) / total_b)
        ) / 2
    return ModalAssertion(
        kind=kind,
        top_a=top_a,
        top_b=top_b,
        stability=stability,
        effect_draws=effect_draws,
        effect_value=effect_value,
    )


@dataclass
class RateAssertion:
    """The attention-gap assertion for one question (qa-0.4.0 semantics)."""

    #: Observed rate difference (A − B) with its posterior interval — always recorded
    #: in question_stats, whether or not an attention_gap fires.
    rate_delta: FindingDelta
    #: The side the assertion calls quiet (the observed lower addressed rate).
    quiet_group: str
    #: P(quiet rate < silent_max_rate  ∧  loud − quiet ≥ min_abs_diff) — one joint
    #: posterior probability, the attention_gap stability.  Compared against the same
    #: supported/weak gates as the modal kinds; nothing else decides.
    stability: float
    #: stability clears the weak gate — the question's finding is the gap.
    fires: bool
    #: The quiet side has zero addressed clusters (wording switch only).
    total_silence: bool


def rate_assertion(
    stats_a: QuestionGroupStats,
    stats_b: QuestionGroupStats,
    thresholds: QAThresholds,
    rng: random.Random,
) -> RateAssertion:
    """One joint assertion, one probability.

    The old two-part fire test (90% interval on the difference excluding zero, plus an
    observed-difference floor) composed two marginal checks into an untraceable overall
    confidence and made every firing gap auto-supported.  Here the assertion is a
    single event evaluated on paired posterior draws, so a gap can be weak, and the
    90% interval is demoted to reporting the effect size.
    """
    t = thresholds
    pseudo_each = t.rate_pseudo_total / 2
    pairs = [
        (
            _beta_draw(rng, stats_a.clusters_addressed, stats_a.clusters_total - stats_a.clusters_addressed, pseudo_each),
            _beta_draw(rng, stats_b.clusters_addressed, stats_b.clusters_total - stats_b.clusters_addressed, pseudo_each),
        )
        for _ in range(t.n_draws)
    ]
    diffs = sorted(ra - rb for ra, rb in pairs)
    value = stats_a.addressed_rate - stats_b.addressed_rate
    lo_q = (1 - t.interval_level) / 2
    lo, hi = _quantile(diffs, lo_q), _quantile(diffs, 1 - lo_q)
    rate_delta = FindingDelta(
        quantity="addressed_rate_diff",
        group_a=stats_a.group_id,
        group_b=stats_b.group_id,
        value=max(-1.0, min(1.0, value)),
        lo=max(-1.0, min(1.0, min(lo, value))),
        hi=max(-1.0, min(1.0, max(hi, value))),
        level=t.interval_level,
    )
    # The asserted quiet side is the observed lower rate; an exact tie asserts A quiet
    # (deterministic, and the separation clause makes the probability negligible).
    quiet, loud = (stats_b, stats_a) if value > 0 else (stats_a, stats_b)
    hits = 0
    for ra, rb in pairs:
        rq, rl = (rb, ra) if value > 0 else (ra, rb)
        if rq >= t.silent_max_rate:
            continue
        # Exactly one separation clause: the absolute loud-side floor when
        # ``loud_min_rate`` is set, the relative difference otherwise.
        if t.loud_min_rate is not None:
            if rl >= t.loud_min_rate:
                hits += 1
        elif rl - rq >= t.attention_gap_min_abs_diff:
            hits += 1
    stability = hits / t.n_draws
    fires = stability >= t.weak_min_probability
    return RateAssertion(
        rate_delta=rate_delta,
        quiet_group=quiet.group_id,
        stability=stability,
        fires=fires,
        total_silence=fires and quiet.clusters_addressed == 0,
    )


def _strength(stability: float, thresholds: QAThresholds) -> FindingStrength:
    """Two cuts on the assertion's posterior probability — nothing else (D-d)."""
    if stability >= thresholds.supported_min_probability:
        return FindingStrength.SUPPORTED
    if stability >= thresholds.weak_min_probability:
        return FindingStrength.WEAK
    return FindingStrength.UNSUPPORTED


# --- summaries (deterministic English pivot) ------------------------------------------


def _summary_modal(
    assertion: ModalAssertion,
    question_text: str,
    sa: QuestionGroupStats,
    sb: QuestionGroupStats,
) -> str:
    a, b = sa.group_id, sb.group_id
    ca, cb = sa.comparable_counts(), sb.comparable_counts()
    if assertion.kind == FindingKind.CONSENSUS:
        x = assertion.top_a
        return (
            f"On “{question_text}” both sampled coverages most often give the same "
            f"answer ‘{x}’ ({a}: {ca.get(x, 0)} of {sa.clusters_addressed}; {b}: "
            f"{cb.get(x, 0)} of {sb.clusters_addressed} addressing clusters)."
        )
    x, y = assertion.top_a, assertion.top_b
    return (
        f"On “{question_text}” the sampled {a} coverage most often answers ‘{x}’ "
        f"({ca.get(x, 0)} of {sa.clusters_addressed} addressing clusters) while the "
        f"sampled {b} coverage most often answers ‘{y}’ "
        f"({cb.get(y, 0)} of {sb.clusters_addressed} addressing clusters)."
    )


def _summary_attention_gap(
    question_text: str,
    sa: QuestionGroupStats,
    sb: QuestionGroupStats,
    total_silence: bool,
) -> str:
    def frac(s: QuestionGroupStats) -> str:
        return f"{s.clusters_addressed} of {s.clusters_total}"

    if total_silence:
        speaking, silent = (sa, sb) if sa.clusters_addressed else (sb, sa)
        return (
            f"{frac(speaking)} sampled {speaking.group_id} clusters address "
            f"“{question_text}”; no sampled {silent.group_id} cluster was annotated "
            "as addressing it. This is a statement about our annotation of the sampled "
            "coverage, not proof the answer appears nowhere."
        )
    return (
        f"The sampled {sa.group_id} coverage addresses “{question_text}” in {frac(sa)} "
        f"clusters, the sampled {sb.group_id} coverage in {frac(sb)}."
    )


# --- ranking (D-f) --------------------------------------------------------------------


@dataclass
class _Candidate:
    kind: FindingKind
    strength: FindingStrength
    stability: float
    delta: Optional[FindingDelta]
    merge_sensitive: bool
    total_silence: bool
    sa: QuestionGroupStats
    sb: QuestionGroupStats
    question_id: str
    summary: str

    @property
    def effect(self) -> float:
        return abs(self.delta.value) if self.delta is not None else 0.0


def _rotate(candidates: list[_Candidate]) -> list[_Candidate]:
    """Kind rotation: per round take each kind's current strongest, in rotation order."""
    queues: dict[FindingKind, list[_Candidate]] = {}
    for c in candidates:
        queues.setdefault(c.kind, []).append(c)
    for queue in queues.values():
        queue.sort(key=lambda c: (_STRENGTH_ORDER[c.strength], -c.effect, c.question_id))
    ordered: list[_Candidate] = []
    while any(queues.values()):
        for kind in _KIND_ROTATION:
            queue = queues.get(kind)
            if queue:
                ordered.append(queue.pop(0))
    return ordered


def _interval_from_draws(
    draws: list[float],
    quantity: str,
    value: float,
    group_a: str,
    group_b: str,
    thresholds: QAThresholds,
) -> FindingDelta:
    ordered = sorted(draws)
    lo_q = (1 - thresholds.interval_level) / 2
    lo, hi = _quantile(ordered, lo_q), _quantile(ordered, 1 - lo_q)
    return FindingDelta(
        quantity=quantity,
        group_a=group_a,
        group_b=group_b,
        value=max(-1.0, min(1.0, value)),
        lo=max(-1.0, min(1.0, min(lo, value))),
        hi=max(-1.0, min(1.0, max(hi, value))),
        level=thresholds.interval_level,
    )


def readable_clusters(
    corpus_run: CorpusRun, access_levels: Mapping[str, str]
) -> tuple[set[str], set[str]]:
    """Split the run's clusters into (readable, unreadable) — the statistical universe.

    The rule itself ("any member ``full``") lives in
    :mod:`newsab_schema.readability`, because the editorial stage has to draw the
    reader's evidence list from exactly the same set the badge was counted over.
    ``access_levels`` maps article_id → access level, read from the article store: the
    corpus run record does not carry the field.
    """
    return split_clusters(
        (article.reporting_cluster_id, access_levels.get(article.article_id))
        for article in corpus_run.articles
    )


# --- the run --------------------------------------------------------------------------


@dataclass
class QAAnalysisRun:
    qa_run_id: str
    topic_id: str
    groups: tuple[str, str]
    findings: list[QAFinding]
    question_stats: dict[str, dict]
    thresholds: QAThresholds
    inputs: dict[str, object] = field(default_factory=dict)

    def run_record(self) -> dict:
        return {
            "qa_run_id": self.qa_run_id,
            "topic_id": self.topic_id,
            "package_version": PACKAGE_VERSION,
            "groups": list(self.groups),
            "thresholds": self.thresholds.to_dict(),
            "inputs": self.inputs,
            "findings": len(self.findings),
        }


def analyse_qa(
    question_set: QuestionSet,
    answers: Sequence[ClusterAnswer],
    corpus_run: CorpusRun,
    *,
    topic_id: str,
    thresholds: Optional[QAThresholds] = None,
    category_map: Optional[CategoryMap] = None,
    access_levels: Optional[Mapping[str, str]] = None,
    answers_run_id: Optional[str] = None,
) -> QAAnalysisRun:
    thresholds = thresholds or QAThresholds()

    # The statistical universe is the readable
    # clusters.  A dropped cluster's answers leave the numerator with it — they are
    # simply never counted, which is what keeps numerator and denominator on the same
    # universe.  ``access_levels`` comes from the article store (the CLI always passes
    # it); ``None`` means the caller has no access information and every cluster
    # counts — unit-test territory, never the production path.
    # The core/peripheral lever stays retired, and the
    # ``peripheral_clusters_excluded`` input stays on the run record (always empty)
    # because downstream readers and old runs reference it.
    if access_levels is not None:
        counted, unreadable = readable_clusters(corpus_run, access_levels)
    else:
        counted = set(corpus_run.cluster_assignment.values())
        unreadable = set()

    clusters_by_group: dict[str, list[str]] = {}
    for cluster_id in sorted(counted):
        group_id = cluster_id.split("-")[1].lower()
        clusters_by_group.setdefault(group_id, []).append(cluster_id)
    if len(clusters_by_group) != 2:
        raise ValueError(
            f"Q×A analysis compares exactly two sides; corpus run has {sorted(clusters_by_group)}"
        )
    group_a, group_b = sorted(clusters_by_group)

    answers_by_question: dict[str, dict[str, ClusterAnswer]] = {}
    for answer in answers:
        answers_by_question.setdefault(answer.question_id, {})[
            answer.reporting_cluster_id
        ] = answer

    map_hash: Optional[str] = None
    if category_map is not None:
        map_hash = hashlib.sha256(
            category_map.model_dump_json(exclude_none=True).encode("utf-8")
        ).hexdigest()

    slug = _YEAR_SUFFIX.sub("", topic_id)
    payload = json.dumps(
        {
            "corpus": corpus_run.set_hash,
            "counted_clusters": sorted(counted),
            "questions": question_set.question_set_version,
            "answers": sorted(a.answer_id for a in answers),
            "category_map": map_hash,
            "thresholds": thresholds.to_dict(),
            "package": PACKAGE_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    qa_run_id = f"qa-{stamp}-{hashlib.sha256(payload.encode()).hexdigest()[:8]}"
    provenance = Provenance(
        skill_version=PACKAGE_VERSION,
        model_id=None,
        run_id=qa_run_id,
        timestamp=datetime.now(timezone.utc),
    )

    candidates: list[_Candidate] = []
    question_stats: dict[str, dict] = {}

    for offset, question in enumerate(question_set.active):
        by_cluster = answers_by_question.get(question.question_id, {})
        project: Callable[[str], str] = (
            (lambda c, qid=question.question_id: category_map.project(qid, c))
            if category_map is not None
            else (lambda c: c)
        )
        sa = _group_stats(group_a, clusters_by_group[group_a], by_cluster, project)
        sb = _group_stats(group_b, clusters_by_group[group_b], by_cluster, project)
        question_text = question.text.get("en") or question.question_id

        # Per-question rng offsets, one stream per sub-machine, reproducible (D-d).
        rng_modal = random.Random(thresholds.seed + 3 * offset)
        rng_rate = random.Random(thresholds.seed + 3 * offset + 1)
        rng_raw = random.Random(thresholds.seed + 3 * offset + 2)

        assertion = modal_assertion(
            sa.comparable_counts(), sb.comparable_counts(), thresholds, rng_modal
        )
        rates = rate_assertion(sa, sb, thresholds, rng_rate)

        modal_strength: Optional[FindingStrength] = None
        if assertion is not None:
            modal_strength = _strength(assertion.stability, thresholds)

        # One finding per question: a firing gap owns the question outright.  A modal
        # assertion that coexists with a near-silent side rides on that side's one or
        # two answers, and the pseudo-vote machine already caps such combinations
        # below supported — so the only thing this branch ever suppresses is weak.
        if rates.fires:
            candidates.append(
                _Candidate(
                    kind=FindingKind.ATTENTION_GAP,
                    strength=_strength(rates.stability, thresholds),
                    stability=rates.stability,
                    delta=rates.rate_delta,
                    merge_sensitive=False,  # rates never depend on category spellings
                    total_silence=rates.total_silence,
                    sa=sa,
                    sb=sb,
                    question_id=question.question_id,
                    summary=_summary_attention_gap(question_text, sa, sb, rates.total_silence),
                )
            )
        elif assertion is not None:
            # Merge-sensitivity flag (D-c): recompute the assertion from the raw counts;
            # if the kind or either asserted top changes (after projecting the raw tops
            # through the map), the writer must inspect both tallies.
            merge_sensitive = False
            raw_a, raw_b = sa.comparable_counts_raw(), sb.comparable_counts_raw()
            if raw_a != sa.comparable_counts() or raw_b != sb.comparable_counts():
                raw_assertion = modal_assertion(raw_a, raw_b, thresholds, rng_raw)
                merge_sensitive = (
                    raw_assertion is None
                    or raw_assertion.kind != assertion.kind
                    or project(raw_assertion.top_a) != assertion.top_a
                    or project(raw_assertion.top_b) != assertion.top_b
                )
            candidates.append(
                _Candidate(
                    kind=assertion.kind,
                    strength=modal_strength,
                    stability=assertion.stability,
                    delta=_interval_from_draws(
                        assertion.effect_draws,
                        assertion.quantity,
                        assertion.effect_value,
                        group_a,
                        group_b,
                        thresholds,
                    ),
                    merge_sensitive=merge_sensitive,
                    total_silence=False,
                    sa=sa,
                    sb=sb,
                    question_id=question.question_id,
                    summary=_summary_modal(assertion, question_text, sa, sb),
                )
            )

        # The honest per-question label (audit P10): the modal machine's outcome, with
        # no "insufficient" euphemism.  ``too_thin`` = a side has zero comparable
        # answers; ``no_significant_relation`` = a combination exists but its posterior
        # probability clears no gate.  When ``attention_gap`` is true the question's
        # emitted finding is the gap and this label only documents what the (suppressed)
        # modal machine saw.
        if assertion is None:
            kind_label = "too_thin"
        elif modal_strength == FindingStrength.UNSUPPORTED:
            kind_label = "no_significant_relation"
        else:
            kind_label = assertion.kind.value
        question_stats[question.question_id] = {
            "question": question_text,
            "tier": question.tier.value,
            "kind": kind_label,
            "stability": assertion.stability if assertion else 0.0,
            "attention_gap": rates.fires,
            "attention_gap_stability": round(rates.stability, 4),
            "attention_gap_quiet_group": rates.quiet_group,
            "addressed_rate_diff": rates.rate_delta.model_dump(mode="json"),
            "groups": {
                s.group_id: {
                    "clusters_total": s.clusters_total,
                    "clusters_addressed": s.clusters_addressed,
                    "category_counts": dict(sorted(s.category_counts.items())),
                    "category_counts_raw": dict(sorted(s.category_counts_raw.items())),
                    "top_category": s.top_category,
                    "top_categories": s.top_categories,
                    "top_category_tied": s.top_category_tied,
                }
                for s in (sa, sb)
            },
        }

    # D-f: the significance gate splits pool from appendix; each part is ordered by the
    # same kind rotation.  ``rank`` is the candidate order — page order and selection
    # belong to the write stage.
    pool = [c for c in candidates if c.strength != FindingStrength.UNSUPPORTED]
    appendix = [c for c in candidates if c.strength == FindingStrength.UNSUPPORTED]
    ordered = _rotate(pool) + _rotate(appendix)

    findings: list[QAFinding] = []
    for rank, c in enumerate(ordered, start=1):
        serial = parse_prefixed_id(c.question_id, "QST").serial
        findings.append(
            QAFinding(
                # Identity decoupled from rank (audit P15): question serial + kind, so a
                # re-run never renames a finding.
                finding_id=f"FND-{slug}-{serial:03d}-{c.kind.value}",
                topic_id=topic_id,
                question_id=c.question_id,
                kind=c.kind,
                strength=c.strength,
                secondary=False,
                rank=rank,
                interest=None,
                groups=[c.sa.to_record(), c.sb.to_record()],
                delta=c.delta,
                stability=round(c.stability, 4),
                merge_sensitive=c.merge_sensitive,
                total_silence=c.total_silence,
                summary=LangText(text=c.summary, lang="en"),
                thresholds_version=thresholds.thresholds_version,
                provenance=provenance,
            )
        )

    inputs: dict[str, object] = {
        "corpus_run_id": corpus_run.run_id,
        "corpus_set_hash": corpus_run.set_hash,
        "question_set_version": question_set.question_set_version,
        # Name the answers run this analysis read.  Every other upstream artifact
        # is on the record by id or hash; the answers were only recoverable by looking up
        # which run happened to be active in the manifest when this one ran, which stops
        # being true the moment a later answers run is activated.  The CLI always passes
        # it; ``None`` is unit-test territory.
        "answers_run_id": answers_run_id,
        # Kept on the record for continuity with pre-refactor runs; the core/peripheral
        # lever is retired, so that exclusion list is empty by construction.
        "counted_clusters": len(counted),
        "peripheral_clusters_excluded": [],
        # Sampled but unreadable — out of every statistic, still in the corpus.
        "unreadable_clusters_excluded": sorted(unreadable),
    }
    if category_map is not None:
        inputs["category_map_run_id"] = category_map.provenance.run_id
        inputs["category_map_hash"] = map_hash

    return QAAnalysisRun(
        qa_run_id=qa_run_id,
        topic_id=topic_id,
        groups=(group_a, group_b),
        findings=findings,
        question_stats=question_stats,
        thresholds=thresholds,
        inputs=inputs,
    )


def write_qa_run(run: QAAnalysisRun, analysis_dir: Path) -> Path:
    """Write the immutable run directory: findings.jsonl + question_stats.json + run.json."""
    run_dir = analysis_dir / run.qa_run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    with open(run_dir / "findings.jsonl", "w", encoding="utf-8") as fh:
        for finding in run.findings:
            fh.write(finding.model_dump_json() + "\n")
    (run_dir / "question_stats.json").write_text(
        json.dumps(run.question_stats, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "run.json").write_text(
        json.dumps(run.run_record(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run_dir
