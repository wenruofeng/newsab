"""Lint engine.

Two families of check, both driven entirely by ``data/*.yaml`` so that the word lists are
reviewable by a non-programmer and versionable independently of the code:

* :func:`lint_text` — presentation-marker / causal / factual-verdict / scope rules;
* :func:`check_quantifier` — binds a quantifier phrase to the number it claims (§3.3 S8).

Severity is per *profile*, not per rule.  The same causal-language hit is a hard failure
in an S4 proposition (§4.2.2 says "打回") and a flag in an S7 editorial sentence (§3.3 S8
says "自动 flag ... 需人工或 judge 确认后放行").  Encoding that once, here, keeps the two
stages from drifting apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from ..io import load_yaml_text

from ..enums import LintVerdict

DATA_DIR = Path(__file__).parent / "data"
LEXICON_PATH = DATA_DIR / "lexicons.yaml"
QUANTIFIER_PATH = DATA_DIR / "quantifiers.yaml"


@dataclass(frozen=True)
class LintFinding:
    rule: str
    verdict: LintVerdict
    matched: str
    span: tuple[int, int]
    message: str
    lang: str
    suggestion: Optional[str] = None

    def __str__(self) -> str:  # pragma: no cover - display only
        where = f"[{self.span[0]}:{self.span[1]}]"
        tail = f" — {self.suggestion}" if self.suggestion else ""
        return f"{self.verdict.value.upper()} {self.rule} {where} {self.matched!r}: {self.message}{tail}"


@dataclass(frozen=True)
class LintProfile:
    """Which rules run for a given kind of text, and how hard each one bites."""

    name: str
    severities: dict[str, LintVerdict]
    #: Rules whose *absence* is the finding (currently only ``presentation_marker``).
    require: tuple[str, ...] = field(default=())


#: An S4 ``observation.proposition`` — the strictest profile (§4.2.2 invariant 2).
_OBSERVATION = LintProfile(
    name="observation_proposition",
    severities={
        "presentation_marker": LintVerdict.FAIL,
        "causal_language": LintVerdict.FAIL,
        "factual_verdict": LintVerdict.FLAG,
        "scope_subject": LintVerdict.FAIL,
    },
    require=("presentation_marker",),
)

#: An S7 ``claim.text`` / any reader-facing editorial sentence (§3.3 S8 L0).
_EDITORIAL = LintProfile(
    name="editorial_sentence",
    severities={
        "causal_language": LintVerdict.FLAG,
        "factual_verdict": LintVerdict.FLAG,
        "scope_subject": LintVerdict.FAIL,
    },
)

#: Free-text metadata a human wrote for other humans (source notes, topic blurbs).  Only
#: the red line applies; requiring "is presented as" in a media card would be nonsense.
_METADATA = LintProfile(
    name="metadata_text",
    severities={"scope_subject": LintVerdict.FAIL, "factual_verdict": LintVerdict.FLAG},
)

PROFILES: dict[str, LintProfile] = {
    p.name: p for p in (_OBSERVATION, _EDITORIAL, _METADATA)
}


@lru_cache(maxsize=1)
def load_lexicons(path: Optional[str] = None) -> dict:
    return load_yaml_text(Path(path or LEXICON_PATH).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_quantifiers(path: Optional[str] = None) -> dict:
    return load_yaml_text(Path(path or QUANTIFIER_PATH).read_text(encoding="utf-8"))


def _base_lang(lang: str) -> str:
    """Fall back from ``zh-TW`` to ``zh-CN``'s list rather than silently linting nothing."""
    lex = load_lexicons()
    if lang in lex["languages"]:
        return lang
    prefix = lang.split("-")[0]
    for known in lex["languages"]:
        if known.split("-")[0] == prefix:
            return known
    return ""


