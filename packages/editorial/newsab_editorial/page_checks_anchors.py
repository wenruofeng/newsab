"""Named things in an explanation paragraph must be anchored on the side that names them.

One defect class, three shapes.  The write stage's explanation paragraphs read as
reporting, so they attract reporting's specifics — an outlet's masthead, a figure, a
proper name.  ``style.md`` already states the rule ("Every outlet you name and every fact
you cite needs an anchor in that side's ``evidence``"), and the L1 judge panel already
catches the breaches.  Measured: the only panel escalation of a nine-locale ship was four
findings that were *all* this — facts genuinely present in the corpus whose anchors were
simply never attached — and a separate run fired on it twice in a row (six, then five
unanchored specifics).  A panel round costs three judges plus a fix run; the mechanical
half of that judgement costs nothing, so it belongs here.

**What this catches and what it does not.**  It catches *named but unanchored*: the
paragraph puts a specific on the page and the side's anchors contain nothing of it.  It
cannot catch *anchored but wrong* — a specific whose anchor exists but does not carry the
assertion ("Variety pairs the CinemaScore grade with the second-weekend gross **to argue
that audiences were not troubled**": both named things are anchored, the causal claim is
the writer's).  That half is entailment, and stays the judge panel's job
(``skills/write/references/panel.md``).  Everything here is therefore a **warning**: it is
a reading aid for the writer and the panel, never a refusal.

All warnings, no model, no network.  ``check_page`` runs this only when it is handed a
``registry`` — the stage-level ``page-check`` CLI passes one, the publish package's shared
re-render/verify path (``builder.render_locales``) does not, so an already-shipped page can
never start failing because a check was added after it went out (same safety switch as
the run-provenance check).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Iterator, Optional

from newsab_schema.enums import ClaimType
from newsab_schema.ids import SentenceId
from newsab_schema.models.corpus import Article, SourceRegistry
from newsab_schema.models.page import PageClaim, ReaderPage

# --- surface forms of an outlet name ----------------------------------------------------

#: Trailing words a masthead carries and a writer drops ("Jiemian News" written as
#: "Jiemian", "Cover News" as "The Cover").  One is dropped, never two: "Yangcheng Evening
#: News" keeps "Evening".
_GENERIC_MASTHEAD_TAIL = {
    "News",
    "Daily",
    "Times",
    "Post",
    "Online",
    "Weekly",
    "Journal",
    "Media",
    "Network",
    "Group",
    "Agency",
    "Press",
    "TV",
    "Radio",
}

#: A single-word alias is only trusted when the domain agrees with it (``Cover`` for
#: ``thecover.cn``, ``Jiemian`` for ``jiemian.com``).  Without that, dropping a generic
#: tail off a two-word masthead invents a common English noun and the check starts firing
#: on prose.  This is the one rule that keeps the outlet warning readable.
_MIN_SINGLE_WORD_ALIAS = 5


def _fold(text: str) -> str:
    """Strip diacritics, keep case.

    A writer who spells ``Guanchá`` for ``Guancha.cn`` is naming the outlet; a check that
    misses it because of one acute accent teaches nothing.  Case is *not* folded — case is
    what separates the masthead ``The Cover`` from the noun ``the cover``, and it is the
    cheapest false-positive guard this module has.
    """
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _domain_words(url: str) -> set[str]:
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    host = host[4:] if host.startswith("www.") else host
    return {label for label in host.split(".") if label}


#: Host labels that carry no masthead: a TLD, a platform word, or a word so common that
#: matching it would fire on ordinary prose.
_GENERIC_HOST_LABEL = {
    "www", "com", "net", "org", "co", "cn", "jp", "kr", "ru", "de", "fr", "id", "tr",
    "mn", "in", "uk", "us", "eu", "info", "news", "media", "online", "web", "site",
    "daily", "post", "times", "global", "world", "the", "group", "press", "radio", "tv",
}


#: Capitals and seats of government, which news prose uses for the government itself
#: ("the request that Seoul consider the matter carefully").  Many outlets are named after
#: their city, so the host label is a masthead *and* a metonym, and the metonym is far more
#: common in an explanation paragraph.  Measured: ``seoul.co.kr`` in the registry turned
#: every mention of the South Korean government into a false warning
#: (4 of the 6 outlet warnings over all 272 tracked pages).  The outlet is still matched by
#: its registered masthead; only the bare host label is withheld.
_METONYM_LABELS = {
    "seoul", "beijing", "tokyo", "washington", "moscow", "brussels", "london", "paris",
    "berlin", "delhi", "ankara", "jakarta", "taipei", "pyongyang", "kyiv", "tehran",
    "riyadh", "cairo", "canberra", "ottawa", "dublin", "rome", "madrid", "athens",
    "hanoi", "manila", "bangkok", "islamabad", "nairobi", "lagos", "abuja", "kabul",
}


def _domain_alias(url: str) -> Optional[str]:
    """The masthead a writer actually types when the registry holds the long form.

    Measured: the registry knows ``rfi_fr`` only as "Radio France
    Internationale" and ``sfen_fr`` as "Sfen — Revue Générale Nucléaire", while the page
    writes "RFI" and "Sfen".  Without this the short form falls through to the proper-name
    check, which cannot know the outlet is anchored, and produces a false warning on a
    correct page.  The host's own label is the writer's short form far more often than
    not, and the generic labels above are excluded so this never becomes a prose match.
    """
    labels = [
        l
        for l in _domain_words(url)
        if l not in _GENERIC_HOST_LABEL and l not in _METONYM_LABELS
    ]
    if len(labels) != 1:
        return None
    label = labels[0]
    return label if len(label) >= 3 and label.isalpha() else None


def _aliases(name_values: Iterable[str], url: str) -> set[str]:
    """Every spelling of one masthead worth looking for in an English pivot paragraph."""
    domain = "".join(sorted(_domain_words(url)))
    forms: set[str] = set()
    short = _domain_alias(url)
    if short:
        # Stored capitalised so the "never match an all-lower-case run" rule in
        # ``mentions`` still applies: "RFI"/"Sfen" match, "rfi" in a URL does not.
        forms.add(short.capitalize())
    for raw in name_values:
        name = _fold(raw).strip()
        if not re.search(r"[A-Za-z]", name):
            # A masthead with no Latin letters (澎湃新闻) cannot appear in the English
            # pivot; the English name of the same entry covers that outlet.
            continue
        candidates = {name}
        if name.startswith("The "):
            candidates.add(name[4:])
        for base in list(candidates):
            words = base.split()
            if len(words) > 1 and words[-1] in _GENERIC_MASTHEAD_TAIL:
                candidates.add(" ".join(words[:-1]))
            # "Guancha.cn" / "Huxiu.com" are registered with their TLD.
            stripped = re.sub(r"\.(cn|com|net|org|co|jp|kr|ru|de|fr|id|tr|mn|in)$", "", base)
            if stripped != base:
                candidates.add(stripped)
        for form in candidates:
            form = form.strip()
            if len(form) < 3 or not form[0].isupper():
                continue
            if " " not in form:
                # Single word: only when the domain vouches for it, and only when it is
                # long enough to be a masthead rather than an article.  An all-caps
                # masthead is exempt from the length floor — ``RFI`` and ``NPR`` are
                # three letters and unambiguous, and leaving them out sent them to the
                # proper-name check, which cannot know that ``rfi_fr`` is anchored.
                if len(form) < _MIN_SINGLE_WORD_ALIAS and not form.isupper():
                    continue
                if form.lower().replace("-", "") not in domain:
                    continue
            forms.add(form)
    return forms


@dataclass(frozen=True)
class OutletLexicon:
    """Masthead spelling → the source ids it could mean, for one page's corpus."""

    by_form: dict[str, frozenset[str]]

    @classmethod
    def build(
        cls, registry: Optional[SourceRegistry], articles: Iterable[Article]
    ) -> "OutletLexicon":
        """Only outlets the page's own corpus contains.

        An outlet with no article in the pinned run cannot be anchored on *either* side,
        so warning about it would say nothing a writer can act on; and matching all 300
        registry mastheads against every paragraph is where a name check turns into noise.
        """
        present = {a.source_id for a in articles}
        by_form: dict[str, set[str]] = {}
        for entry in (registry.sources if registry else []):
            if entry.id not in present:
                continue
            for form in _aliases(entry.name.values.values(), entry.url):
                by_form.setdefault(form, set()).add(entry.id)
        return cls({form: frozenset(ids) for form, ids in by_form.items()})

    def mentions(self, text: str) -> list[tuple[str, frozenset[str]]]:
        """Mastheads named in this paragraph, longest spelling first.

        Longest-first matters: "Yangcheng Evening News" and "Yangcheng Evening" are both
        registered spellings of one outlet, and the reader of a warning should see the
        words that are actually on the page.
        """
        folded = _fold(text)
        hits: list[tuple[str, frozenset[str]]] = []
        spent: list[tuple[int, int]] = []
        for form in sorted(self.by_form, key=len, reverse=True):
            for m in re.finditer(
                rf"(?<![\w-]){re.escape(form)}(?![\w-])", folded, re.IGNORECASE
            ):
                # Case-insensitive, because mastheads are registered in their house style
                # ("USA TODAY") and written in ordinary title case ("USA Today").  But a
                # match that is *entirely* lower case is prose, not a masthead — that one
                # rule is what keeps "the cover story" and "on paper" out of this list.
                if m.group(0).islower():
                    continue
                if any(s <= m.start() and m.end() <= e for s, e in spent):
                    continue
                spent.append((m.start(), m.end()))
                hits.append((m.group(0), self.by_form[form]))
                break
        return hits


