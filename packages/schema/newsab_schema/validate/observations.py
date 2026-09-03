"""§4.2.2 invariants — the checks S8 L0 will re-run on any submission.

These are cross-record checks: the model layer already enforces everything that can be
decided from one record alone (evidence non-empty, same article, attrs per dimension).
What needs the corpus is here.
"""

from __future__ import annotations

import statistics
from typing import Iterable, Optional, Sequence

from ..enums import LintVerdict
from ..ids import SentenceId
from ..lints import lint_text
from ..models.annotation import ArticleAnnotation, ConceptOntology, Observation
from ..models.corpus import Article
from .report import ValidationReport

#: Per-article observation counts the blueprint calls normal for a dense article (§4.2.2
#: invariant 5).  Outside this band is a *warning*, never an error: a two-sentence wire
#: brief legitimately yields two observations, and a hard floor would push an annotator
#: into inventing them.
EXPECTED_OBS_PER_ARTICLE = (10, 30)


def validate_observations(
    observations: Sequence[Observation],
    articles: Iterable[Article],
    ontology: Optional[ConceptOntology] = None,
    *,
    expected_range: tuple[int, int] = EXPECTED_OBS_PER_ARTICLE,
) -> ValidationReport:
    """Check every §4.2.2 invariant that needs the corpus, plus the distribution stats.

    ``ontology`` is optional because S4 runs annotation before normalisation; pass it once
    normalisation has run and invariant 3 becomes checkable.
    """
    report = ValidationReport()
    by_id = {a.article_id: a for a in articles}
    report.stats["articles"] = len(by_id)
    report.stats["observations"] = len(observations)

    seen_ids: set[str] = set()
    per_article: dict[str, int] = {aid: 0 for aid in by_id}
    dimension_counts: dict[str, int] = {}
    evidence_total = 0

    for obs in observations:
        target = obs.observation_id

        if obs.observation_id in seen_ids:
            report.error("duplicate_observation_id", target, "observation_id used twice")
        seen_ids.add(obs.observation_id)

        article = by_id.get(obs.article_id)
        if article is None:
            report.error(
                "unknown_article",
                target,
                f"references article {obs.article_id} which is not in the corpus",
                "run this against the same corpus version S4 annotated",
            )
            continue

        per_article[obs.article_id] = per_article.get(obs.article_id, 0) + 1
        dimension_counts[obs.dimension.value] = dimension_counts.get(obs.dimension.value, 0) + 1
        evidence_total += len(obs.evidence)

        # Invariant 1 — every anchor exists in this article's structured text.
        for sid in obs.evidence:
            if not article.has_sentence(sid):
                report.error(
                    "evidence_anchor_missing",
                    target,
                    f"{sid} does not exist in {obs.article_id}",
                    "sentence IDs come from the S2 split; do not hand-write them",
                )

        # Invariant 4 — the proposition is written in the article's language (D6).
        if obs.proposition.lang != article.lang:
            report.error(
                "proposition_language_mismatch",
                target,
                f"proposition.lang={obs.proposition.lang} but article language is {article.lang}",
                "single-side processing stays in the source's own language (§1.6 L1)",
            )

        # Invariant 2 — descriptive, not explanatory or adjudicating.
        for finding in lint_text(
            obs.proposition.text, obs.proposition.lang, profile="observation_proposition"
        ):
            severity = "error" if finding.verdict == LintVerdict.FAIL else "warning"
            report.add(
                severity,
                f"lint_{finding.rule}",
                target,
                f"{finding.message} (matched {finding.matched!r})",
                finding.suggestion,
            )

        # quoted_voice evidence should point at the quoting sentence itself (§4.2.1).
        if obs.dimension.value == "quoted_voice" and all(
            SentenceId.parse(s).is_title for s in obs.evidence
        ):
            report.warning(
                "quoted_voice_headline_only",
                target,
                "a quoted-voice observation anchored only to the headline block",
                "anchor to the sentence carrying the quote",
            )

    if ontology is not None:
        report.extend(validate_ontology_against(observations, ontology))

    # Invariant 5 — distribution, reported rather than enforced.
    counts = [n for n in per_article.values()]
    if counts:
        low, high = expected_range
        report.stats["obs_per_article_mean"] = round(statistics.fmean(counts), 2)
        report.stats["obs_per_article_median"] = statistics.median(counts)
        report.stats["obs_per_article_min"] = min(counts)
        report.stats["obs_per_article_max"] = max(counts)
        report.stats["evidence_per_observation"] = (
            round(evidence_total / len(observations), 2) if observations else 0
        )
        report.stats["dimension_counts"] = dict(sorted(dimension_counts.items()))

        empty = sorted(a for a, n in per_article.items() if n == 0)
        if empty:
            report.warning(
                "article_without_observations",
                ",".join(empty[:10]) + ("…" if len(empty) > 10 else ""),
                f"{len(empty)} article(s) produced no observations",
                "if an article really says nothing on any dimension, record that in the run "
                "log — silence is data, but unexplained silence is a bug (D5)",
            )
        outliers = sorted(a for a, n in per_article.items() if n and not (low <= n <= high))
        if outliers:
            report.info(
                "obs_count_outside_expected_band",
                f"{len(outliers)} article(s)",
                f"observation counts outside the {low}–{high} band expected for a dense "
                f"article: {', '.join(f'{a}={per_article[a]}' for a in outliers[:10])}",
            )

    return report


