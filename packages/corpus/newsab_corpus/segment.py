"""Deterministic paragraph and sentence segmentation.

Sentence IDs are permanent (§4.1) — every quote, every observation and every claim on the
site is an offset into this function's output.  So it has exactly two obligations:

1. **Deterministic.** Same text + same ``SPLITTER_VERSION`` => same split, forever.  No
   model, no locale lookup, no dictionary that might update underneath us.
2. **Honest about what it cannot do.** Chinese, Japanese, Korean and English are handled
   by rules tuned for news prose.  An unknown language falls back to a conservative
   splitter and the caller is told, rather than being given a confident wrong answer.

Bumping ``SPLITTER_VERSION`` invalidates every sentence ID produced by the old one.  That
is not a bug — it is why the version goes in the manifest — but it means a bump requires
re-ingesting the corpus and re-running annotation, so treat it as expensive.

Version history:

* ``split-0.1.0`` — initial zh/en rules + conservative fallback.
* ``split-0.2.0`` — same segmentation rules; ``strip_residue`` (``strip-0.1.0``,
  ``staging.py``) now runs on every staged body before segmentation.
  The sentence *sets* of residue-affected articles change,
  which is exactly what a splitter bump signals.
* ``split-0.3.0`` — two additions, both inert on a body that does not opt into them.
  ``strip_residue`` gains ``strip-0.2.0``'s *inline* rules, which excise
  a leaked page-control call from within a line instead of dropping the line; and
  :func:`split_paragraphs` accepts ``paragraph_break="single_newline"`` for bodies taken
  from a JSON-LD ``articleBody``, where a single newline is the paragraph boundary.
  A corpus built before this version is unaffected: no existing staged body carries the
  inline shapes, and ``blank_line`` remains the default.  Rebuild + re-annotate is still
  required for any article that *does* change under the new rules.
* ``split-0.4.0`` — ``ja`` joins the tuned languages, routed to the same CJK terminal rules
  Chinese already used (the terminal and closer sets were never Chinese-specific).  Found
  by the first Japanese corpus: the fallback splits on a terminal *followed by whitespace*,
  and Japanese prose puts no space after ``。``, so 117 of 119 Japanese articles came out
  with one "sentence" per paragraph — every anchor a whole paragraph, and page quotes that
  would have blown the half-an-article render budget.  **Inert for every corpus built
  before it**: no article in any earlier topic is ``ja``, and the zh/en/fallback rules are
  untouched, so no existing sentence ID moves and nothing needs re-annotating.
* ``split-0.5.0`` — ``ko`` joins the tuned languages before the first Korean corpus.
  Korean news prose normally separates sentences with ASCII terminals and whitespace,
  but the generic fallback loses boundaries when a terminal sits inside a closing quote.
  The Korean rule absorbs those closers, protects decimal points, and then splits only at
  a whitespace or paragraph end.  **Inert for every earlier corpus**: the repository had
  no Korean article when this version shipped, and every other language's rules are
  unchanged.
* ``split-0.6.0`` — ``de`` and ``tr`` join the tuned languages before the first German or
  Turkish corpus.  Both are Latin-script languages whose news prose uses ASCII terminals,
  so the generic fallback looks adequate and is not: German writes ordinals and dates with
  a trailing period (``am 24. April``, ``im 20. Jahrhundert``) and Turkish does the same
  (``2. kez``), and both use ``.`` as a thousands separator — the fallback splits every one
  of those in half, shifting every following sentence ID in the paragraph.  Capitalisation
  is no help in German, where every noun is capitalised.  The shared Latin rule therefore
  keeps a period internal when it sits between digits, follows a one- or two-digit number,
  follows a single-letter initial, follows a known abbreviation, or is not followed by
  whitespace at all.  **Inert for every earlier corpus**: the repository had no German or
  Turkish article when this version shipped, and no other language's rules are touched.
* ``split-0.7.0`` — ``fr`` and ``mn`` join the tuned languages before the first French or
  Mongolian corpus, both on the shared Latin rule but with its ordinal clause **off**.
  That clause is the one part of the German rule that does not travel: German and Turkish
  write an ordinal as a bare number plus a period, so "24." is almost never a sentence
  end, whereas French writes ``1er`` / ``2e`` and Mongolian writes ``1-р`` / ``1 дүгээр``
  — in both, a period after a small number really does end the sentence ("… porte sur
  1,6 milliard de dollars, soit 51.").  What each language needs instead is its own
  abbreviation set: French news prose is full of ``M.`` and ``av. J.-C.``, and Mongolian
  puts personal-name initials in front of every surname (``Л. Оюун-Эрдэнэ``), so the
  single-letter-initial rule has to recognise Cyrillic capitals too.  French also writes
  a narrow no-break space before ``? ! ; :``, which :func:`normalize_text` now folds to a
  plain space along with the no-break space it already folded.  **Inert for every earlier
  corpus**: the repository had no French or Mongolian article when this version shipped,
  no other language's rules are touched, and no existing body contains U+202F.
* ``split-0.8.0`` — ``hi`` and ``ur`` join the tuned languages, found by the first
  Hindi/Urdu corpus (aabb-canal-gate-2026): the fallback splits only on ``[.!?。！？]`` followed
  by whitespace and knows neither the Devanagari danda ``।`` (U+0964) nor the Urdu full
  stop ``۔`` (U+06D4), so danda-punctuated articles came out with whole paragraphs as one
  "sentence" (measured: a 2,631-character sentence holding 19 danda).  ``।``/``॥`` (hi)
  and ``۔``/``؟`` (ur) are *hard* terminals splitting like CJK — no following whitespace
  required, closers absorbed; ASCII terminals keep the shared Latin soft rule with
  per-language abbreviation sets; Devanagari name initials ("जे. पी. नड्डा") ride in the
  Hindi abbreviation set as the closed set of transliterated English letter names, because
  a shape rule cannot tell an initial from the many one- or two-code-point Hindi words
  that end sentences.  **Not inert**: aabb-canal-gate-2026 holds 4 ``hi`` + 2 ``ur`` articles
  built on ``split-0.7.0`` — rebuilding re-splits them and shifts their sentence IDs, so
  that topic's rebuild ships together with re-annotation of the affected clusters.
  No other topic has a ``hi``/``ur`` article and no other language's rules move.
* ``split-0.9.0`` — staging standfirsts become the body's first paragraph when the
  extracted body does not already start with them, using the collector-declared paragraph
  convention; ``strip_residue`` ``strip-0.4.0`` also removes newly measured tail chrome.
  Both changes can move sentence IDs, so every affected article must be rebuilt and its
  changed clusters re-annotated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SPLITTER_VERSION = "split-0.9.0"

#: Languages with rules tuned for them.  Anything else uses :func:`_split_fallback`.
SUPPORTED_LANGS = ("zh", "ja", "ko", "en", "de", "tr", "fr", "mn", "hi", "ur")

# --- CJK (Chinese and Japanese) ----------------------------------------------------------

#: Sentence-final punctuation in CJK news prose.
_ZH_TERMINALS = "。！？!?；;…"
#: Closers that belong to the sentence they follow (quote marks, brackets).
_ZH_CLOSERS = "」』】）)》”’\"'"

# --- Korean ------------------------------------------------------------------------------

# Korean news prose uses ASCII sentence terminals, often followed by a closing Korean or
# curly quote.  Keep this separate from CJK's no-whitespace splitter: a period inside a
# Latin abbreviation or URL is much more common in Korean copy than in zh/ja copy.
_KO_TERMINALS = ".!?…"
_KO_CLOSERS = "\"'”’」』】）)]}》"

# --- English -----------------------------------------------------------------------------

#: Abbreviations after which a period is not a sentence end.  Recall matters more than
#: brevity: a missed abbreviation splits one sentence into two and shifts every following
#: sentence ID in the paragraph.
_EN_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sen", "rep", "gov", "sgt", "lt", "col", "gen",
    "st", "jr", "sr", "inc", "ltd", "co", "corp", "univ", "dept", "est", "fig",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun",
    "vs", "etc", "eg", "ie", "cf", "al", "no", "vol", "pp", "approx",
    "u.s", "u.k", "u.n", "e.u", "d.c", "ph.d", "b.a", "m.a", "a.m", "p.m",
}

_EN_SENTENCE_END = re.compile(r'([.!?][."\'”’)\]]*)(\s+)(?=[\"\'“‘(\[]?[A-Z0-9])')
_TRAILING_INITIAL = re.compile(r"\b[A-Z]\.$")

# --- German and Turkish (shared Latin rule) ----------------------------------------------

# Both languages write news prose with ASCII terminals and a space after them, so the
# generic fallback *looks* adequate.  It is not: both put a period after an ordinal number
# ("am 24. April", "im 20. Jahrhundert", "2. kez") and both use "." as a thousands
# separator, and the fallback splits every one of those in half.  German capitalises every
# noun, so "terminal + space + capital" — the signal the English rule leans on — carries no
# information here.  What is left is: a period is internal unless whitespace follows it and
# nothing in front of it says otherwise.
_LATIN_TERMINALS = ".!?…"
_LATIN_CLOSERS = "\"'”’»«)]}›"

#: Period-bearing abbreviations in German news prose.  Includes the halves of spaced forms
#: ("z. B.", "u. a.", "d. h.") because each half ends in a period of its own.
_DE_ABBREVIATIONS = {
    "z", "b", "u", "a", "d", "h", "o", "s", "v", "t", "i", "r", "g", "e", "f",
    "bzw", "ca", "ggf", "evtl", "usw", "sog", "inkl", "exkl", "zzgl", "bspw", "etc",
    "vgl", "dt", "engl", "ehem", "mind", "max", "mio", "mrd", "tsd", "nr", "abs",
    "art", "bd", "aufl", "bsp", "hrsg", "kap", "lt", "pkt", "tel", "ff", "jh", "jhd",
    "dr", "prof", "dipl", "ing", "hr", "fr", "st", "jun", "sen", "bzgl", "ggfs",
    "gem", "einschl", "urspr", "insb", "ehm", "bes", "allg", "verg", "rd", "z.b",
    "u.a", "d.h", "v.a", "z.t", "i.d.r", "u.ä", "o.ä", "n.chr", "v.chr",
    "jan", "feb", "mär", "maer", "apr", "jul", "aug", "sep", "sept", "okt", "nov", "dez",
}

#: Period-bearing abbreviations in Turkish news prose.  Turkish takes suffixes onto
#: abbreviations after an apostrophe ("TL.'nin"), which the closer/whitespace rule already
#: keeps internal; what this set has to carry is the bare forms.
_TR_ABBREVIATIONS = {
    "dr", "doç", "prof", "av", "sn", "alb", "gen", "yrd", "öğr", "gör", "uzm", "müh",
    "bşk", "md", "ltd", "şti", "a.ş", "t.c", "vb", "vs", "bkz", "örn", "vd", "yy",
    "mah", "cad", "sok", "sk", "blv", "apt", "no", "s", "çev", "haz", "ed", "age",
    "agm", "fak", "üniv", "mrk", "tl", "krş", "bkz", "bak", "hz", "st", "mm", "cm",
    "km", "kg", "gr", "milyon", "mlyr",
}

#: Period-bearing abbreviations in French news prose.  "m" carries the weight here:
#: "M. Macron" is the ordinary way a French paper names a man on second reference, and a
#: missed "M." splits every such sentence in two.  The halves of spaced and hyphenated
#: forms ("p. ex.", "c.-à-d.", "av. J.-C.") each end in a period of their own.
_FR_ABBREVIATIONS = {
    "m", "mm", "mme", "mmes", "mlle", "mlles", "dr", "drs", "pr", "me", "mgr", "st",
    "ste", "sts", "stes", "sté", "ets", "cie", "éd", "ed", "éds", "vol", "chap", "fig",
    "réf", "ref", "tél", "tel", "av", "bd", "pl", "bt", "app", "art", "arts", "al",
    "env", "cf", "etc", "ex", "p", "pp", "ibid", "op", "cit", "suiv", "sq", "trad",
    "n", "nos", "num", "min", "max", "moy", "hab", "dép", "dir", "adj", "gén", "col",
    "lt", "cap", "sgt", "amb", "prof", "ing", "arch", "inc", "ltd", "sarl", "sas",
    "j.-c", "ap", "apr", "sept", "janv", "févr", "fevr", "juil", "oct", "nov", "déc",
    "dec", "c.-à-d", "c.-a-d", "p.-s", "s.a", "s.a.s", "s.a.r.l",
}

#: Period-bearing abbreviations in Mongolian news prose.  Mongolian writes most
#: institutional short forms as bare Cyrillic initialisms with no period at all
#: (УИХ, ХХК, ТӨХК), so this set is short by nature; what it has to carry is the handful
#: of lexical abbreviations and the units that appear in mining copy.
_MN_ABBREVIATIONS = {
    "г", "м", "г.м", "б.а", "ж", "ж.нь", "х", "х.х", "мян", "тэрбум", "сая", "проф",
    "акад", "др", "тн", "кг", "гр", "км", "см", "мм", "л", "мл", "кв", "куб",
    "тэрб", "төг", "ам", "долл", "хув", "он", "оны", "дүгээр", "дугаар",
}

#: A single capital letter plus a period is an initial, not a sentence end.  The class
#: spans every capital the tuned Latin-rule languages use, Cyrillic included: Mongolian
#: news prose puts an initial in front of almost every personal name ("Л. Оюун-Эрдэнэ").
_LATIN_TRAILING_INITIAL = re.compile(
    r"(?:^|[\s(\[\"'“‘«])[A-ZÀ-ÖØ-ÞĀ-ſЀ-Я]\.$"
)

# --- Hindi and Urdu (shared hard-terminal rule over the Latin soft rule) -----------------

# Hindi news prose ends a sentence with the danda "।" (some outlets use the ASCII period
# instead — both occur), Urdu with "۔" and "؟".  None of those characters is ever internal
# to a number or an abbreviation, so they are *hard* terminals: they end the sentence with
# or without following whitespace, exactly as CJK treats "。".  The ASCII terminals both
# languages also use keep the shared Latin soft rule.
_HI_HARD_TERMINALS = "।॥"
_UR_HARD_TERMINALS = "۔؟"

#: Period-bearing abbreviations in Hindi news prose.  Hindi writes most honorifics with a
#: period ("डॉ. सिंह", "प्रो. शर्मा"); institutional short forms are usually bare Latin
#: initialisms (PTI, IWT) with no period.  Devanagari *name initials* ("जे. पी. नड्डा")
#: are transliterated English letter names — a closed set, listed here rather than matched
#: by shape, because most common Hindi words are also one or two code points and a shape
#: rule would swallow every short sentence-final word before an ASCII period.
_HI_ABBREVIATIONS = {
    "डॉ", "प्रो", "पं", "स्व", "इं", "ले",
    "ए", "बी", "सी", "डी", "ई", "एफ", "जी", "एच", "आई", "जे", "के", "एल", "एम",
    "एन", "ओ", "पी", "क्यू", "आर", "एस", "टी", "यू", "वी", "डब्ल्यू", "एक्स", "वाई", "जेड",
}

#: Urdu spells its honorifics out ("ڈاکٹر") rather than abbreviating with a period, so
#: this set carries nothing yet; the digit and initial guards still apply to the ASCII
#: periods that reach Urdu copy through numbers and embedded Latin text.
_UR_ABBREVIATIONS: set[str] = set()

#: A period that follows a one- or two-digit number is an ordinal ("24. April", "2. kez")
#: far more often than it is the end of a sentence.  Four-digit years are left alone, so a
#: sentence ending "… im Jahr 2024." still splits.
_LATIN_ORDINAL = re.compile(r"(?:^|[^\d])\d{1,2}\.$")


def _latin_period_is_internal(
    prefix: str,
    abbreviations: set[str],
    ordinal_periods: bool = True,
    trailing_initial: re.Pattern[str] = _LATIN_TRAILING_INITIAL,
) -> bool:
    """Does the period ending ``prefix`` belong inside the sentence?

    ``ordinal_periods`` is the one clause that does not travel across the Latin-rule
    languages.  German and Turkish write an ordinal as a bare number plus a period, so a
    period after a small number is overwhelmingly internal.  French and Mongolian do not
    ("1er" / "2e", "1-р" / "1 дүгээр"), so for them the same clause would swallow every
    sentence that happens to end in a small number.
    """
    tail = prefix.rstrip()
    if not tail.endswith("."):
        return False
    if ordinal_periods and _LATIN_ORDINAL.search(tail):
        return True
    if trailing_initial.search(tail):
        return True
    word = re.split(r"[\s(\[\"'“‘»]", tail)[-1].rstrip(".").lower()
    return bool(word) and word in abbreviations


def _split_latin(
    paragraph: str,
    abbreviations: set[str],
    ordinal_periods: bool = True,
    hard_terminals: str = "",
    trailing_initial: re.Pattern[str] = _LATIN_TRAILING_INITIAL,
) -> list[str]:
    """Split German, Turkish, French, Mongolian, Hindi or Urdu news prose.

    A boundary is a terminal, plus any repeated terminals and closing punctuation,
    followed by whitespace or the paragraph end — and not ruled internal by
    :func:`_latin_period_is_internal`.  A character in ``hard_terminals`` (the Devanagari
    danda, the Urdu full stop) is never internal to a number or an abbreviation, so it
    ends the sentence like a CJK terminal: whitespace after it is not required and no
    internal-period test runs.  Under-splitting is the deliberate failure mode:
    a longer anchor still quotes whole sentences, a shorter one quotes half of one.
    """
    terminals = _LATIN_TERMINALS + hard_terminals
    sentences: list[str] = []
    start = 0
    i = 0
    while i < len(paragraph):
        ch = paragraph[i]
        if ch not in terminals:
            i += 1
            continue
        hard = ch in hard_terminals
        if (
            ch == "."
            and i > 0
            and i + 1 < len(paragraph)
            and paragraph[i - 1].isdigit()
            and paragraph[i + 1].isdigit()
        ):
            i += 1  # 2.400 / 1.000.000 — thousands separator
            continue
        end = i + 1
        while end < len(paragraph) and paragraph[end] in terminals + _LATIN_CLOSERS:
            end += 1
        if not hard and end < len(paragraph) and not paragraph[end].isspace():
            i = end
            continue
        if ch == "." and _latin_period_is_internal(
            paragraph[start:i + 1], abbreviations, ordinal_periods, trailing_initial
        ):
            i = end
            continue
        nxt = end
        while nxt < len(paragraph) and paragraph[nxt].isspace():
            nxt += 1
        if (
            not hard
            and nxt < len(paragraph)
            and paragraph[nxt].isalpha()
            and paragraph[nxt].islower()
        ):
            # None of these languages starts a sentence with a lower-case letter, so
            # this is an attribution running on after a closing quote — 'Döner ist
            # türkisch." dedi' / '… gehört zu Deutschland", sagte er' / '… l\'uranium »,
            # a-t-il dit' / '… гэрээ." гэж мэдэгдэв'.
            i = end
            continue
        candidate = paragraph[start:end].strip()
        if candidate:
            sentences.append(candidate)
        while end < len(paragraph) and paragraph[end].isspace():
            end += 1
        start = end
        i = end
    tail = paragraph[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


@dataclass(frozen=True)
class SegmentationResult:
    """Paragraphs of sentences, plus whether real rules or the fallback were used."""

    paragraphs: list[list[str]]
    lang: str
    splitter_version: str
    used_fallback: bool

    @property
    def sentence_count(self) -> int:
        return sum(len(p) for p in self.paragraphs)


def normalize_text(raw: str) -> str:
    """Whitespace normalisation applied *before* splitting, and therefore before IDs exist.

    Deliberately minimal: it collapses runs of spaces and normalises line endings, and
    nothing else.  Anything more (curly quotes, full-width punctuation) would make the
    stored sentence differ from the page, and §2.5 promises a reader that Ctrl-F finds it.
    """
    text = (
        raw.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace(" ", " ")
        .replace(" ", " ")
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


#: How a staged body marks a paragraph boundary.  ``blank_line`` is what a body copied
#: out of rendered HTML looks like.  ``single_newline`` is what a JSON-LD ``articleBody``
#: looks like: the publisher's own paragraph breaks survive as lone ``\n`` characters, and
#: reading those as intra-paragraph whitespace collapses the whole article into P01 —
#: sentence anchors stay correct, but every "which paragraph" answer becomes useless.
PARAGRAPH_BREAKS = ("blank_line", "single_newline")


def split_paragraphs(text: str, paragraph_break: str = "blank_line") -> list[str]:
    """Paragraph blocks, split by the convention the body was captured under.

    ``blank_line`` (default): blank-line separated blocks, single newlines inside a block
    kept as spaces.  ``single_newline``: every newline is a paragraph boundary, which is
    the JSON-LD ``articleBody`` convention.
    """
    if paragraph_break not in PARAGRAPH_BREAKS:
        raise ValueError(
            f"unknown paragraph_break {paragraph_break!r}; expected one of {PARAGRAPH_BREAKS}"
        )
    normalized = normalize_text(text)
    if paragraph_break == "single_newline":
        return [b.strip() for b in normalized.split("\n") if b.strip()]
    blocks = re.split(r"\n\s*\n", normalized)
    return [re.sub(r"\s*\n\s*", " ", b).strip() for b in blocks if b.strip()]


def _split_cjk(paragraph: str) -> list[str]:
    sentences: list[str] = []
    buffer: list[str] = []
    i = 0
    while i < len(paragraph):
        ch = paragraph[i]
        buffer.append(ch)
        if ch in _ZH_TERMINALS:
            # Absorb repeated terminals ("……", "？！") and any closing quotes/brackets.
            j = i + 1
            while j < len(paragraph) and paragraph[j] in _ZH_TERMINALS + _ZH_CLOSERS:
                buffer.append(paragraph[j])
                j += 1
            sentences.append("".join(buffer).strip())
            buffer = []
            i = j
            continue
        i += 1
    tail = "".join(buffer).strip()
    if tail:
        sentences.append(tail)
    return [s for s in sentences if s]


def _looks_like_abbreviation(chunk: str) -> bool:
    tail = chunk.rstrip()
    if not tail.endswith("."):
        return False
    if _TRAILING_INITIAL.search(tail):  # "J. Smith"
        return True
    word = re.split(r"[\s(\[\"']", tail)[-1].rstrip(".").lower()
    return word in _EN_ABBREVIATIONS


def _split_en(paragraph: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    for match in _EN_SENTENCE_END.finditer(paragraph):
        candidate = paragraph[start : match.end(1)]
        if _looks_like_abbreviation(candidate):
            continue
        sentences.append(candidate.strip())
        start = match.end(2)
    tail = paragraph[start:].strip()
    if tail:
        sentences.append(tail)
    return [s for s in sentences if s]


def _split_ko(paragraph: str) -> list[str]:
    """Split Korean news prose without losing quote-final sentence boundaries.

    A boundary is a terminal (plus repeated terminals and closing punctuation) followed
    by whitespace or paragraph end.  Decimal points stay internal.  This deliberately
    does not guess at a period followed immediately by Latin or Hangul text: preserving
    one longer anchor is safer than splitting an abbreviation or URL in half.
    """
    sentences: list[str] = []
    start = 0
    i = 0
    while i < len(paragraph):
        ch = paragraph[i]
        if ch not in _KO_TERMINALS:
            i += 1
            continue
        if (
            ch == "."
            and i > 0
            and i + 1 < len(paragraph)
            and paragraph[i - 1].isdigit()
            and paragraph[i + 1].isdigit()
        ):
            i += 1
            continue
        end = i + 1
        while end < len(paragraph) and paragraph[end] in _KO_TERMINALS + _KO_CLOSERS:
            end += 1
        if end < len(paragraph) and not paragraph[end].isspace():
            i = end
            continue
        candidate = paragraph[start:end].strip()
        if candidate:
            sentences.append(candidate)
        while end < len(paragraph) and paragraph[end].isspace():
            end += 1
        start = end
        i = end
    tail = paragraph[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _split_fallback(paragraph: str) -> list[str]:
    """Language-agnostic last resort: split on terminal punctuation followed by a space.

    Conservative on purpose — for an unhandled language, under-splitting produces longer
    but still correct anchors, whereas over-splitting produces anchors that quote half a
    sentence.
    """
    parts = re.split(r"(?<=[.!?。！？])\s+", paragraph)
    return [p.strip() for p in parts if p.strip()]


def split_sentences(paragraph: str, lang: str) -> list[str]:
    base = lang.split("-")[0].lower()
    if base in ("zh", "ja"):
        return _split_cjk(paragraph)
    if base == "ko":
        return _split_ko(paragraph)
    if base == "en":
        return _split_en(paragraph)
    if base == "de":
        return _split_latin(paragraph, _DE_ABBREVIATIONS)
    if base == "tr":
        return _split_latin(paragraph, _TR_ABBREVIATIONS)
    if base == "fr":
        return _split_latin(paragraph, _FR_ABBREVIATIONS, ordinal_periods=False)
    if base == "mn":
        return _split_latin(paragraph, _MN_ABBREVIATIONS, ordinal_periods=False)
    if base == "hi":
        return _split_latin(
            paragraph,
            _HI_ABBREVIATIONS,
            ordinal_periods=False,
            hard_terminals=_HI_HARD_TERMINALS,
        )
    if base == "ur":
        return _split_latin(
            paragraph,
            _UR_ABBREVIATIONS,
            ordinal_periods=False,
            hard_terminals=_UR_HARD_TERMINALS,
        )
    return _split_fallback(paragraph)


def segment(text: str, lang: str, paragraph_break: str = "blank_line") -> SegmentationResult:
    """Split a body into paragraphs of sentences."""
    base = lang.split("-")[0].lower()
    paragraphs = [
        split_sentences(p, lang) for p in split_paragraphs(text, paragraph_break)
    ]
    return SegmentationResult(
        paragraphs=[p for p in paragraphs if p],
        lang=lang,
        splitter_version=SPLITTER_VERSION,
        used_fallback=base not in SUPPORTED_LANGS,
    )