# --- numbers ----------------------------------------------------------------------------

#: A figure, after ``_digit_fold`` has already taken the thousands separators out.  The
#: pattern deliberately stops at the first non-digit: an earlier version allowed separators
#: inside the token and turned "since 1997, 27 mines" into the figure ``1997, 27``, which
#: appears in no sentence anywhere and warned on every page that carried it.
_NUMBER_TOKEN = re.compile(r"\d+(?:\.\d+)?")
_FOOTNOTE_MARK = re.compile(r"\[\^\d{1,2}\]")
#: A magnitude word right after the digits.  CJK coverage writes large numbers on a
#: different scale (12亿 for "1.2 billion", 1500万 for "15 million"), so a scaled English
#: figure is not comparable to a CJK anchor by string match and is skipped there rather
#: than warned about.  Documented limitation, not an oversight.
_SCALED = re.compile(
    r"^\s*(?:million|billion|trillion|thousand|bn|m\b|k\b)", re.IGNORECASE
)
#: One thousands separator inside a grouped number.  The lookahead walks the whole run
#: of three-digit groups, so "1 234 567" loses both separators rather than only the last.
#: ``\u202f`` and ``\u2009`` are the narrow/thin spaces French typography uses, ``\u00a0``
#: the non-breaking space that survives a copy-paste out of a web page.
_GROUP_SEPARATOR = re.compile(
    r"(?<=\d)[,\u202f\u2009\u00a0' ](?=\d{3}(?:[,\u202f\u2009\u00a0' ]\d{3})*(?!\d))"
)

