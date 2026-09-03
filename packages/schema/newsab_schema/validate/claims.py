"""§4.5 invariants and the character-exact quote check (§2.5, §3.3 S8-L0).

The quote check is the load-bearing one: §2.5 promises a reader that pasting the quoted
sentence into the original page will find it.  Everything else on the site depends on that
promise being mechanically true rather than usually true.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from ..enums import ClaimType, LintVerdict
from ..lints import check_quantifier, lint_text
from ..models.analysis import CandidateAngle, Claim
from ..models.corpus import Article
from .report import ValidationReport


def validate_claims(
    claims: Sequence[Claim],
    articles: Iterable[Article],
    angles: Optional[Sequence[CandidateAngle]] = None,
) -> ValidationReport:
    """Check evidence anchors, provenance paths, scope/causal lints and quantifier bounds."""
    report = ValidationReport()
    by_article = {a.article_id: a for a in articles}
    by_angle = {a.angle_id: a for a in (angles or [])}
    seen: set[str] = set()

    for claim in claims:
        target = claim.claim_id
        if claim.claim_id in seen:
            report.error("duplicate_claim_id", target, "claim_id used twice")
        seen.add(claim.claim_id)

        angle = by_angle.get(claim.angle_id)
        if angles is not None and angle is None:
            report.error(
                "unknown_angle", target, f"claim references angle {claim.angle_id}, which is absent"
            )

        for sid in claim.evidence:
            article_id = sid.split(":", 1)[0]
            article = by_article.get(article_id)
            if article is None:
                report.error(
                    "evidence_article_missing", target, f"{sid} points at an unknown article"
                )
            elif not article.has_sentence(sid):
                report.error(
                    "evidence_anchor_missing", target, f"{sid} does not exist in {article_id}"
                )

        if claim.claim_type == ClaimType.CORPUS_AGGREGATE and angle is not None:
            expected_prefix = f"{claim.angle_id}."
            if not claim.computed_from.startswith(expected_prefix):
                report.error(
                    "computed_from_mismatch",
                    target,
                    f"computed_from={claim.computed_from!r} does not point into "
                    f"{claim.angle_id}'s metrics",
                )

        # Scope and causal lints on every reader-facing language version (§3.3 S8).
        for lang, text in claim.text.values.items():
            for finding in lint_text(text, lang, profile="editorial_sentence"):
                severity = "error" if finding.verdict == LintVerdict.FAIL else "warning"
                report.add(
                    severity,
                    f"lint_{finding.rule}",
                    f"{target}[{lang}]",
                    f"{finding.message} (matched {finding.matched!r})",
                    finding.suggestion,
                )

        # Quantifier binding.  Only aggregates carry numbers to bind to; for a source claim
        # the quantifier belongs to the speaker, not to us.  The wording is bound to the
        # magnitude of the signed difference (|Δ|, the page's headline gap).
        if claim.claim_type == ClaimType.CORPUS_AGGREGATE and angle is not None:
            divergence = abs(angle.metrics.delta.value)
            prevalences = [
                g.prevalence for g in angle.comparison.groups if g.prevalence is not None
            ]
            for lang, text in claim.text.values.items():
                findings = check_quantifier(
                    text,
                    lang,
                    prevalence=max(prevalences) if prevalences else None,
                    divergence=divergence,
                )
                for finding in findings:
                    severity = "error" if finding.verdict == LintVerdict.FAIL else "warning"
                    report.add(
                        severity,
                        f"lint_{finding.rule}",
                        f"{target}[{lang}]",
                        finding.message,
                        finding.suggestion,
                    )
            if claim.quantifier_check is None:
                report.warning(
                    "quantifier_check_absent",
                    target,
                    "an aggregate claim with no recorded quantifier_check",
                    "record which phrase was bound to which metric (§4.5)",
                )

        # A reading has no magnitude, so any quantifier in it is a number the page cannot
        # back.  `check_quantifier` with nothing to bind to returns FLAG for every
        # quantifier phrase it finds; here that is an error, not a flag — this claim type
        # exists precisely so "what the two sides answer" can never borrow the authority of
        # "how often they say it".
        if claim.claim_type == ClaimType.CORPUS_READING:
            for lang, text in claim.text.values.items():
                for finding in check_quantifier(text, lang):
                    report.error(
                        "reading_carries_quantifier",
                        f"{target}[{lang}]",
                        f"{finding.matched!r} quantifies a reading that nothing measured",
                        "say what the sides answer, or move the sentence to a "
                        "corpus_aggregate claim that cites the metric",
                    )
            groups = {sid.split("_", 1)[0] for sid in claim.evidence}
            if len(groups) < 2:
                report.warning(
                    "reading_is_one_sided",
                    target,
                    "every anchor of this reading comes from one side's articles",
                    "a cross-side reading should quote both sides; a one-side "
                    "characterisation belongs on that side's angle card (S5)",
                )

    report.stats["claims"] = len(claims)
    report.stats["aggregate_claims"] = sum(
        1 for c in claims if c.claim_type == ClaimType.CORPUS_AGGREGATE
    )
    report.stats["reading_claims"] = sum(
        1 for c in claims if c.claim_type == ClaimType.CORPUS_READING
    )
    return report


def verify_quote(article: Article, sentence_id: str, quoted_text: str) -> bool:
    """Character-exact match between a published quote and the stored sentence (§2.5).

    No normalisation of any kind: whitespace and punctuation differences are exactly what
    breaks a reader's Ctrl-F, so they have to fail here.
    """
    return article.has_sentence(sentence_id) and article.sentence_text(sentence_id) == quoted_text