def _iter_term_hits(text: str, terms: Iterable[str], word_boundary: bool):
    for term in terms:
        pattern = rf"\b{re.escape(term)}\b" if word_boundary else re.escape(term)
        for m in re.finditer(pattern, text, flags=re.IGNORECASE if word_boundary else 0):
            yield term, m.span()


def _drop_subsumed(findings: list[LintFinding]) -> list[LintFinding]:
    """Keep the longest match when phrases nest.

    ``almost all`` contains ``all`` and ``几乎全部`` contains ``全部``; reporting both would
    fail a correct sentence against the *inner* phrase's bounds.  Longest match wins.
    """
    kept: list[LintFinding] = []
    for f in findings:
        if any(
            g is not f
            and g.rule == f.rule
            and g.span[0] <= f.span[0]
            and f.span[1] <= g.span[1]
            and (g.span[1] - g.span[0]) > (f.span[1] - f.span[0])
            for g in findings
        ):
            continue
        kept.append(f)
    return kept


def lint_text(text: str, lang: str, profile: str = "observation_proposition") -> list[LintFinding]:
    """Run every rule of ``profile`` over ``text``.

    Returns findings in document order.  An unknown language yields a single ``FLAG``
    finding rather than an empty (falsely clean) result — silence about an unlintable
    language would be exactly the kind of invisible gap D5 tells us to make explicit.
    """
    if profile not in PROFILES:
        raise KeyError(f"unknown lint profile {profile!r}; known: {sorted(PROFILES)}")
    prof = PROFILES[profile]
    lex = load_lexicons()
    resolved = _base_lang(lang)
    if not resolved:
        return [
            LintFinding(
                rule="lexicon_coverage",
                verdict=LintVerdict.FLAG,
                matched="",
                span=(0, 0),
                message=(
                    f"no lint lexicon for language {lang!r}; this text was NOT mechanically "
                    "checked and needs judge or human review"
                ),
                lang=lang,
                suggestion=f"add a {lang!r} section to lints/data/lexicons.yaml",
            )
        ]

    word_boundary = bool(lex["languages"][resolved]["word_boundary"])
    findings: list[LintFinding] = []

    for rule_name, severity in prof.severities.items():
        rule = lex["rules"].get(rule_name)
        if rule is None:
            continue
        kind = rule["kind"]

        if kind == "required_any":
            if rule_name not in prof.require:
                continue
            terms = rule["terms"].get(resolved, [])
            if terms and not any(True for _ in _iter_term_hits(text, terms, word_boundary)):
                findings.append(
                    LintFinding(
                        rule=rule_name,
                        verdict=severity,
                        matched="",
                        span=(0, len(text)),
                        message=(
                            "proposition does not say how the article *presents* something "
                            "(§4.2.2 invariant 2)"
                        ),
                        lang=resolved,
                        suggestion=(
                            "phrase it as 被呈现为 / 被描述为 …"
                            if resolved.startswith("zh")
                            else "phrase it as 'is presented as' / 'is framed as' …"
                        ),
                    )
                )
            continue

        if kind in ("forbidden_any", "flagged_any"):
            terms = rule["terms"].get(resolved, [])
            for term, span in _iter_term_hits(text, terms, word_boundary):
                findings.append(
                    LintFinding(
                        rule=rule_name,
                        verdict=severity,
                        matched=term,
                        span=span,
                        message=rule.get("message", rule_name),
                        lang=resolved,
                    )
                )
            continue

        if kind == "forbidden_pattern":
            for pattern in rule.get("patterns", {}).get(resolved, []):
                for m in re.finditer(pattern, text):
                    findings.append(
                        LintFinding(
                            rule=rule_name,
                            verdict=severity,
                            matched=m.group(0),
                            span=m.span(),
                            message=rule.get("message", rule_name),
                            lang=resolved,
                            suggestion=(rule.get("suggestion") or {}).get(resolved),
                        )
                    )
            continue

        raise ValueError(f"unknown lint rule kind {kind!r} for rule {rule_name!r}")

    findings = _drop_subsumed(findings)
    findings.sort(key=lambda f: (f.span[0], f.rule))
    return findings