#: Languages that rewrite magnitudes on the 万/億 scale.
_CJK_SCALE_LANGS = {"zh", "zh-cn", "zh-tw", "zh-hans", "zh-hant", "ja", "ko"}


def _digit_fold(text: str) -> str:
    """ASCII digits, no thousands separators, for comparing a figure across notations.

    Full-width digits (１２３) and a group separator every three digits are notation, not
    quantity: ``90,000`` in the paragraph and ``90 000`` in the anchored French sentence
    are the same figure, and a check that says otherwise is refusing a correct page over
    a typographic convention.  Separators only ever go when they sit *between* digits and
    the digits after them group in threes to the end of the number, so "3, 4" never
    becomes "34" and a year followed by a clause is left alone.
    """
    out = unicodedata.normalize("NFKC", text)
    return re.sub(_GROUP_SEPARATOR, "", out)


def _numbers(text: str) -> list[tuple[str, bool]]:
    """``(figure, is_scaled)`` for every figure in the paragraph.

    Chinese/Japanese/Korean numerals spelled out in characters (十二万) are **not**
    handled: they would need a parser, and no page has yet stated a figure that way in the
    English pivot.  Digits only, deliberately.
    """
    plain = _digit_fold(_FOOTNOTE_MARK.sub("", text))
    found: list[tuple[str, bool]] = []
    for m in _NUMBER_TOKEN.finditer(plain):
        found.append((m.group(0), bool(_SCALED.match(plain[m.end() :]))))
    return found


