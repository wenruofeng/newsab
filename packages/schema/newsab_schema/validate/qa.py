"""Cross-record invariants of the Q×A annotation layer (V-1).

The model layer enforces what one record can know about itself (addressed ⇒ summary +
category + anchors; group consistency; ID grammar).  What needs the corpus and the
question set is here:

* every answer names a question the set knows, and pins the set's version;
* every anchor exists verbatim in the corpus and belongs to an article that the corpus
  run assigns to the answer's cluster;
* coverage is complete: every (active question × reporting cluster) pair has exactly
  one answer — a missing pair is indistinguishable from silence, and silence must be a
  recorded judgement, never an accident of an unfinished pass;
* answer summaries are language-tagged; current annotation runs use English pivot so a
  semantically defined group may contain articles in several source languages.

These are what the pre-review mechanical checks re-run; run them before writing a run
directory (artifact_versioning §2: a check that would refuse at the end must run in the dry-run).
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence

from ..ids import SentenceId
from ..models.corpus import Article
from ..models.qa import ClusterAnswer, QuestionSet
from .report import ValidationReport


def validate_answers(
    answers: Sequence[ClusterAnswer],
    question_set: QuestionSet,
    articles: Iterable[Article],
    *,
    cluster_assignment: Optional[Mapping[str, str]] = None,
    scope_questions: Optional[Iterable[str]] = None,
    retexted_anchors: Optional[Iterable[str]] = None,
) -> ValidationReport:
    """Check the answer set against its question set and corpus.

    ``cluster_assignment`` maps ``article_id -> reporting_cluster_id`` as pinned by the
    corpus run; when given, coverage and cluster-membership checks run against it.

    ``scope_questions`` narrows the coverage check to those question IDs.  An incremental
    pass that answers only new questions across existing clusters is complete when its own
    questions are covered; without this it is measured against every active question and
    can never come back clean, which pushes each worker into inventing its own workaround
    for reading the result.

    ``retexted_anchors`` are fully-qualified sentence IDs that a rebuild kept at the same
    address while changing their text, as recorded in the corpus run's
    ``build_report["anchor_delta"]``.  They are the one kind of anchor damage no other
    check can see: the ID resolves, so ``dangling_anchor`` stays silent, and the answer
    now cites a different sentence than the one it was written against.  Only the build
    that produced both generations knows which addresses moved, so it says, and this
    refuses them.
    """
    report = ValidationReport()
    by_article = {a.article_id: a for a in articles}
    questions = {q.question_id: q for q in question_set.questions}
    active_ids = {q.question_id for q in question_set.active}

    report.stats["answers"] = len(answers)
    report.stats["questions"] = len(question_set.questions)
    report.stats["active_questions"] = len(active_ids)

    clusters: set[str] = set()
    if cluster_assignment is not None:
        clusters = set(cluster_assignment.values())
        report.stats["clusters"] = len(clusters)

    moved = set(retexted_anchors or ())
    seen_ids: set[str] = set()
    seen_pairs: dict[tuple[str, str], str] = {}
    addressed_count = 0

    for answer in answers:
        target = answer.answer_id

        if answer.answer_id in seen_ids:
            report.error("duplicate_answer_id", target, "answer_id used twice")
        seen_ids.add(answer.answer_id)

        if answer.topic_id != question_set.topic_id:
            report.error(
                "wrong_topic", target, f"answer declares topic {answer.topic_id!r}"
            )

        question = questions.get(answer.question_id)
        if question is None:
            report.error(
                "unknown_question",
                target,
                f"{answer.question_id} is not in question set "
                f"{question_set.question_set_version}",
            )
        elif answer.question_id not in active_ids:
            report.warning(
                "retired_question",
                target,
                f"{answer.question_id} is retired; this answer is history, not input",
            )

        if answer.question_set_version != question_set.question_set_version:
            report.error(
                "question_set_mismatch",
                target,
                f"answer pins question set {answer.question_set_version!r}, validating "
                f"against {question_set.question_set_version!r}",
            )

        pair = (answer.question_id, answer.reporting_cluster_id)
        if pair in seen_pairs:
            report.error(
                "duplicate_pair",
                target,
                f"cluster {answer.reporting_cluster_id} already answered "
                f"{answer.question_id} in {seen_pairs[pair]}",
            )
        seen_pairs[pair] = answer.answer_id

        if cluster_assignment is not None and answer.reporting_cluster_id not in clusters:
            report.error(
                "unknown_cluster",
                target,
                f"{answer.reporting_cluster_id} is not a cluster of this corpus run",
            )

        if answer.addressed:
            addressed_count += 1

        for sid in answer.evidence:
            parsed = SentenceId.parse(sid)
            article = by_article.get(parsed.article_id)
            if article is None:
                report.error(
                    "unknown_article", target, f"anchor {sid} points outside the corpus"
                )
                continue
            if not article.has_sentence(sid):
                report.error(
                    "dangling_anchor", target, f"anchor {sid} does not exist in the article"
                )
            elif sid in moved:
                report.error(
                    "retexted_anchor",
                    target,
                    f"anchor {sid} still resolves but the rebuild changed the text at that "
                    "address; this answer now cites a sentence it was not written against, "
                    "and re-reading the cluster is the only fix",
                )
            if cluster_assignment is not None:
                actual = cluster_assignment.get(parsed.article_id)
                if actual is not None and actual != answer.reporting_cluster_id:
                    report.error(
                        "anchor_outside_cluster",
                        target,
                        f"anchor {sid} belongs to cluster {actual}, not "
                        f"{answer.reporting_cluster_id}",
                    )

    report.stats["addressed"] = addressed_count

    # -- coverage: every active question × cluster pair, exactly once --------------------
    if cluster_assignment is not None:
        required_questions = set(active_ids)
        if scope_questions is not None:
            wanted = set(scope_questions)
            unknown = sorted(wanted - active_ids)
            for question_id in unknown:
                report.error(
                    "unknown_scope_question",
                    question_id,
                    "named in the coverage scope but not an active question",
                )
            required_questions &= wanted
        missing: list[str] = []
        for question_id in sorted(required_questions):
            for cluster_id in sorted(clusters):
                if (question_id, cluster_id) not in seen_pairs:
                    missing.append(f"{question_id} × {cluster_id}")
        for gap in missing:
            report.error(
                "coverage_gap",
                gap,
                "no answer recorded — silence must be an explicit addressed=false "
                "judgement, never a hole in the pass",
            )
        report.stats["coverage_gaps"] = len(missing)

    return report