def check_quantifier(
    text: str,
    lang: str,
    *,
    prevalence: Optional[float] = None,
    divergence: Optional[float] = None,
) -> list[LintFinding]:
    """Bind every quantifier phrase in ``text`` to the number it is standing in for.

    ``prevalence`` is a share of **independent reporting clusters** (D7) in [0, 1];
    ``divergence`` is the A1 divergence metric of the angle the sentence came from.
    A phrase whose table entry needs a number we were not given produces a ``FLAG``:
    an unbindable quantifier is precisely the thing S8 exists to catch.
    """
    table = load_quantifiers()
    resolved = _base_lang(lang) or lang
    lex = load_lexicons()
    word_boundary = bool(lex["languages"].get(resolved, {}).get("word_boundary", True))

    # Collect matches first, then keep only maximal spans.  This has to happen before the
    # bounds are evaluated: when "almost all" is correct at 0.95 it produces no finding, so
    # filtering *findings* would leave the nested "all" to fail a perfectly good sentence.
    matches: list[tuple[str, str, tuple[int, int], object]] = []
    for family in ("prevalence", "comparative"):
        for phrase, spec in (table[family].get(resolved) or {}).items():
            for _, span in _iter_term_hits(text, [phrase], word_boundary):
                matches.append((family, phrase, span, spec))

    maximal = [
        m
        for m in matches
        if not any(
            o is not m
            and o[2][0] <= m[2][0]
            and m[2][1] <= o[2][1]
            and (o[2][1] - o[2][0]) > (m[2][1] - m[2][0])
            for o in matches
        )
    ]

    findings: list[LintFinding] = []
    for family, phrase, span, spec in maximal:
        if family == "prevalence":
            low, high = float(spec[0]), float(spec[1])
            if prevalence is None:
                findings.append(
                    LintFinding(
                        rule="quantifier_unbound",
                        verdict=LintVerdict.FLAG,
                        matched=phrase,
                        span=span,
                        message=f"quantifier {phrase!r} has no prevalence value to bind to",
                        lang=resolved,
                    )
                )
            elif not (low <= prevalence <= high):
                findings.append(
                    LintFinding(
                        rule="quantifier_range",
                        verdict=LintVerdict.FAIL,
                        matched=phrase,
                        span=span,
                        message=(
                            f"{phrase!r} requires prevalence in [{low:g}, {high:g}] "
                            f"but the measured value is {prevalence:.3g} "
                            f"(table {table['table_version']})"
                        ),
                        lang=resolved,
                    )
                )
        else:
            floor = float(spec["min_divergence"])
            if divergence is None:
                findings.append(
                    LintFinding(
                        rule="quantifier_unbound",
                        verdict=LintVerdict.FLAG,
                        matched=phrase,
                        span=span,
                        message=f"comparative {phrase!r} has no divergence value to bind to",
                        lang=resolved,
                    )
                )
            elif divergence < floor:
                findings.append(
                    LintFinding(
                        rule="quantifier_range",
                        verdict=LintVerdict.FAIL,
                        matched=phrase,
                        span=span,
                        message=(
                            f"{phrase!r} requires divergence >= {floor:g} but the angle's "
                            f"divergence is {divergence:.3g} (table {table['table_version']})"
                        ),
                        lang=resolved,
                    )
                )

    findings.sort(key=lambda f: (f.span[0], f.rule))
    return findings


def worst(findings: Iterable[LintFinding]) -> LintVerdict:
    """The strongest verdict present — ``pass`` when there is nothing to report."""
    verdicts = {f.verdict for f in findings}
    if LintVerdict.FAIL in verdicts:
        return LintVerdict.FAIL
    if LintVerdict.FLAG in verdicts:
        return LintVerdict.FLAG
    return LintVerdict.PASS