# --- proper names -----------------------------------------------------------------------

#: Two or more capitalised words, or a run-on acronym.  ``of``/``the``/``and``/``de``/``van``
#: are allowed inside a name ("The Museum of the Steppe", "Rotten Tomatoes").
_MULTIWORD_NAME = re.compile(
    r"\b[A-Z][\w'’-]+(?:\s+(?:of|the|and|de|van|für|del|di)?\s*[A-Z][\w'’-]+)+"
)
#: ``IMAX``, ``NASA``, ``CGTN`` — an acronym survives translation into a non-Latin script
#: intact, which is what makes it the only name form worth checking against CJK anchors.
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{2,6}\b")
#: Titles inside CJK book marks, which the English pivot sometimes keeps verbatim.
_BOOK_TITLE = re.compile(r"《([^》]{1,60})》")

#: Openers, connectives, demonyms and months that a sentence-initial or adjectival capital
#: turns into a false name.  A candidate is trimmed word by word from the left while its
#: first word is one of these, so "In the German reports" and "March the Federal Foreign
#: Office" reduce to the thing actually being named — or to a single word, which
#: ``_name_candidates`` then drops.  Every entry here was added because it produced a false
#: warning on a real page, not by imagination.
_NAME_STOPWORDS = {
    "The", "A", "An", "This", "That", "These", "Those", "It", "Its", "In", "On", "At",
    "By", "For", "From", "With", "Both", "Neither", "Either", "But", "And", "Or", "So",
    "What", "Where", "When", "Why", "How", "Who", "Which", "There", "Here", "One", "Two",
    "Three", "Most", "Some", "All", "No", "Not", "Only", "Every", "Each", "Their", "They",
    "His", "Her", "He", "She", "We", "Our", "Us", "You", "Your", "If", "As", "Than",
    "Then", "Because", "While", "After", "Before", "Between", "Against", "About",
    "Several", "Where", "Whether", "Since", "During", "Under", "Over", "Through",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
    "East", "West", "North", "South", "Northern", "Southern", "Eastern", "Western",
    "Chinese", "American", "English", "German", "French", "Turkish", "Japanese",
    "Korean", "Mongolian", "Indian", "Pakistani", "Nigerian", "Indonesian", "Russian",
    "European", "African", "Asian", "Kenyan", "Ethiopian", "Somali", "Arab",
    "US", "UK", "EU", "UN", "AI", "TV",
}

#: A coordination is two names, not one.  "Uzbekistan and Namibia" appears in no sentence
#: as a phrase even when both countries are anchored, so the joined form is checked as its
#: parts (each of which then meets the one-capitalised-word rule and is usually dropped).
_COORDINATION = re.compile(r"\s+(?:and|und|et|y|e)\s+")


#: A possessive splits one capitalised run into two names.  "Christopher Nolan's The
#: Odyssey" is *two* things a reader could click — the director and the film — and checking
#: the joined string finds neither, because no sentence anywhere contains both in that
#: order.  Measured on a nine-locale ship: this alone accounted for two of the four
#: name warnings on the pre-panel page, both false.
_POSSESSIVE = re.compile(r"['’]s\s+")


