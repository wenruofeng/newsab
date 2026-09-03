"""Proving that a re-prepared page still carries the bytes a human approved.

Touchpoint two signs *one page's exact bytes*.  ``prepare`` therefore re-renders the
reviewed locale set and demands those bytes back, byte for byte
(:func:`newsab_publish.builder.prepare_publication`).  That check is the reason a
publication can never quietly become a different article, and **nothing here relaxes it
on that path**.

The site-wide locale backfill is the one path where the strict re-prove cannot hold and
should not.  ``backfill-locales`` re-prepares an already-approved publication months
later, against the topic's *current* editorial run and with *today's* renderer, for the
sole purpose of shipping languages the site has since learned.  Two things move that have
nothing to do with what the reviewer read:

1. **The run says who it is.**  The disclosure panel renders the editorial run's own
   ``run_id``/timestamp/producer version/``model_id``.  An expansion run is a new run
   (``docs/artifact_versioning.md``: wrong or extended records are never edited in place),
   so that line necessarily changes even when every reader-visible sentence is identical.
2. **The chrome is renderer-owned.**  Site furniture — the ``dir`` attribute, the
   hreflang alternates, the language switcher, the wording of the stat tooltips — belongs
   to the renderer, not to the article.  It moves with the code and is explicitly not a
   thing a human is asked to re-approve (``skills/publish/references/localization.md``).

So the backfill path proves the same thing a different way, in two layers, and refuses on
anything else.  It is *not* a looser byte comparison; it is a stricter content comparison
plus a byte comparison with a closed, code-owned whitelist:

* **Layer 1 — content equivalence.**  The signed run's ``page.json`` and the candidate
  run's ``page.json``, both projected onto the reviewed locales, must be identical: same
  angles, same prose, same quotes, same badge numerators and denominators, same lexicon.
  Values in *other* languages are ignored (that is the whole point of an expansion run);
  a value present in one and absent in the other is a difference.  The pinned upstream
  closure (corpus / questions / answers / normalization / analysis / write) and the
  language-neutral data islands must be identical too.  This is strictly stronger than
  any HTML diff: it compares the artifact the writer produced, not a rendering of it.
* **Layer 2 — rendered-byte equivalence under a closed whitelist.**  Both the signed HTML
  and the freshly rendered HTML are put through :func:`redact`, which erases exactly the
  regions listed in :data:`RULES` and nothing else, and the results must be byte-identical.
  Every rule is anchored on markup the renderer emits from a fixed template, so no
  editorial sentence, number, label or quote can hide inside one.  The stat-tooltip rule
  keeps the tooltip's *numbers* in the comparison and drops only the words around them,
  because the numbers are the substance and the wording is the renderer's.

Both layers fail closed: anything they cannot account for is a refusal, reported for the
ordinary review path.  The evidence they produce (hashes on both sides, the digest of the
redacted bytes, which rules actually fired) is written into the ``PublicationRecord`` so a
later ``verify-candidate`` can replay the proof without needing the superseded bundle.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Sequence

from newsab_editorial.render.strings import PROVENANCE_COUNTS
from newsab_schema.io import ArtifactError


#: Bump when :data:`RULES` changes.  It is recorded with every proof, so a record always
#: says which whitelist it was accepted under and an audit can tell them apart.
WHITELIST_VERSION = "reviewed-equivalence-1.0.0"


@dataclass(frozen=True)
class RedactionRule:
    """One whitelisted region: what it is, why it may move, how to erase it."""

    key: str
    why: str
    pattern: re.Pattern[str]
    #: What replaces a match.  Default erases it; the stat tooltip keeps its numbers.
    replace: Callable[[re.Match[str]], str] = lambda match: ""

    def apply(self, html: str) -> tuple[str, int]:
        hits = 0

        def _sub(match: re.Match[str]) -> str:
            nonlocal hits
            hits += 1
            return self.replace(match)

        return self.pattern.sub(_sub, html), hits


def _language_note_pattern() -> re.Pattern[str]:
    """The page row's own counter note ("2 languages"), from the renderer's own table.

    Built from ``PROVENANCE_COUNTS["page"]`` rather than hand-typed so this rule cannot
    drift from what the renderer actually writes, and so it can never accidentally cover
    a *different* provenance note (the scope/review actor lines, which are content about
    a human and stay in the comparison).
    """
    alternatives = []
    for _name, template in PROVENANCE_COUNTS.get("page", ()):
        for text in template.values():
            alternatives.append(re.escape(text).replace(r"\{n\}", r"[0-9][0-9.]*"))
    if not alternatives:  # pragma: no cover - the table is never empty in practice
        return re.compile(r"(?!)")
    return re.compile(
        r'<span class="prov-note">(?:' + "|".join(sorted(set(alternatives))) + r")</span>"
    )


def _tooltip_numbers(match: re.Match[str]) -> str:
    """Keep the tooltip's numbers, drop the renderer's wording around them."""
    numbers = ",".join(re.findall(r"[0-9][0-9.]*", match.group(1)))
    return f'<span class="badge count" data-tip="#{numbers}"'


#: The closed whitelist.  Adding a rule here widens what a backfill may accept without a
#: human, so each one names the renderer template it is anchored on and why that region
#: is site-owned rather than approved content.
RULES: tuple[RedactionRule, ...] = (
    RedactionRule(
        key="locale-alternates",
        why=(
            "hreflang alternates in <head>: the set of languages the site ships, a "
            "site-owned decision the reviewer did not take. Verified independently by "
            "page_semantics.check_hreflang against the publication's actual locales."
        ),
        pattern=re.compile(r'<link rel="alternate" hreflang="[^"]*" href="[^"]*">'),
    ),
    RedactionRule(
        key="locale-switcher",
        why=(
            "the language switcher's per-locale links and the fallback notice "
            "(render/page.py _site_tools): same site-owned locale list, in the body."
        ),
        pattern=re.compile(
            r'<a href="[^"]*" hreflang="[^"]*" lang="[^"]*"(?: aria-current="page")?>'
            r"[^<]*</a>"
            r'|<p class="locale-fallback" role="note">[^<]*</p>'
        ),
    ),
    RedactionRule(
        key="content-direction",
        why=(
            "dir= on the root <html> element: writing direction is renderer "
            "chrome derived from the locale, never authored content."
        ),
        pattern=re.compile(r' dir="(?:ltr|rtl)"(?= data-site-locale=)'),
    ),
    RedactionRule(
        key="provenance-lineage",
        why=(
            "the run id / timestamp / producer version / model of each provenance row "
            "(render/modals.py disclosure_modal). An expansion run is a new run, so its "
            "self-description necessarily differs; Layer 1 compares the pinned closure "
            "itself, which is what those ids stand for."
        ),
        pattern=re.compile(
            r'<code class="prov-run">[^<]*</code>'
            r'<span class="prov-meta"><time datetime="[^"]*">[^<]*</time>'
            r"<span>[^<]*</span>"
            r'(?:<span class="prov-model">[^<]*</span>)?</span>'
        ),
    ),
    RedactionRule(
        key="provenance-language-count",
        why=(
            "the page row's 'N languages' counter: a fact about the run, and the very "
            "number a locale expansion is supposed to change."
        ),
        pattern=_language_note_pattern(),
    ),
    RedactionRule(
        key="stat-tooltip-wording",
        why=(
            "the count badge's data-tip sentence (render/strings.py STAT_TEMPLATE): a "
            "renderer-owned template. Its numbers stay in the comparison — only the "
            "words around them are dropped — and the badge's visible text is compared "
            "verbatim like any other content."
        ),
        pattern=re.compile(r'<span class="badge count" data-tip="([^"]*)"'),
        replace=_tooltip_numbers,
    ),
)


def redact(html: str) -> tuple[str, dict[str, int]]:
    """Erase every whitelisted region, returning the remainder and per-rule hit counts."""
    counts: dict[str, int] = {}
    for rule in RULES:
        html, hits = rule.apply(html)
        counts[rule.key] = hits
    return html, counts


def redacted_digest(html: bytes) -> tuple[str, dict[str, int]]:
    """``sha256`` of the non-whitelisted bytes of one rendered page."""
    remainder, counts = redact(html.decode("utf-8"))
    digest = hashlib.sha256(remainder.encode("utf-8")).hexdigest()
    return f"sha256:{digest}", counts


# --------------------------------------------------------------------------------------
# Layer 1 — content equivalence, on the artifacts rather than on their rendering
# --------------------------------------------------------------------------------------


def project_page(node, locales: Iterable[str]):
    """A ``page.json`` with every multi-language value narrowed to ``locales``.

    ``MultiLangText`` is the only place a page carries several languages at once, and it
    is recognised structurally (``{"values": {lang: str}}``) rather than by field name, so
    a new multi-language field cannot slip past unprojected.  ``provenance`` is dropped:
    it is the run's self-description, which is exactly what an expansion run changes.

    Three normalizations keep the comparison about content rather than about
    serialization: a value that narrows to nothing becomes absent (a quote gaining a
    French translation is not a change to the English page), an explicit ``null`` is
    treated as absent (different producer versions disagree about whether to emit unset
    optional fields — ``"question_id": null`` and no ``question_id`` are the same page),
    and a *container* that narrows to nothing is absent the same way one level up — a run
    that introduces a whole new multi-language lexicon dict (``page.lexicon.group_labels``
    and friends) populated only in locales this page has not been reviewed in
    projects to ``{}`` on a baseline old enough to have no such key at all, and those two
    are the same reviewed-language page.  None of the three can hide a real change: a
    field that *had* a reviewed-language value and lost it still leaves at least one side
    non-empty, so it still differs.
    """
    keep = set(locales)
    if isinstance(node, dict):
        values = node.get("values")
        if (
            set(node) == {"values"}
            and isinstance(values, dict)
            and all(isinstance(value, str) for value in values.values())
        ):
            kept = {lang: text for lang, text in values.items() if lang in keep}
            return {"values": kept} if kept else None
        projected = {
            key: project_page(value, keep)
            for key, value in node.items()
            if key != "provenance"
        }
        kept_container = {key: value for key, value in projected.items() if value is not None}
        return kept_container or None
    if isinstance(node, list):
        return [project_page(item, keep) for item in node]
    return node


def _first_difference(left, right, path: str = "") -> Optional[str]:
    """Where two projected pages stop agreeing, in reader terms."""
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            found = _first_difference(left.get(key), right.get(key), f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return f"{path}: {len(left)} items -> {len(right)} items"
        for index, (a, b) in enumerate(zip(left, right)):
            found = _first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
        return None
    if left != right:
        return f"{path}: {str(left)[:120]!r} -> {str(right)[:120]!r}"
    return None


@dataclass(frozen=True)
class ContentBaseline:
    """What a re-prepared candidate is measured against.

    The **first** backfill of a publication measures against the user's own approved bytes,
    recovered from the live publication's stored bundle and re-hashed against
    ``review.page_hash`` before they are allowed to stand for anything.

    Every backfill **after** that measures against the standing publication, which is
    itself already proven equivalent to those bytes.  Equivalence composes exactly
    because Layer 2 is a digest equality: the standing record says
    ``redact(signed) == redact(candidate₁)``, so showing ``redact(candidate₂)`` equals
    that same digest shows ``redact(candidate₂) == redact(signed)``.  Chaining this way —
    rather than reaching back for the original bundle — is what lets the user's
    approval survive a publication being superseded, which is the normal case by the
    second language the site learns.
    """

    page: Mapping  # the baseline run's page.json, parsed
    page_run_id: str
    #: ``(stage, run_id)`` for every pin except ``page`` — the lineage under the article.
    closure: tuple[tuple[str, str], ...]
    #: ``(name, sha256)`` of the language-neutral data islands. Locale-set independent by
    #: construction, so a baseline taken from a wider publication still compares.
    data_assets: tuple[tuple[str, str], ...]
    #: The exact bytes the human approved — present only on the first backfill.
    page_html: Optional[bytes] = None
    #: The digest a standing proof already established — present on every later one.
    prior_redacted_digest: Optional[str] = None

    def reference_digest(self) -> str:
        """The redacted digest a candidate has to reproduce, from either form."""
        if self.page_html is not None:
            return redacted_digest(self.page_html)[0]
        if self.prior_redacted_digest is not None:
            return self.prior_redacted_digest
        raise ArtifactError("a baseline carries neither signed bytes nor a prior proof")

    def reference_html(self) -> Optional[str]:
        return None if self.page_html is None else self.page_html.decode("utf-8")


def prove_content_equivalence(
    baseline: ContentBaseline,
    candidate_page: Mapping,
    candidate_closure: Sequence[tuple[str, str]],
    candidate_data_assets: Sequence[tuple[str, str]],
    reviewed_locales: Sequence[str],
) -> None:
    """Raise unless the approved content is identical in every reviewed language."""
    signed = project_page(baseline.page, reviewed_locales)
    candidate = project_page(candidate_page, reviewed_locales)
    if signed != candidate:
        where = _first_difference(signed, candidate) or "(unlocated)"
        raise ArtifactError(
            "the candidate page run changes approved content in the reviewed languages "
            f"{list(reviewed_locales)} and cannot ride a locale backfill: {where}. "
            "This topic needs the ordinary review path."
        )
    signed_closure = tuple(sorted(baseline.closure))
    if signed_closure != tuple(sorted(candidate_closure)):
        raise ArtifactError(
            "the candidate page run pins a different upstream closure than the approved "
            f"publication: {signed_closure} != {tuple(sorted(candidate_closure))}"
        )
    if tuple(sorted(baseline.data_assets)) != tuple(sorted(candidate_data_assets)):
        raise ArtifactError(
            "the language-neutral data islands differ from the approved publication: "
            f"{tuple(sorted(baseline.data_assets))} != "
            f"{tuple(sorted(candidate_data_assets))}"
        )


# --------------------------------------------------------------------------------------
# Layer 2 — rendered bytes, minus the whitelist
# --------------------------------------------------------------------------------------


def whitelisted_differences(signed_html: str, candidate_html: str) -> dict[str, int]:
    """Per rule, how many of its regions actually moved between the two renders.

    Evidence, not a gate: it says *what* the whitelist absorbed, so a record never hides
    the fact that (say) the provenance line changed while nothing else did.
    """
    moved: dict[str, int] = {}
    for rule in RULES:
        signed = [m.group(0) for m in rule.pattern.finditer(signed_html)]
        candidate = [m.group(0) for m in rule.pattern.finditer(candidate_html)]
        count = abs(len(signed) - len(candidate)) + sum(
            1 for a, b in zip(signed, candidate) if a != b
        )
        if count:
            moved[rule.key] = count
    return moved


def prove_byte_equivalence(
    baseline: ContentBaseline, candidate_html: bytes
) -> tuple[str, dict[str, int]]:
    """Raise unless the candidate differs from the baseline only inside :data:`RULES`.

    Returns the shared digest of the redacted bytes and, per rule, how many of its
    regions actually differed — the evidence a record carries so a later
    ``verify-candidate`` can replay the proof without any superseded bundle.  The
    per-rule detail is only available when the baseline still has the bytes; a chained
    proof reports the digest alone, which is what the gate is made of anyway.
    """
    reference = baseline.reference_digest()
    candidate_digest, candidate_counts = redacted_digest(candidate_html)
    if reference != candidate_digest:
        raise ArtifactError(
            "the candidate page differs from the approved bytes outside the "
            f"{WHITELIST_VERSION} whitelist: redacted {reference} != "
            f"{candidate_digest} (whitelist hits on the candidate: {candidate_counts})"
        )
    reference_html = baseline.reference_html()
    if reference_html is None:
        return candidate_digest, {}
    return candidate_digest, whitelisted_differences(
        reference_html, candidate_html.decode("utf-8")
    )