def validate_ontology_against(
    observations: Sequence[Observation], ontology: ConceptOntology
) -> ValidationReport:
    """Invariant 3 plus §4.3's "every surface maps to exactly one concept".

    The subtle half is that normalisation must not *rewrite* anything: every surface listed
    in the ontology has to appear verbatim in some observation.  A surface that appears
    nowhere means the normaliser paraphrased, and the audit trail is broken.
    """
    report = ValidationReport()
    observed = {(o.concept_surface, o.proposition.lang) for o in observations}
    mapped = ontology.surface_map()

    unmapped = sorted({key for key in observed if key not in mapped})
    for surface, lang in unmapped:
        report.error(
            "surface_not_mapped",
            f"{surface!r}({lang})",
            "concept_surface has no concept_id in the ontology",
            "every surface must map to exactly one concept before analysis (§4.3); "
            "self-mapping is fine",
        )

    invented = sorted({key for key in mapped if key not in observed})
    for surface, lang in invented:
        report.error(
            "surface_not_observed",
            f"{surface!r}({lang})",
            "the ontology lists a surface that appears in no observation",
            "normalisation may add mappings but must never rewrite concept_surface "
            "(§4.2.2 invariant 3)",
        )

    report.stats["concepts"] = len(ontology.concepts)
    report.stats["surfaces_mapped"] = len(mapped)
    report.stats["distinct_surfaces_observed"] = len(observed)
    if mapped:
        report.stats["merge_ratio"] = round(len(mapped) / max(len(ontology.concepts), 1), 2)
    return report


def validate_article_annotations(
    annotations: Sequence[ArticleAnnotation], articles: Iterable[Article]
) -> ValidationReport:
    """Article-level notes: anchors exist, one annotation per article, no orphans."""
    report = ValidationReport()
    by_id = {a.article_id: a for a in articles}
    seen: set[str] = set()

    for ann in annotations:
        if ann.article_id in seen:
            report.error(
                "duplicate_article_annotation", ann.article_id, "annotated more than once"
            )
        seen.add(ann.article_id)
        article = by_id.get(ann.article_id)
        if article is None:
            report.error(
                "unknown_article", ann.article_id, "annotation for an article not in the corpus"
            )
            continue
        for note in ann.notable_language:
            if not article.has_sentence(note.sentence):
                report.error(
                    "notable_language_anchor_missing",
                    ann.article_id,
                    f"{note.sentence} does not exist in {ann.article_id}",
                )
            elif note.phrase not in article.sentence_text(note.sentence):
                report.error(
                    "notable_language_not_verbatim",
                    ann.article_id,
                    f"phrase {note.phrase!r} does not occur in {note.sentence}",
                    "notable_language must quote the article character-for-character (D14)",
                )

    missing = sorted(set(by_id) - seen)
    if missing:
        report.info(
            "article_without_annotation",
            f"{len(missing)} article(s)",
            "articles with observations but no article-level annotation: "
            + ", ".join(missing[:10]),
        )
    report.stats["article_annotations"] = len(annotations)
    return report