def _name_candidates(text: str) -> list[str]:
    """Specific things a reader could click on, in the order they appear."""
    found: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        name = name.strip(" ’'-")
        if not name or name in seen:
            return
        if _POSSESSIVE.search(name):
            for part in _POSSESSIVE.split(name):
                add(part)
            return
        if _COORDINATION.search(name):
            for part in _COORDINATION.split(name):
                add(part)
            return
        # A trailing possessive is punctuation on the name, not part of it.
        name = re.sub(r"['’]s$", "", name).strip()
        words = name.split()
        if not words or all(w in _NAME_STOPWORDS for w in words):
            return
        if len(words) == 1 and not _ACRONYM.fullmatch(name):
            # One capitalised word is a name only by context this module cannot read
            # ("Odyssey" the poem, the film, or the ship).  Acronyms are the exception:
            # they are unambiguous and they survive into every script.
            return
        if len(words) > 1 and (words[0] in _NAME_STOPWORDS or words[0][:1].islower()):
            # "But Homer" does not start at "But"; "In the German reports" does not start
            # at "In".  Trim one word and re-enter, so a run of openers peels off.
            trimmed = " ".join(words[1:])
            if trimmed and trimmed not in seen:
                add(trimmed)
            return
        seen.add(name)
        found.append(name)

    for m in _BOOK_TITLE.finditer(text):
        add(m.group(1))
    for m in _MULTIWORD_NAME.finditer(text):
        add(m.group(0))
    for m in _ACRONYM.finditer(text):
        if m.group(0) not in _NAME_STOPWORDS:
            add(m.group(0))
    return found


def _is_acronym(name: str) -> bool:
    return bool(_ACRONYM.fullmatch(name))


# --- the check --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Passage:
    """One reader-facing paragraph and the anchors a reader can click from it."""

    where: str
    claim: PageClaim
    anchors: tuple[str, ...]
    #: The whole angle's anchors, used only for an outlet that belongs to the *other*
    #: side: "unlike the New York Times, the Chinese reports…" names an outlet this side
    #: structurally cannot anchor, since the other group's articles are the other side's.
    #: An outlet of this side's own group gets no such widening — the reader clicks under
    #: *this* paragraph, and an anchor filed on the other side is not reachable from here.
    wider: tuple[str, ...]
    #: ``None`` for the intro, the hook and anything written for both sides at once.
    group_id: Optional[str] = None


def _passages(page: ReaderPage) -> Iterator[_Passage]:
    for i, claim in enumerate(page.intro, start=1):
        anchors = tuple(claim.evidence)
        yield _Passage(f"intro claim {i}", claim, anchors, anchors)
    if page.hook is not None:
        anchors = tuple(page.hook.evidence)
        yield _Passage("hook", page.hook, anchors, anchors)
    for angle in page.angles:
        wide: list[str] = []
        for side in angle.sides:
            wide.extend(side.answer.evidence)
            wide.extend(q.sentence_id for q in side.quotes)
        for side in angle.sides:
            own = [
                *side.answer.evidence,
                *(q.sentence_id for q in side.quotes),
            ]
            yield _Passage(
                f"angle {angle.rank} ({side.group_id})",
                side.answer,
                tuple(own),
                tuple(wide),
                side.group_id,
            )
        for claim in angle.detail:
            yield _Passage(
                f"angle {angle.rank} detail",
                claim,
                tuple([*claim.evidence, *wide]),
                tuple([*claim.evidence, *wide]),
            )
        if angle.commentary_joint is not None:
            joint = tuple([*angle.commentary_joint.evidence, *wide])
            yield _Passage(
                f"angle {angle.rank} joint", angle.commentary_joint, joint, joint
            )


