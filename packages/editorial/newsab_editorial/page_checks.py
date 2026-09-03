"""Pre-render mechanical checks for a value-chain ReaderPage.

Everything the old S8 L0 layer would refuse at the end now runs *before* a run
directory is written (artifact_versioning §2: a check that can only fire after the fact costs a
run id every time it fires).  The write skill runs these on its draft; the
render+localize stage runs them again on the final artifact plus the
language-completeness check for the reviewer's language.

All deterministic; no model anywhere.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from newsab_schema.enums import ClaimType, FindingKind, FindingStrength
from newsab_schema.ids import SentenceId
from newsab_schema.models.corpus import Article
from newsab_schema.models.findings import QAFinding
from newsab_schema.models.page import AngleBlock, CountBadge, PageClaim, ReaderPage
from newsab_schema.readability import readable_clusters_of_articles

from . import concept_cloud
from .evidence import AnswerIndex, badge_selector, counted_clusters

#: The provenance a fresh ``page_init.py`` draft carries.  Values, not a convention:
#: the draft script imports these so the two can never drift apart.
PLACEHOLDER_RUN_ID = "edt-19700101000000000000-00000000"
PLACEHOLDER_MODEL_ID = "TODO"

_NUMBER = re.compile(r"\d[\d,.]*")
#: Number-words that smuggle a magnitude past the digit check.
_QUANT_WORDS = re.compile(
    r"\b(all|none|no|every|most|majority|half|twice|double)\b", re.IGNORECASE
)


@dataclass
class PageCheckReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = [
            f"page checks: {len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        ]
        lines += [f"  ERROR: {e}" for e in self.errors]
        lines += [f"  warn:  {w}" for w in self.warnings]
        for key, value in sorted(self.stats.items()):
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)


def _sentence_map(articles: Iterable[Article]) -> dict[str, Article]:
    return {a.article_id: a for a in articles}


def _iter_claims(page: ReaderPage):
    for claim in page.intro:
        yield "intro", claim
    if page.hook is not None:
        yield "hook", page.hook
    for angle in page.angles:
        for side in angle.sides:
            yield f"angle {angle.rank} ({side.group_id})", side.answer
        for claim in angle.detail:
            yield f"angle {angle.rank} detail", claim
        if angle.commentary_joint is not None:
            yield f"angle {angle.rank} joint", angle.commentary_joint


def _check_anchor(
    out: PageCheckReport, where: str, sid: str, by_article: dict[str, Article]
) -> None:
    article = by_article.get(SentenceId.parse(sid).article_id)
    if article is None:
        out.errors.append(f"{where}: anchor {sid} points outside the pinned corpus run")
    elif not article.has_sentence(sid):
        out.errors.append(f"{where}: anchor {sid} does not exist in its article")


#: A writer's inline footnote marker (``[^1]``), which the renderer turns into a
#: superscript link. It is punctuation, not a quantity, so it leaves before the digit
#: rules run — otherwise a marker would make a ``corpus_reading`` claim "carry a number".
_FOOTNOTE_MARK = re.compile(r"\[\^\d{1,2}\]")
#: The same marker with its number in hand, for checking what it points at.
_FOOTNOTE_INDEX = re.compile(r"\[\^(\d{1,2})\]")


def _digits(text: str) -> list[str]:
    r"""Numbers in the text, without the sentence punctuation stuck to them.

    ``\d[\d,.]*`` swallows a trailing comma or full stop, so "in 2025, warnings…" yields
    ``2025,`` — a token that appears in no anchored sentence and would fail the verbatim
    check purely because of where the clause ended. A number never *ends* in a separator,
    so trailing ones are always punctuation.
    """
    plain = _FOOTNOTE_MARK.sub("", text)
    return [n.rstrip(",.") for n in _NUMBER.findall(plain) if n.rstrip(",.")]


def _finding_numbers(finding: QAFinding) -> set[str]:
    """Every integer a badge or aggregate sentence may legitimately restate."""
    numbers: set[str] = set()
    for g in finding.groups:
        numbers.update(
            str(v)
            for v in (
                g.clusters_total,
                g.clusters_addressed,
                *(g.category_counts or {}).values(),
            )
        )
    return numbers


def check_page(
    page: ReaderPage,
    articles: Iterable[Article],
    findings: list[QAFinding],
    question_stats: Optional[dict] = None,
    *,
    answers: Optional[AnswerIndex] = None,
    required_langs: tuple[str, ...] = ("en",),
    pinned_corpus_run: Optional[str] = None,
    pinned_qa_run: Optional[str] = None,
    manifest=None,
    topics_by_article: Optional[dict] = None,
) -> PageCheckReport:
    out = PageCheckReport()
    by_article = _sentence_map(articles)
    # The badge is counted over the readable universe (qa-0.5.0), so the evidence check
    # below has to draw from the same set or it compares two different denominators.
    readable = readable_clusters_of_articles(by_article.values())
    by_finding = {f.finding_id: f for f in findings}
    out.stats["angles"] = len(page.angles)

    # The page's own account of where its numbers came from.  Every other check verifies
    # that a number recomputes; this one verifies that the page names the run it recomputes
    # *from*.  A page carried forward onto a new analysis keeps its old `how_we_counted`
    # unless someone moves it, and then every figure is right while the page's statement of
    # its own provenance is false — which is the one thing "recomputable from a stored run
    # id" cannot survive, and the one thing no recomputation can notice.
    if pinned_corpus_run and page.how_we_counted.corpus_run_id != pinned_corpus_run:
        out.errors.append(
            f"how_we_counted names corpus run {page.how_we_counted.corpus_run_id} but the "
            f"pinned analysis run analysed {pinned_corpus_run}; the page's numbers and its "
            "account of where they came from disagree"
        )
    # The same defect one run upstream, and the more likely one: `repin_page.py` moves the
    # findings and the badges onto a new analyze run, and a page whose `qa_run_id` was not
    # moved with them names a run whose finding numbering is not the one its cards use.
    if pinned_qa_run and page.how_we_counted.qa_run_id != pinned_qa_run:
        out.errors.append(
            f"how_we_counted names analysis run {page.how_we_counted.qa_run_id} but every "
            f"number on this page is checked against {pinned_qa_run}"
        )
    # ``page_init.py`` stamps placeholder provenance into every draft.  Nothing else
    # looks at it until the publish stage refuses the page — after the run is finalized
    # and immutable, when the only remedy is a whole new run — so the placeholder is
    # refused here, while it is still one edit.
    if page.provenance.run_id == PLACEHOLDER_RUN_ID:
        out.errors.append(
            f"provenance.run_id is still the draft placeholder {PLACEHOLDER_RUN_ID}; "
            "set it to this page's own run id before finalizing"
        )
    if page.provenance.model_id == PLACEHOLDER_MODEL_ID:
        out.errors.append(
            "provenance.model_id is still the draft placeholder 'TODO'; name the model "
            "that wrote this page"
        )

    # -- claims: anchors, digit discipline, language completeness ----------------------
    for where, claim in _iter_claims(page):
        for sid in claim.evidence:
            _check_anchor(out, where, sid, by_article)
        for lang in required_langs:
            if claim.text.get(lang) is None:
                out.errors.append(f"{where}: claim text missing language {lang!r}")
        # V-5: the English pivot is the canonical, mechanically recomputable master.
        # Localizations may convert notation/units for their readers; equivalence is the
        # localizer's and final reviewer's semantic responsibility, not a second parser.
        en = claim.text.get("en") or ""
        numbers = _digits(en)
        if claim.claim_type == ClaimType.CORPUS_READING:
            if numbers:
                out.errors.append(
                    f"{where}: corpus_reading text carries numbers {numbers}; a counted "
                    "statement is a corpus_aggregate"
                )
            if _QUANT_WORDS.search(en):
                out.errors.append(
                    f"{where}: corpus_reading text quantifies "
                    f"({_QUANT_WORDS.search(en).group(0)!r}); say what the sides answer, "
                    "never how much"
                )
        elif claim.claim_type == ClaimType.SOURCE_CLAIM and numbers:
            anchored_text = " ".join(
                by_article[SentenceId.parse(sid).article_id].sentence_text(sid)
                for sid in claim.evidence
                if SentenceId.parse(sid).article_id in by_article
                and by_article[SentenceId.parse(sid).article_id].has_sentence(sid)
            )
            for number in numbers:
                if number not in anchored_text:
                    out.errors.append(
                        f"{where}: source_claim states {number!r} which appears in none of "
                        "its anchored sentences — a number nobody said is not a source claim"
                    )
        elif claim.claim_type == ClaimType.CORPUS_AGGREGATE:
            finding = by_finding.get((claim.computed_from or "").split(":")[0])
            if finding is None:
                out.errors.append(
                    f"{where}: corpus_aggregate computed_from {claim.computed_from!r} names "
                    "no finding of the pinned analysis run"
                )
            else:
                allowed = _finding_numbers(finding)
                for number in numbers:
                    plain = number.replace(",", "")
                    if plain and "." not in plain and plain not in allowed:
                        out.errors.append(
                            f"{where}: corpus_aggregate states {number!r} which does not "
                            f"recompute from {finding.finding_id} (allowed: {sorted(allowed)})"
                        )

    # -- angles: findings, strength discipline, badges, quotes -------------------------
    for angle in page.angles:
        where = f"angle {angle.rank}"
        finding = by_finding.get(angle.finding_id)
        if finding is None:
            out.errors.append(
                f"{where}: finding {angle.finding_id} not in the analysis run"
            )
            continue
        if finding.question_id != angle.question_id:
            out.errors.append(
                f"{where}: finding {angle.finding_id} answers {finding.question_id}, "
                f"not {angle.question_id}"
            )
        if finding.kind != angle.kind:
            out.errors.append(
                f"{where}: declares {angle.kind.value} but the finding is {finding.kind.value}"
            )
        if finding.strength == FindingStrength.UNSUPPORTED:
            out.errors.append(
                f"{where}: finding {angle.finding_id} is marked unsupported — it may not "
                "be asserted in prose or visuals (V-3)"
            )
        # qa-0.4.0: an attention_gap angle always lays out its finding's quiet side as
        # the silent block — one side gets an answer card, the other gets renderer-worded
        # near-silence with its few mentions listed but no answer asserted for it.
        # Pre-0.4.0 pages (two speaking sides on a rate difference) stay pinned to their
        # old runs and are not re-checked.
        if finding.kind == FindingKind.ATTENTION_GAP:
            quiet = min(
                finding.groups,
                key=lambda g: (
                    g.clusters_addressed / g.clusters_total
                    if g.clusters_total
                    else 0.0,
                    g.group_id,
                ),
            )
            silent_sides = [s.group_id for s in angle.sides if s.is_silent_side]
            if not silent_sides:
                out.errors.append(
                    f"{where}: an attention_gap angle must mark the finding's quiet side "
                    f"({quiet.group_id}) silent — statistically there is no answer to "
                    "write on that side (qa-0.4.0)"
                )
            elif silent_sides != [quiet.group_id]:
                out.errors.append(
                    f"{where}: marks {silent_sides} silent but the finding's quiet side "
                    f"is {quiet.group_id}"
                )
        # Editorial interest is the writer's judgement on why a reader would care —
        # required per angle since the mechanical ranking stopped pretending to know
        # (refactor D-f).
        if (
            angle.editorial_interest is None
            or not angle.editorial_interest.text.strip()
        ):
            out.errors.append(
                f"{where}: no editorial_interest — the writer must state in one line "
                "why a reader would care about this angle"
            )
        # A weak finding used to require a hand-written caveat. The renderer now labels
        # it — one "weak signal" chip with the thresholds behind it, identical on every
        # page — so the writer's caveat is reserved for what code cannot know (a sampling
        # limitation, a corpus quirk), and never for restating the statistics in prose.
        stats_by_group = {g.group_id: g for g in finding.groups}
        for side in angle.sides:
            side_where = f"{where} ({side.group_id})"
            stats = stats_by_group.get(side.group_id)
            if stats is None:
                out.errors.append(f"{side_where}: finding has no stats for this group")
                continue
            if (
                stats.top_category_tied
                and side.answer.claim_type == ClaimType.CORPUS_AGGREGATE
                and not re.search(
                    r"\b(tie|tied|joint)\b", side.answer.text.get("en") or "", re.I
                )
            ):
                out.errors.append(
                    f"{side_where}: {stats.top_categories} are tied for the top category; "
                    "the aggregate answer must state that tie explicitly"
                )
            _check_badge(out, side_where, side.badge, angle, stats)
            _check_answer_label(out, side_where, side, stats, required_langs)
            if answers is not None and not side.is_silent_side:
                counted = set(
                    counted_clusters(
                        side, angle, finding, answers, readable=readable
                    )
                )
                per_cluster = answers.for_group(angle.question_id, side.group_id)
                for quote in side.quotes:
                    quoted = by_article.get(
                        SentenceId.parse(quote.sentence_id).article_id
                    )
                    cluster = quoted.reporting_cluster_id if quoted else None
                    if cluster is not None and cluster not in counted:
                        # The renderer shows one original per counted cluster, the
                        # writer's pick leading.  A pick from outside the counted set
                        # would make the badge and the evidence list disagree.
                        out.errors.append(
                            f"{side_where}: quote {quote.sentence_id} comes from cluster "
                            f"{cluster}, which the badge does not count — pick a "
                            "representative from the clusters the number is made of"
                        )
                missing = [
                    c
                    for c in counted
                    if not (per_cluster.get(c) and per_cluster[c].evidence)
                ]
                if missing:
                    out.errors.append(
                        f"{side_where}: {len(missing)} counted cluster(s) have no anchor to "
                        f"show the reader: {sorted(missing)[:3]}"
                    )
                out.stats[f"evidence angle {angle.rank} ({side.group_id})"] = (
                    f"{len(counted)} cluster(s) = badge {side.badge.numerator}"
                )
                if len(counted) != side.badge.numerator:
                    out.errors.append(
                        f"{side_where}: badge counts {side.badge.numerator} report(s) but "
                        f"{len(counted)} cluster(s) match it in the answers run — the "
                        "evidence list cannot show the number the badge promises"
                    )
            for quote in side.quotes:
                _check_anchor(out, side_where, quote.sentence_id, by_article)
                quoted = by_article.get(SentenceId.parse(quote.sentence_id).article_id)
                quoted_lang = (quoted.lang if quoted else "").split("-")[0]
                for lang in required_langs:
                    # A quote already in the reader's own language needs no translation —
                    # the renderer suppresses one, so demanding it would only put a
                    # sentence into the artifact as its own "translation".
                    if lang.split("-")[0] == quoted_lang:
                        continue
                    if lang != "en" and (
                        quote.translation is None or quote.translation.get(lang) is None
                    ):
                        out.errors.append(
                            f"{side_where}: quote {quote.sentence_id} translation missing "
                            f"language {lang!r} — a reviewer reading {lang} would meet "
                            "this quote untranslated"
                        )
            if (
                side.is_silent_side
                and stats.clusters_addressed != 0
                and (finding.kind == FindingKind.BLINDSPOT or finding.total_silence)
            ):
                # A quiet side with mentions is legitimate under qa-0.4.0, but a finding
                # *worded* as total silence must actually count zero.
                out.errors.append(
                    f"{side_where}: worded as total silence but the finding counts "
                    f"{stats.clusters_addressed} addressing clusters"
                )

        shared = angle.shared_category
        if shared is not None and angle.shared_answer_label is None:
            out.errors.append(
                f"{where}: both sides answer {shared!r} — the reader gets one shared "
                "answer card, so the angle needs a shared_answer_label"
            )
        if angle.shared_answer_label is not None:
            for lang in required_langs:
                if angle.shared_answer_label.get(lang) is None:
                    out.errors.append(
                        f"{where}: shared_answer_label missing language {lang!r}"
                    )

    # -- redundancy: many same-direction attention gaps read as one drumbeat -----------
    # (non-negotiable 8: silence statements stay factual, never a story
    # of neglect told three times.)
    gap_signs: dict[int, int] = {}
    for angle in page.angles:
        finding = by_finding.get(angle.finding_id)
        if (
            finding is not None
            and finding.kind == FindingKind.ATTENTION_GAP
            and finding.delta is not None
            and finding.delta.value != 0
        ):
            sign = 1 if finding.delta.value > 0 else -1
            gap_signs[sign] = gap_signs.get(sign, 0) + 1
    for sign, count in gap_signs.items():
        if count >= 3:
            out.warnings.append(
                f"{count} attention-gap angles all point the same way — together they "
                "read as one 'the other side ignores this' drumbeat; consider folding "
                "them into a single beat (non-negotiable 8)"
            )

    # -- visuals may not draw what the text may not say --------------------------------
    for visual in page.visuals:
        if visual.kind == "concept_cloud":
            _check_concept_cloud(out, visual, question_stats)
        if visual.question_id:
            asserted = {
                a.question_id: by_finding.get(a.finding_id) for a in page.angles
            }
            finding = asserted.get(visual.question_id)
            if finding is None and question_stats is not None:
                qs = question_stats.get(visual.question_id)
                if qs is None:
                    out.errors.append(
                        f"visual {visual.kind}: question {visual.question_id} is not in "
                        "the analysis run"
                    )
                elif (
                    qs.get("kind")
                    not in (None, "insufficient", "too_thin", "no_significant_relation")
                    and visual.kind == "answer_distribution"
                ):
                    out.warnings.append(
                        f"visual {visual.kind}: draws {visual.question_id} which no angle "
                        "asserts — make sure it is not implying an unsupported contrast"
                    )
        for lang in required_langs:
            if visual.caption.get(lang) is None:
                out.errors.append(
                    f"visual {visual.kind}: caption missing language {lang!r}"
                )

    # -- language completeness for the remaining reader-facing fields ------------------
    for lang in required_langs:
        if page.title.get(lang) is None:
            out.errors.append(f"page title missing language {lang!r}")
        for angle in page.angles:
            reader_question = page.lexicon.questions.get(angle.question_id)
            if reader_question is not None:
                if reader_question.get(lang) is None:
                    out.errors.append(
                        f"angle {angle.rank}: lexicon question {angle.question_id} "
                        f"missing language {lang!r}"
                    )
            elif angle.question_display is None:
                out.errors.append(
                    f"angle {angle.rank}: no reader wording for {angle.question_id} — "
                    "add it to page.lexicon.questions"
                )
            elif angle.question_display.get(lang) is None:
                out.errors.append(
                    f"angle {angle.rank}: question_display missing language {lang!r}"
                )
            if angle.caveat is not None and angle.caveat.get(lang) is None:
                out.errors.append(
                    f"angle {angle.rank}: caveat missing language {lang!r}"
                )
            for side in angle.sides:
                # An English badge label on a Chinese page is the count itself arriving
                # untranslated — the renderer falls back to a localized default only when
                # no label was written at all.
                if side.badge.label is not None and side.badge.label.get(lang) is None:
                    out.errors.append(
                        f"angle {angle.rank} ({side.group_id}): badge label missing "
                        f"language {lang!r}"
                    )
        for question_id, text in sorted(page.lexicon.questions.items()):
            if text.get(lang) is None:
                out.errors.append(
                    f"lexicon question {question_id} missing language {lang!r}"
                )
        for category, text in sorted(page.lexicon.categories.items()):
            if text.get(lang) is None:
                out.errors.append(
                    f"lexicon category {category} missing language {lang!r}"
                )
        for phrase, text in sorted(page.lexicon.scope.items()):
            if text.get(lang) is None:
                out.errors.append(f"lexicon scope {phrase!r} missing language {lang!r}")
        for pivot, text in sorted(page.lexicon.topics.items()):
            if text.get(lang) is None:
                out.errors.append(f"lexicon topic {pivot!r} missing language {lang!r}")
        # group_labels/group_short_labels/group_definitions are a *supplement* to the
        # manifest's own groups[].label/short_label/definition, not a replacement for it
        # (see the field's docstring: the manifest can only ever carry the languages
        # touchpoint one approved). A language missing from the lexicon override is only
        # a real gap when the manifest does not carry it either — same fallback the
        # renderer's group_text() performs — so this checks against that union, not the
        # lexicon dict alone the way questions/categories/scope/topics do above (those
        # have no such manifest fallback).
        for group_id, text in sorted(page.lexicon.group_labels.items()):
            group = manifest.group_by_id(group_id) if manifest else None
            fallback = group.label if group else None
            if text.get(lang) is None and (fallback is None or fallback.get(lang) is None):
                out.errors.append(
                    f"lexicon group_labels {group_id!r} missing language {lang!r} "
                    "(manifest has no fallback for it either)"
                )
        for group_id, text in sorted(page.lexicon.group_short_labels.items()):
            group = manifest.group_by_id(group_id) if manifest else None
            fallback = (group.short_label or group.label) if group else None
            if text.get(lang) is None and (fallback is None or fallback.get(lang) is None):
                out.errors.append(
                    f"lexicon group_short_labels {group_id!r} missing language {lang!r} "
                    "(manifest has no fallback for it either)"
                )
        for group_id, text in sorted(page.lexicon.group_definitions.items()):
            group = manifest.group_by_id(group_id) if manifest else None
            fallback = group.definition if group else None
            if text.get(lang) is None and (fallback is None or fallback.get(lang) is None):
                out.errors.append(
                    f"lexicon group_definitions {group_id!r} missing language {lang!r} "
                    "(manifest has no fallback for it either)"
                )

    _check_lexicon_coverage(out, page, question_stats)
    _check_scope_coverage(out, page, manifest)
    _check_topics_coverage(out, page, topics_by_article)
    _check_group_lexicon_coverage(out, page, manifest)
    _check_footnote_markers(out, page, required_langs)
    _check_machine_category_labels(out, page)
    if page.hook is not None:
        out.warnings.append(
            "page carries a hook, which the renderer no longer draws (angle 1 is the "
            "hook) — drop the field instead of writing and localizing dead text"
        )
    return out


def _check_machine_category_labels(out: "CheckResult", page) -> None:
    """A reader-facing category label that equals the generator's default was never
    rewritten.

    ``page-init`` seeds ``lexicon.categories`` with ``key.replace('_', ' ').capitalize()``
    as machine vocabulary that the write stage must put into reader words.  Equality with
    that default is a warning, not an error: a short key's default can coincide with a
    deliberate label, and a warning must be answered in the run report either way.
    """
    raw = sorted(
        key
        for key, text in page.lexicon.categories.items()
        if (en := text.get("en")) is not None
        and en == key.split(":")[-1].replace("_", " ").capitalize()
    )
    if raw:
        shown = ", ".join(raw[:5]) + ("…" if len(raw) > 5 else "")
        out.warnings.append(
            f"{len(raw)} lexicon category label(s) equal the machine-generated default "
            f"({shown}) — rewrite them in reader words, or answer this warning in the "
            "run report"
        )


def _check_footnote_markers(
    out: PageCheckReport, page: ReaderPage, required_langs: tuple[str, ...]
) -> None:
    """A note the prose never points at is a note the reader never sees.

    ``caveat`` and ``detail`` reach the reader only through a ``[^n]`` marker in the
    angle's explanation: the renderer builds the note list, then drops every note no marker
    reached — there is no appendix that shows the leftovers. So a page can carry a carefully
    written sampling caveat, validate clean, render, and simply not contain it, and the only
    way anyone finds out is by reading the page and remembering what was supposed to be on
    it. Checked per reader language, because a translation that drops the marker loses the
    note for that reader alone.
    """
    for angle in page.angles:
        notes = (1 if angle.caveat is not None else 0) + len(angle.detail)
        for lang in required_langs:
            prose = (
                [angle.commentary_joint.text.get(lang)]
                if angle.commentary_joint is not None
                else [side.answer.text.get(lang) for side in angle.sides]
            )
            marked = {
                int(m.group(1))
                for text in prose
                if text
                for m in _FOOTNOTE_INDEX.finditer(text)
            }
            missing = sorted(set(range(1, notes + 1)) - marked)
            if notes and len(missing) == notes:
                out.warnings.append(
                    f"angle {angle.rank} [{lang}]: {notes} note(s) — "
                    + ("caveat" if angle.caveat is not None else "")
                    + (" + " if angle.caveat is not None and angle.detail else "")
                    + (f"{len(angle.detail)} detail" if angle.detail else "")
                    + " — but the explanation carries no [^n] marker, so the renderer drops "
                    "every one of them and the reader never sees it"
                )
            elif missing:
                out.warnings.append(
                    f"angle {angle.rank} [{lang}]: note(s) {missing} have no [^n] marker in "
                    "the explanation and will not be rendered"
                )
            # A marker pointing at nothing is the same defect from the other end: the
            # writer meant to say something in a note that is not on the page.
            dangling = sorted(n for n in marked if not 1 <= n <= notes)
            if dangling:
                out.warnings.append(
                    f"angle {angle.rank} [{lang}]: marker(s) {dangling} point past the "
                    f"angle's {notes} note(s); the renderer drops the marker silently"
                )


def _check_topics_coverage(
    out: PageCheckReport, page: ReaderPage, topics_by_article
) -> None:
    """Every displayed collect-stage pivot has a reader-language lexicon entry."""
    if topics_by_article is None:
        return
    wanted = {
        (entry.get("pivot_en") or "").strip()
        for entries in topics_by_article.values()
        for entry in (entries or [])
        if (entry.get("pivot_en") or "").strip()
    }
    missing = sorted(wanted - set(page.lexicon.topics))
    if missing:
        out.errors.append(
            f"{len(missing)} topics_raised pivot(s) have no reader wording in "
            "page.lexicon.topics: " + "; ".join(missing)
        )
    stray = sorted(set(page.lexicon.topics) - wanted)
    if stray:
        out.warnings.append(
            "page.lexicon.topics carries entries absent from the pinned collect artifact: "
            + "; ".join(stray)
        )


def _check_scope_coverage(out: PageCheckReport, page: ReaderPage, manifest) -> None:
    """Every in/out-of-scope bullet the scope panel shows needs reader words.

    The manifest is written in English at touchpoint one and cannot carry a translation
    (its hash is what a topic's ``scope_approval`` signed), so the reader wording lives
    in ``page.lexicon.scope``. A gap is a warning: the panel falls back to the English
    original, which is honest but is our internal vocabulary on a reader's page.
    """
    if manifest is None:
        return
    wanted = [*manifest.include, *manifest.exclude]
    missing = [phrase for phrase in wanted if phrase not in page.lexicon.scope]
    if missing:
        out.warnings.append(
            f"{len(missing)} scope bullet(s) have no reader wording in page.lexicon.scope: "
            + "; ".join(missing)
        )
    stray = sorted(set(page.lexicon.scope) - set(wanted))
    if stray:
        out.warnings.append(
            "page.lexicon.scope carries entries the manifest does not contain (a scope "
            f"bullet was reworded?): {', '.join(stray)}"
        )
    # The bullets are what touchpoint one signed; a localization is a translation, not a
    # summary.  Numbers (dates, windows) are the deterministic tracer: every number the
    # English bullet states must survive into every localized wording.  Leading zeros
    # are stripped ("04" appears as "4月") and containment is substring-level, so
    # natural notation changes still pass.
    for phrase in wanted:
        text = page.lexicon.scope.get(phrase)
        if text is None:
            continue
        numbers = {n.lstrip("0") or "0" for n in re.findall(r"\d+", phrase)}
        for lang, localized in sorted(text.values.items()):
            if not localized:
                continue
            lost = sorted(n for n in numbers if n not in localized)
            if lost:
                out.warnings.append(
                    f"lexicon scope [{lang}] drops number(s) {', '.join(lost)} from "
                    f"the signed bullet {phrase[:60]!r}… — translate the bullet, do "
                    "not summarize it"
                )


def _check_group_lexicon_coverage(out: PageCheckReport, page: ReaderPage, manifest) -> None:
    """A run that starts translating a side's name should finish both sides.

    ``page.lexicon.group_labels`` / ``group_short_labels`` / ``group_definitions`` exist
    because the manifest's ``groups[].label`` etc. cannot carry a language beyond what
    touchpoint one approved without invalidating ``scope_hash()`` (see the field's
    docstring). A run that never touches these three dicts is unaffected — the renderer
    falls back to the manifest, as it always has. A run that populates one of them
    for one group but not the other, or for one field but not the sibling fields, is a
    half-finished extension: the reader would see one side's badge translated and the
    other side's badge in whatever language the manifest happens to carry. Warning, not
    error, for the same reason ``_check_scope_coverage`` is a warning: the gap degrades
    to the manifest's own wording rather than fabricating one.
    """
    if manifest is None:
        return
    group_ids = [g.group_id for g in manifest.groups]
    for attr in ("group_labels", "group_short_labels", "group_definitions"):
        table = getattr(page.lexicon, attr)
        if not table:
            continue
        missing = [gid for gid in group_ids if gid not in table]
        if missing:
            out.warnings.append(
                f"page.lexicon.{attr} covers {sorted(table)} but the manifest's groups "
                f"are {group_ids} — missing {missing}"
            )
        stray = sorted(set(table) - set(group_ids))
        if stray:
            out.warnings.append(
                f"page.lexicon.{attr} carries group_id(s) the manifest does not "
                f"declare: {stray}"
            )


def _check_concept_cloud(
    out: PageCheckReport, visual, question_stats: Optional[dict]
) -> None:
    """The cloud is drawn from the pinned run, so the page must name that run's stats.

    Nothing here is a writer's number — the whole section is computed at render time — so
    the declaration is all there is to check before rendering. What actually shipped is
    verified afterwards, against the HTML, by :func:`check_rendered_concept_cloud`.
    """
    if not visual.data_from.startswith("qa_run:question_stats"):
        out.errors.append(
            f"visual concept_cloud: data_from {visual.data_from!r} — the cloud is summed "
            "from the pinned analyze run's question_stats and from nothing else"
        )
    if not question_stats:
        out.errors.append(
            "visual concept_cloud: declared, but this check has no question_stats to sum"
        )
        return
    clouds = concept_cloud.build(question_stats)
    speaking = {gid: cloud for gid, cloud in clouds.items() if cloud.total}
    if len(speaking) < 2:
        out.errors.append(
            "visual concept_cloud: fewer than two sides have any classified answer — "
            f"there is no vocabulary to put side by side (totals: "
            f"{ {gid: c.total for gid, c in clouds.items()} })"
        )
        return
    for group_id, cloud in sorted(speaking.items()):
        out.stats[f"concept cloud ({group_id})"] = (
            f"{len(cloud.shown)} of {len(cloud.concepts)} concept(s) drawn, "
            f"{cloud.total} classified answers"
        )
        if not cloud.shown:
            out.warnings.append(
                f"visual concept_cloud ({group_id}): nothing reaches "
                f"both {concept_cloud.MIN_COUNT} answers and "
                f"{concept_cloud.SHARE_THRESHOLD:.0%} of this side's "
                f"{cloud.total} answers — the column would be empty"
            )


#: One rendered pill's opening tag, as :func:`page_render._concept_cloud_viz` writes it.
#: Its body is taken by scanning to the next pill rather than by a nested-span pattern —
#: the two columns mirror the order of label and percentage, so there is no one shape.
_PILL = re.compile(
    r'<span class="pill (?P<css>[ab])" tabindex="0" data-k="(?P<key>[^"]*)" '
    r'style="font-size:(?P<px>[0-9.]+)px">'
)
_PILL_END = re.compile(r'<span class="pill |</div>')
_PILL_PCT = re.compile(r'<span class="pct">(?P<pct>[0-9.]+)%</span>')


def check_rendered_concept_cloud(
    html_text: str,
    question_stats: dict,
    order: list[str],
    *,
    source: str = "categories",
    topics_by_article: Optional[dict] = None,
    articles: Optional[Iterable[Article]] = None,
) -> PageCheckReport:
    """Re-derive the cloud from the pinned run and hold the rendered page to it.

    Same discipline as a count badge, one step later: a badge is a number a writer typed
    and the checks recompute, and every number in this section is a number the *renderer*
    computed — so it is recomputed here from ``question_stats`` alone, and compared against
    what the HTML actually says. The arithmetic below deliberately does not call
    :mod:`.concept_cloud`: a check that runs the code it is checking would confirm nothing
    but that the function is deterministic.

    ``order`` is the group ids in column order (left, right) — the same order
    ``group_meta`` assigns the ``a`` / ``b`` colours from the manifest.
    """
    out = PageCheckReport()
    pills = list(_PILL.finditer(html_text))
    if not pills:
        out.stats["concept cloud"] = "not rendered"
        return out

    totals: dict[str, int] = {}
    counts: dict[str, dict[str, int]] = {}
    if source == "topics_raised":
        # The reporting-cluster tally, recomputed here from the collect artifact and the
        # pinned corpus run: a phrase counts once per independent report, and the
        # denominator is that side's whole set of **readable** reports, records or no
        # records — the site's one counting universe, the same one every badge
        # denominator uses (``newsab_schema.readability``).
        article_list = list(articles or ())
        readable = readable_clusters_of_articles(article_list)
        seen: dict[str, set[str]] = {}
        hits: dict[str, dict[str, set[str]]] = {}
        for article in article_list:
            if article.reporting_cluster_id not in readable:
                continue
            group_id = article.article_id.split("_", 1)[0].lower()
            seen.setdefault(group_id, set()).add(article.reporting_cluster_id)
            for entry in (topics_by_article or {}).get(article.article_id) or ():
                phrase = (entry.get("pivot_en") or "").strip()
                if phrase:
                    hits.setdefault(group_id, {}).setdefault(phrase, set()).add(
                        article.reporting_cluster_id
                    )
        for group_id, clusters in seen.items():
            totals[group_id] = len(clusters)
            counts[group_id] = {
                phrase: len(members)
                for phrase, members in (hits.get(group_id) or {}).items()
            }
    else:
        for stats in question_stats.values():
            for group_id, gstats in (stats.get("groups") or {}).items():
                for category, n in (gstats.get("category_counts") or {}).items():
                    if category in concept_cloud.MECHANISM_CATEGORIES:
                        continue
                    counts.setdefault(group_id, {})[category] = counts.setdefault(
                        group_id, {}
                    ).get(category, 0) + int(n)
                    totals[group_id] = totals.get(group_id, 0) + int(n)

    css_group = {css: group_id for css, group_id in zip(("a", "b"), order)}
    drawn: dict[str, list[tuple[str, float]]] = {}
    sizes: list[tuple[float, float]] = []
    for pill in pills:
        css, key = pill.group("css"), html.unescape(pill.group("key"))
        group_id = css_group.get(css)
        where = f"concept cloud ({group_id or css}) {key}"
        count = (counts.get(group_id) or {}).get(key)
        if count is None:
            out.errors.append(
                f"{where}: drawn on the page but this side's coverage was never annotated "
                "with it in the pinned run"
            )
            continue
        share = count / totals[group_id]
        tail = _PILL_END.search(html_text, pill.end())
        body = html_text[pill.end() : tail.start() if tail else len(html_text)]
        shown_pct = _PILL_PCT.search(body)
        if shown_pct is None:
            out.errors.append(f"{where}: drawn without its share")
        elif shown_pct.group("pct") != f"{share * 100:.1f}":
            out.errors.append(
                f"{where}: the page says {shown_pct.group('pct')}% but {count}/"
                f"{totals[group_id]} recomputes to {share * 100:.1f}%"
            )
        if count < concept_cloud.MIN_COUNT or share < concept_cloud.SHARE_THRESHOLD:
            out.errors.append(
                f"{where}: {count}/{totals[group_id]} ({share:.1%}) is below the "
                f"{concept_cloud.MIN_COUNT}-answer and {concept_cloud.SHARE_THRESHOLD:.0%} "
                "display threshold the footnote promises"
            )
        drawn.setdefault(group_id, []).append((key, share))
        sizes.append((share, float(pill.group("px"))))

    # "Bigger word = bigger share" is the section's whole visual claim, and it is claimed
    # across the midline as well as down a column: one map, both sides.
    ranked = sorted(sizes, key=lambda pair: -pair[0])
    if any(a[1] < b[1] - 1e-6 for a, b in zip(ranked, ranked[1:])):
        out.errors.append(
            "concept cloud: a smaller share is set larger than a bigger one — the two "
            "columns are not sharing one size map"
        )
    if ranked and abs(ranked[0][1] - concept_cloud.FONT_MAX_PX) > 1e-6:
        out.errors.append(
            f"concept cloud: the largest share is set at {ranked[0][1]}px, not the "
            f"{concept_cloud.FONT_MAX_PX}px top of the range"
        )

    for group_id, entries in sorted(drawn.items()):
        if len(entries) > concept_cloud.MAX_PER_SIDE:
            out.errors.append(
                f"concept cloud ({group_id}): {len(entries)} concepts drawn, over the "
                f"cap of {concept_cloud.MAX_PER_SIDE} the footnote promises"
            )
        shares = [share for _, share in entries]
        if shares != sorted(shares, reverse=True):
            out.errors.append(
                f"concept cloud ({group_id}): the column is not in descending order of "
                "share — the reader is told rank means share"
            )
        expected = sorted(
            (
                cat
                for cat, n in (counts.get(group_id) or {}).items()
                if n >= concept_cloud.MIN_COUNT
                and n / totals[group_id] >= concept_cloud.SHARE_THRESHOLD
            ),
            key=lambda cat: (-counts[group_id][cat], cat),
        )[: concept_cloud.MAX_PER_SIDE]
        if [key for key, _ in entries] != expected:
            out.errors.append(
                f"concept cloud ({group_id}): the drawn concepts are not the ones that "
                f"recompute from the pinned run (page: {[k for k, _ in entries]}, "
                f"recomputed: {expected})"
            )
        out.stats[f"concept cloud ({group_id})"] = (
            f"{len(entries)} concept(s) verified against {totals[group_id]} "
            "classified answers"
        )
    return out


def _check_lexicon_coverage(
    out: PageCheckReport, page: ReaderPage, question_stats: Optional[dict]
) -> None:
    """Every question and every answer category the page displays needs reader words.

    A gap is a warning, not an error: the renderer falls back to the annotation wording or
    the raw counting key, which is ugly but never wrong. It is still a defect — the reader
    is being shown our internal vocabulary.
    """
    if not question_stats:
        return
    missing_questions = sorted(set(question_stats) - set(page.lexicon.questions))
    if missing_questions:
        out.warnings.append(
            f"{len(missing_questions)} question(s) have no reader wording in "
            f"page.lexicon.questions: {', '.join(missing_questions)}"
        )
    categories: set[str] = set()
    for stats in question_stats.values():
        for gstats in (stats.get("groups") or {}).values():
            categories.update((gstats.get("category_counts") or {}))
    missing_categories = sorted(categories - set(page.lexicon.categories))
    if missing_categories:
        out.warnings.append(
            f"{len(missing_categories)} answer category/ies have no reader label in "
            f"page.lexicon.categories: {', '.join(missing_categories)}"
        )


def _check_answer_label(
    out: PageCheckReport,
    where: str,
    side,
    stats,
    required_langs: tuple[str, ...],
) -> None:
    """The answer card is the first thing a reader reads — it has to be bound to a count.

    ``answer_label`` is short reader language (the writer's job); ``answer_category`` is
    the annotate stage's category it puts into words, and it must be one the finding
    actually counted for this side.
    """
    if side.is_silent_side:
        return
    if side.answer_label is None:
        out.errors.append(
            f"{where}: no answer_label — the angle's answer card would have nothing to "
            "say before the reader reaches the paragraph"
        )
    else:
        for lang in required_langs:
            if side.answer_label.get(lang) is None:
                out.errors.append(f"{where}: answer_label missing language {lang!r}")
    selector = badge_selector(side)
    counts = stats.category_counts or {}
    if selector == "top_category":
        if side.answer_category != stats.top_category:
            out.errors.append(
                f"{where}: answer_category {side.answer_category!r} is not the category "
                f"the badge counts ({stats.top_category!r})"
            )
    elif side.answer_category is not None and side.answer_category not in counts:
        out.errors.append(
            f"{where}: answer_category {side.answer_category!r} is not one this side's "
            f"coverage was annotated with (have: {sorted(counts)})"
        )


def _check_badge(
    out: PageCheckReport,
    where: str,
    badge: CountBadge,
    angle: AngleBlock,
    stats,
) -> None:
    """A badge recomputes from its finding or it does not ship."""
    ref = badge.computed_from
    base, _, selector = ref.partition(":")
    if base != angle.finding_id:
        out.errors.append(
            f"{where}: badge computed_from {ref!r} must name the angle's finding "
            f"{angle.finding_id}"
        )
        return
    if selector in ("", "addressed"):
        expected = (stats.clusters_addressed, stats.clusters_total)
    elif selector == "top_category":
        if stats.top_category_tied:
            out.errors.append(
                f"{where}: badge selector top_category is ambiguous because "
                f"{stats.top_categories} are tied; use addressed or state the tie explicitly"
            )
            return
        top = stats.top_category
        expected = (
            (stats.category_counts or {}).get(top, 0),
            stats.clusters_addressed,
        )
    else:
        out.errors.append(f"{where}: unknown badge selector {selector!r}")
        return
    if (badge.numerator, badge.denominator) != expected:
        out.errors.append(
            f"{where}: badge says {badge.numerator}/{badge.denominator} but "
            f"{ref} recomputes to {expected[0]}/{expected[1]}"
        )


def load_analysis_thresholds(run_dir: Path) -> dict:
    """The thresholds the pinned analyze run actually ran under.

    The page's statistical chips quote these numbers, so they come from the run record
    rather than from a copy in this package — a page pinned to an older run explains
    itself in that run's terms.
    """
    path = run_dir / "run.json"
    if not path.exists():
        return {}
    record = json.loads(path.read_text(encoding="utf-8"))
    return dict(record.get("thresholds") or {})


def load_analysis_run(run_dir: Path) -> tuple[list[QAFinding], dict]:
    findings = [
        QAFinding.model_validate_json(line)
        for line in (run_dir / "findings.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    question_stats = json.loads(
        (run_dir / "question_stats.json").read_text(encoding="utf-8")
    )
    return findings, question_stats


def load_pinned_corpus_run(run_dir: Path) -> Optional[str]:
    """The corpus run the analysis actually analysed, from its own record."""
    run_file = run_dir / "run.json"
    if not run_file.exists():
        return None
    inputs = json.loads(run_file.read_text(encoding="utf-8")).get("inputs") or {}
    return inputs.get("corpus_run_id")


def load_excluded_clusters(run_dir: Path) -> list[str]:
    """Clusters this analysis run left out of its denominators.

    Read from the run rather than recomputed from the corpus, so a page always counts
    exactly what the analysis it pins counted — including when an older run is re-rendered.
    """
    run_file = run_dir / "run.json"
    if not run_file.exists():
        return []
    inputs = json.loads(run_file.read_text(encoding="utf-8")).get("inputs") or {}
    return list(inputs.get("peripheral_clusters_excluded") or [])