def _anchor_text(anchors: Iterable[str], by_article: dict[str, Article]) -> str:
    parts = []
    for sid in anchors:
        try:
            article = by_article.get(SentenceId.parse(sid).article_id)
        except Exception:
            continue
        if article is None or not article.has_sentence(sid):
            continue
        parts.append(article.sentence_text(sid))
    return "\n".join(parts)


def _anchor_langs(anchors: Iterable[str], by_article: dict[str, Article]) -> set[str]:
    langs = set()
    for sid in anchors:
        try:
            article = by_article.get(SentenceId.parse(sid).article_id)
        except Exception:
            continue
        if article is not None:
            langs.add(article.lang.lower())
    return langs


def _anchor_sources(anchors: Iterable[str], by_article: dict[str, Article]) -> set[str]:
    sources = set()
    for sid in anchors:
        try:
            article = by_article.get(SentenceId.parse(sid).article_id)
        except Exception:
            continue
        if article is not None:
            sources.add(article.source_id)
    return sources


def _groups_by_source(by_article: dict[str, Article]) -> dict[str, set[str]]:
    """Which side(s) of the comparison each outlet's articles sit on.

    An article's group is the prefix of its id (``CN_…`` → ``cn``), which is how the
    corpus assigns a publication to a side.  Naming the *other* side's outlet is normal
    writing; naming your own side's outlet without anchoring it is the defect.
    """
    groups: dict[str, set[str]] = {}
    for article in by_article.values():
        groups.setdefault(article.source_id, set()).add(
            article.article_id.split("_")[0].lower()
        )
    return groups


#: Scripts in which an English proper name can be expected to survive verbatim.  Anywhere
#: else a name is transliterated (Mycenaeans → 迈锡尼, Nolan → 诺兰) and a string match
#: would fire on every name in every paragraph, which is worse than not checking.
_LATIN_SCRIPT_LANGS = {
    "en", "fr", "es", "de", "it", "pt", "nl", "id", "ms", "tr", "vi", "pl", "sv", "da",
    "no", "fi", "cs", "hu", "ro", "hr", "sl", "sk", "et", "lv", "lt", "sw", "tl", "af",
}


def check_named_things(
    out,
    page: ReaderPage,
    articles: Iterable[Article],
    *,
    registry: Optional[SourceRegistry],
    allowed_numbers: Optional[dict[str, set[str]]] = None,
    strict_names: bool = False,
) -> None:
    """Warn where a paragraph names a specific its own side never anchors.

    ``allowed_numbers`` maps ``finding_id`` → the integers a ``corpus_aggregate`` sentence
    may legitimately restate from the analysis run (cluster totals and category counts).
    Those numbers are *computed*, not quoted, so they need no anchor and are exempt; every
    other figure is a thing somebody reported and belongs in an anchored sentence.
    """
    by_article = {a.article_id: a for a in articles}
    lexicon = OutletLexicon.build(registry, by_article.values())
    source_groups = _groups_by_source(by_article)
    counts = {"outlets": 0, "numbers": 0, "names": 0}
    checked_names = 0
    skipped_unanchored = 0

    for passage in _passages(page):
        text = passage.claim.text.get("en") or ""
        anchored = _anchor_text(passage.anchors, by_article)
        if not text or not anchored:
            # A paragraph with no resolvable anchor at all fails *every* comparison here,
            # so listing each of its named things would restate one fact many times and
            # bury the real hits.  It is also a louder defect than this module's, and one
            # the writer meets elsewhere; counted, not enumerated.
            skipped_unanchored += 1 if text else 0
            continue
        own_sources = _anchor_sources(passage.anchors, by_article)
        wide_sources = _anchor_sources(passage.wider, by_article)

        # -- outlets: the reliable half.  A masthead resolves to a source_id through the
        # registry and an anchor resolves to a source_id through the corpus, so this
        # comparison never depends on the language either one is written in.  This is the
        # only one of the three that works across scripts, and the one to trust.
        for form, source_ids in lexicon.mentions(text):
            if source_ids & own_sources:
                continue
            # Only an outlet of another group may borrow the angle's other side: this
            # side has no article of that outlet to anchor in the first place.
            foreign = passage.group_id is not None and not any(
                passage.group_id in source_groups.get(sid, set()) for sid in source_ids
            )
            if foreign and source_ids & wide_sources:
                continue
            named = " / ".join(sorted(source_ids))
            out.warnings.append(
                f"{passage.where}: names {form!r} but this side's anchors carry no "
                f"sentence from {named} — anchor the outlet you name, or drop the name "
                "(page_checks_anchors)"
            )
            counts["outlets"] += 1

        anchored_folded = _digit_fold(anchored)
        langs = _anchor_langs(passage.anchors, by_article)
        exempt: set[str] = set()
        if allowed_numbers and passage.claim.computed_from:
            exempt = allowed_numbers.get(passage.claim.computed_from.split(":")[0], set())
        cjk_anchor = bool(langs & _CJK_SCALE_LANGS)

        # Figures are already governed, hard, everywhere this module could reach — and by
        # *errors*, which a warning must not argue with.  ``check_page`` refuses a
        # ``source_claim`` digit that appears in none of its anchors, refuses any digit at
        # all in a ``corpus_reading``, and refuses a ``corpus_aggregate`` integer that does
        # not recompute from its finding.  Measured over all 272 tracked ``page.json``:
        # every figure this half flagged before the narrowing was already a hard error on
        # the same sentence.  The one gap left is real, though: the aggregate rule skips
        # any token containing a decimal point outright, so "1.2 billion" or "12.1%" can
        # sit in an explanation paragraph with nothing behind it.  That gap is what this
        # covers, with ``_digit_fold`` so notation never decides the answer.
        if passage.claim.claim_type == ClaimType.CORPUS_AGGREGATE:
            for figure, scaled in _numbers(text):
                if "." not in figure:
                    continue
                if figure in exempt or figure.replace(",", "") in exempt:
                    continue
                if scaled and cjk_anchor:
                    # 12亿 vs "1.2 billion": same figure, different scale, no string match.
                    continue
                if figure in anchored_folded:
                    continue
                out.warnings.append(
                    f"{passage.where}: states the figure {figure!r}, which appears in "
                    "none of this side's anchored sentences and recomputes from no "
                    "finding (page_checks_anchors)"
                )
                counts["numbers"] += 1

        # -- proper names: the half that only works within one script.  An English name
        # reaches a non-Latin anchor transliterated (Mycenaeans → 迈锡尼) or translated
        # (IMF → Олон Улсын Валютын Сан), so a string match there fires on everything.
        # Measured: before this gate, every proper-name warning on a CJK/Cyrillic side of
        # a real page was false, and every true one was on a Latin-script side.
        if not (langs and langs <= _LATIN_SCRIPT_LANGS):
            continue
        anchored_ci = _fold(anchored).casefold()
        named_forms = {form for form, _ in lexicon.mentions(text)}
        for name in _name_candidates(text):
            if any(name in form or form in name for form in named_forms):
                continue  # already judged as an outlet, one warning per thing
            if not strict_names and not _is_acronym(name):
                continue
            checked_names += 1
            # Case-insensitive: a German report writes the association "Dehoga" and the
            # page writes "DEHOGA"; that is the same thing anchored, not a defect.
            if _fold(name).casefold() in anchored_ci:
                continue
            out.warnings.append(
                f"{passage.where}: names {name!r}, which appears in none of this side's "
                "anchored sentences (page_checks_anchors)"
            )
            counts["names"] += 1

    out.stats["named-thing warnings"] = (
        f"{counts['outlets']} outlet, {counts['numbers']} figure, {counts['names']} name; "
        f"{checked_names} name(s) checked"
        + ("" if strict_names else " (acronyms only; --strict-names widens this)")
        + (f", {skipped_unanchored} paragraph(s) skipped for having no anchors"
           if skipped_unanchored else "")
    )
