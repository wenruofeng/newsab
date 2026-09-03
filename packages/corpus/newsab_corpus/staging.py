"""The hand-filled staging format, and its conversion into `Article` records.

Phase 0 builds its corpus manually or semi-automatically (blueprint ⑥) — there is no
crawler yet, and D18 says the angle engine is derisked first.  So the entry point is a
small YAML file per article that a person or an agent can fill from a browser tab, and a
deterministic step that turns it into the real `Article` record with permanent sentence
IDs.

When S2 is built it replaces the *front* of this pipeline — fetching and cleaning —
and calls the same :func:`build_articles` for segmentation and IDs.  The staging format
stays useful forever as the manual-entry path for a source that cannot be scraped.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, NamedTuple, Optional, Sequence

from newsab_schema.io import load_yaml_text
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from newsab_schema.common import normalize_lang
from newsab_schema.enums import AccessLevel, OriginType, SourceCategory
from newsab_schema.ids import canonical_url, make_article_id, make_cluster_id
from newsab_schema.models.corpus import (
    Article,
    LocalEdits,
    Origin,
    Paragraph,
    Sentence,
)
from newsab_schema.common import Provenance

from .segment import PARAGRAPH_BREAKS, SPLITTER_VERSION, segment, split_paragraphs

#: Topic-relevance labels.  See :class:`StagingArticle.topic_relevance`.
TOPIC_RELEVANCE = ("core", "peripheral")


# --------------------------------------------------------------------------------------
# Navigation/copyright residue stripping (rationale: G-2a)
#
# The Phase 0 id-side corpus carried ~6.2% non-body sentences (site navigation, wire
# copyright footers, player placeholders, standalone bylines) that occupied sentence IDs.
# These rules remove them from a staged body *before* segmentation.
#
# ENABLED since split-0.2.0: :func:`build_paragraphs` applies them to every
# staged body, and the ``SPLITTER_VERSION`` bump that shipped with the enablement is what
# marks the resulting sentence sets as a new segmentation generation (G-2a: stripping
# changes which sentences exist, so it invalidates affected anchors exactly like a
# splitter change, and shipped together with the Q×A re-annotation).  Every removal is
# returned to the caller and lands in the corpus run's ``build_report`` — stripping is
# never silent.
# --------------------------------------------------------------------------------------

#: ``strip-0.4.0`` adds tail-block rules for author biographies, comment furniture,
#: app promotions and related-story rails found in the first India/Pakistan corpus.  The
#: rules are deliberately tail-only and start from strong publisher-furniture phrases:
#: body prose merely containing words such as ``comments`` or ``Read More`` is untouched.
RESIDUE_RULES_VERSION = "strip-0.4.0"

#: (rule_name, pattern) — every match is cut *out of* its line and the rest of the line
#: is kept.  Line rules cannot express this: the residue arrives glued to the end of a
#: real body sentence, so dropping the line would drop reporting with it.
_RESIDUE_INLINE_RULES: list[tuple[str, re.Pattern[str]]] = [
    # A page-control script call that leaked into the body text of an older CMS
    # (longhoo/sina mirrors): `pageTop(gb/longhoo/news2004/njnews/city/index.html,都市);`
    # Matched by *shape*, not by function name, because the next CMS will use a different
    # name and the same shape: an ASCII lowerCamelCase identifier applied to an argument
    # list that contains a site path — a page filename with a web extension. Prose does
    # not contain that, so the rule cannot eat a sentence.
    (
        "page_control_call",
        re.compile(
            r"[A-Za-z][A-Za-z0-9_]{3,}"                 # identifier
            r"\(\s*[^()\n]*?"                           # argument list, no nesting
            r"\.(?:s?html?|jsp|asp|aspx|php|do)\b"       # …containing a page filename
            r"[^()\n]*\)\s*;?[ \t]*",                    # …to the closing paren, + its space
        ),
    ),
]

#: (rule_name, pattern) — a line matching any pattern is dropped whole.
_RESIDUE_LINE_RULES: list[tuple[str, re.Pattern[str]]] = [
    # detik/antara/kompas in-site recommendation slots: "Baca juga: <headline>"
    ("baca_juga", re.compile(r"^\s*Baca juga\s*:", re.IGNORECASE)),
    # ANTARA wire footer: "Pewarta: <name>Editor: <name> Copyright © ANTARA 2026"
    ("antara_footer", re.compile(r"^\s*Pewarta\s*:", re.IGNORECASE)),
    ("antara_footer", re.compile(r"copyright\s*©\s*antara", re.IGNORECASE)),
    # detik embedded-player placeholder: "[Gambas:Video 20detik]"
    ("gambas_placeholder", re.compile(r"^\s*(\[Gambas:[^\]]*\]\s*)+$")),
    # tempo/detik mid-article scroll prompt
    ("scroll_prompt", re.compile(r"^\s*Scroll ke bawah untuk melanjutkan membaca\s*$", re.IGNORECASE)),
    # tempo contributor credit: "<Name> berkontribusi dalam penulisan artikel ini."
    ("tempo_contributor", re.compile(r"berkontribusi dalam penulisan artikel ini", re.IGNORECASE)),
    # Chinese reprint-rights footer, inside the body container rather than the page chrome:
    # "本文系观察者网独家稿件，未经授权，不得转载。"  Boilerplate about the article, never
    # reporting; left in, it occupies a sentence ID that an annotation could anchor on.
    ("cn_reprint_footer", re.compile(r"(未经授权|未经许可|版权所有)[^\n]{0,12}(不得|禁止)转载")),
    ("cn_reprint_footer", re.compile(r"^\s*本文(系|为)[^\n]{0,20}独家稿件")),
    # A line that is nothing but the prohibition, or nothing but a source credit — both are
    # publishing metadata sitting in the body container, both recur across zh outlets.
    ("cn_reprint_footer", re.compile(r"^\s*(禁止|不得)转载[。．.]?\s*$")),
    ("cn_source_credit", re.compile(r"^\s*来源\s*[|｜:：]\s*\S{2,20}\s*$")),
    # 中新网/新华 editor credit: "【编辑:于晓艳】"
    ("cn_editor_credit", re.compile(r"^\s*【\s*(编辑|责编|责任编辑)\s*[:：][^】]{0,20}】\s*$")),
    # French in-article recommendation slots — the `baca_juga` family in French.  RFI and
    # La Croix put them *inside* the body container, so they arrive as body sentences:
    # "À lire aussi Uranium: le Français Orano engage…", "À écouter aussi Mongolie:…".
    # The verb list is closed on purpose; "à lire" inside a real sentence is not matched
    # because the rule is anchored at the start of the line (fr corpus).
    ("fr_lire_aussi", re.compile(r"^\s*[ÀA]\s+(?:lire|écouter|ecouter|voir|revoir|regarder)\s+aussi\b", re.IGNORECASE)),
    ("fr_lire_aussi", re.compile(r"^\s*(?:Lire|Voir)\s+aussi\s*[:>»]", re.IGNORECASE)),
    ("fr_lire_aussi", re.compile(r"^\s*Sur\s+le\s+même\s+sujet\s*$", re.IGNORECASE)),
    # RFI stamps the publication time as a line inside the body container.
    ("fr_publish_stamp", re.compile(r"^\s*(?:Publié|Modifié)\s+le\s*:", re.IGNORECASE)),
    # Most-read rail header; the headlines under it are removed at extraction, but the
    # header itself recurs across French outlets and is never reporting.
    ("fr_most_read", re.compile(r"^\s*Les\s+plus\s+lus\s*$", re.IGNORECASE)),
    # Le Monde's metered-wall marker, inside the body container: it is the wall talking
    # about the article, never reporting — and its presence is what makes the article
    # `access_level: partial`.
    ("fr_paywall_marker", re.compile(r"^\s*Il\s+vous\s+reste\s+[\d,.]+\s*%\s+de\s+cet\s+article", re.IGNORECASE)),
    # Mongolian portal furniture (mn corpus).  The reuse notice arrives broken
    # across several lines by <br>, so each fragment is matched on its own distinctive
    # wording rather than on the start of the notice.
    ("mn_reuse_notice", re.compile(r"Хэвлэл мэдээллийн байгууллагууд\s*\(")),
    ("mn_reuse_notice", re.compile(r"эх сурвалжийг\s*\([^)]{2,20}\)\s*дурдах")),
    ("mn_reuse_notice", re.compile(r"бүрэн ба хэсэгчлэн авч ашиглах хориотой")),
    # Related-news / other-news rail headers and the breaking-news ticker label.
    ("mn_related_rail", re.compile(r"^\s*(?:Холбоотой|Бусад|Шуурхай|Онцлох)\s+мэдээ\s*$")),
    ("mn_disclaimer_header", re.compile(r"^\s*Анхааруулга\s*$")),
    # A block that is nothing but punctuation is layout debris, never a sentence.  It
    # would otherwise occupy a sentence ID that an annotation could anchor on.
    ("punctuation_only", re.compile(r"^[\s\|·•—–\-«»\"\'“”‘’()\[\]{}/\\.,;:!?]+$")),
    # A bare relative timestamp is a related-articles rail's furniture, never reporting:
    # "10 минут", "2 цаг 52 мин", "3 өдөр, 15 цаг" (ikon.mn, polit.mn, livetv.mn).
    ("mn_relative_timestamp", re.compile(
        r"^\s*\d{1,2}\s*(?:минут|мин|цаг|өдөр|сар|жил)"
        r"(?:\s*,?\s*\d{1,2}\s*(?:минут|мин|цаг|өдөр))?\s*(?:өмнө)?\s*$")),
    # ikon.mn stamps an archived story with this banner inside the body container.
    ("mn_stale_banner", re.compile(r"^\s*ХУУЧИРСАН МЭДЭЭ\s*[:：]")),
    # French page furniture that sits inline between real paragraphs.
    ("fr_page_furniture", re.compile(r"^\s*(?:PUBLICIT[ÉE]|Publicité)\s*$")),
    ("fr_page_furniture", re.compile(r"^\s*Article réservé à nos abonnés\s*$", re.IGNORECASE)),
    ("fr_page_furniture", re.compile(r"^\s*Temps de lecture\s*[:：]?", re.IGNORECASE)),
    ("fr_page_furniture", re.compile(r"^\s*S['’]inscrire\s*$", re.IGNORECASE)),
    ("fr_page_furniture", re.compile(r"^\s*Newsletter(?:\s+abonnés)?\s*$", re.IGNORECASE)),
    ("fr_page_furniture", re.compile(r"^\s*(?:Voir l['’]original|Partager|Traduit par [\w.\- ]+)\s*$", re.IGNORECASE)),
    ("fr_page_furniture", re.compile(r"^\s*-\s*Traduit par\b", re.IGNORECASE)),
    # A standalone Mongolian byline — initial, dot, surname in caps ("Т.САЙХАН",
    # "Г.САНСАРМАА") — sits at the head or foot of the body on several portals.
    ("mn_byline", re.compile(r"^\s*[А-ЯӨҮЁ]\.\s?[А-ЯӨҮЁ]{3,20}\s*$")),
    ("mn_source_credit", re.compile(r"^\s*Эх сурвалж\s*[:：]", re.IGNORECASE)),
    ("mn_live_marker", re.compile(r"^\s*ШУУД ДАМЖУУЛАЛТ\s*[:：]?\s*$")),
    ("mn_copyright_footer", re.compile(r"БҮХ ЭРХ ХУУЛИАР ХАМГААЛАГДСАН", re.IGNORECASE)),
    ("fr_page_furniture", re.compile(r"^\s*Newsletters\s*$", re.IGNORECASE)),
    ("fr_page_furniture", re.compile(r"^\s*Déjà abonné\s*\?", re.IGNORECASE)),
    ("fr_page_furniture", re.compile(r"^\s*Pour soutenir le travail de notre rédaction", re.IGNORECASE)),
    ("fr_page_furniture", re.compile(r"^\s*(?:Sudoku|Les grilles de Sudoku)\b", re.IGNORECASE)),
    ("fr_page_furniture", re.compile(r"^\s*Meilleur portail\b", re.IGNORECASE)),
    ("mn_comment_policy", re.compile(r"^\s*Та сэтгэгдэл бичихдээ", re.IGNORECASE)),
]

#: A tail block starts at a strong furniture marker and removes every later non-empty
#: line.  Unlike the ordinary line rules, this also removes unlabelled related-story
#: headlines that cannot be recognised safely one by one.  Markers are considered only
#: near the article tail, so a news story quoting the same words in its body survives.
_RESIDUE_TAIL_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "geo_related_tail",
        re.compile(
            r"^\s*Govt snubs ['’]misleading['’] foreign media news on Imran['’]s "
            r"well-being, prison conditions\s*$",
            re.IGNORECASE,
        ),
    ),
    ("pk_comments_tail", re.compile(r"^\s*No comments yet\.\s*$", re.IGNORECASE)),
    (
        "pakistan_today_author_tail",
        re.compile(r"^\s*APP is Pakistan['’]s government-operated national news agency\b", re.IGNORECASE),
    ),
    (
        "pakistan_today_author_tail",
        re.compile(r"^\s*Our monitoring team diligently searches the vast expanse of the web\b", re.IGNORECASE),
    ),
    (
        "pakistan_today_author_tail",
        re.compile(r"^\s*The Editorial Department of Pakistan Today can be contacted at\s*:", re.IGNORECASE),
    ),
    (
        "ht_author_tail",
        re.compile(r"^\s*Follow the latest breaking news, major developments and agenda-setting stories\b", re.IGNORECASE),
    ),
    (
        "ht_author_tail",
        re.compile(r"^\s*[A-Z][\w.’'\- ]{1,80} is .{0,80}\bHindustan Times, which .{0,20} joined\b", re.IGNORECASE),
    ),
    (
        "tnie_promo_tail",
        re.compile(r"^\s*Follow The New Indian Express channel on WhatsApp\s*$", re.IGNORECASE),
    ),
]
_TAIL_RESIDUE_WINDOW = 30

#: A standalone byline: 1–4 title-case tokens, no sentence punctuation.  Only trusted at
#: the very tail of an article (tempo_id ends articles with a bare reporter name), because
#: anywhere else the same shape could be a legitimate short line.
_TAIL_BYLINE = re.compile(r"^\s*(?:[A-Z][\w'.\-]*)(?:\s+[A-Z][\w'.\-]*){0,3}\s*$")
_TAIL_BYLINE_WINDOW = 3


class StrippedBody(NamedTuple):
    body: str
    #: (rule_name, removed_line) in document order — the audit trail for the
    #: collection_log; stripping must never be silent.
    removed: list[tuple[str, str]]


def strip_residue(body: str) -> StrippedBody:
    """Remove known navigation/copyright residue lines from a staged body.

    Deterministic and versioned (``RESIDUE_RULES_VERSION``): same body, same rules, same
    output.  Returns what it removed so the caller can log it.  See the block comment
    above for why callers must couple this to a ``SPLITTER_VERSION`` bump.
    """
    lines = body.split("\n")
    kept: list[str] = []
    removed: list[tuple[str, str]] = []

    # Inline first: a line that is *nothing but* residue becomes empty here and is then
    # dropped by the ordinary blank-line handling, so the two rule kinds compose.
    for i, line in enumerate(lines):
        for name, pattern in _RESIDUE_INLINE_RULES:
            hits = pattern.findall(line)
            if not hits:
                continue
            for hit in hits:
                removed.append((name, hit.strip()))
            line = pattern.sub("", line)
        lines[i] = line.rstrip() if line.strip() else line

    for line in lines:
        rule = next(
            (name for name, pattern in _RESIDUE_LINE_RULES if pattern.search(line)),
            None,
        )
        if rule is not None and line.strip():
            removed.append((rule, line.strip()))
        else:
            kept.append(line)

    # Tail blocks: a marker plus the unlabeled cards after it are one piece of chrome.
    # Pick the earliest eligible marker so nested furniture (author bio -> comments ->
    # related cards) is removed in one deterministic cut and audited in document order.
    nonempty = [index for index, line in enumerate(kept) if line.strip()]
    eligible = set(nonempty[-_TAIL_RESIDUE_WINDOW:])
    tail_hits: list[tuple[int, str]] = []
    for index in sorted(eligible):
        rule = next(
            (name for name, pattern in _RESIDUE_TAIL_RULES if pattern.search(kept[index])),
            None,
        )
        if rule is not None:
            tail_hits.append((index, rule))
    if tail_hits:
        start, rule = tail_hits[0]
        removed.extend((rule, line.strip()) for line in kept[start:] if line.strip())
        del kept[start:]

    # Tail bylines: walk backwards over the last non-empty lines.
    tail_seen = 0
    while kept and tail_seen < _TAIL_BYLINE_WINDOW:
        index = len(kept) - 1
        while index >= 0 and not kept[index].strip():
            index -= 1
        if index < 0:
            break
        line = kept[index]
        if not _TAIL_BYLINE.match(line):
            break
        removed.append(("tail_byline", line.strip()))
        del kept[index:]
        tail_seen += 1

    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip("\n")
    return StrippedBody(body=cleaned, removed=removed)


class StagingOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: OriginType = OriginType.ORIGINAL
    wire_source: Optional[str] = None
    headline_changed: Optional[bool] = None
    lead_changed: Optional[bool] = None

    @model_validator(mode="after")
    def _constructible(self) -> "StagingOrigin":
        """Fail at load time, where the error can name the staging file.

        The rule itself lives on :class:`Origin` and is not restated here — this only
        moves *when* the collector hears about it, from halfway through a build to the
        moment the file is read.
        """
        self.to_origin()
        return self

    def to_origin(self) -> Origin:
        local = None
        if self.headline_changed is not None or self.lead_changed is not None:
            local = LocalEdits(
                headline_changed=bool(self.headline_changed),
                lead_changed=bool(self.lead_changed),
            )
        return Origin(type=self.type, wire_source=self.wire_source, local_edits=local)


class StagingArticle(BaseModel):
    """One article as typed in by hand.

    Everything here is what a person can read off the page.  Nothing derived lives here —
    no sentence IDs, no cluster, no article ID — because a hand-maintained derived value
    is a hand-maintained inconsistency.
    """

    model_config = ConfigDict(extra="forbid")

    #: The collector's explicit membership judgement against the topic manifest's group
    #: definition.  Country and language are article/source facts, not group selectors.
    group_id: str = Field(pattern=r"^[a-z]{2,5}$")
    source_id: str
    # --- registering an outlet the registry has never seen -----------------------------
    # Meeting a new outlet is the normal result of an open frame (D19), so the build
    # registers it rather than stopping (D20).  What it will not do is invent the entry:
    # the registry has no "a human confirms this later" tier, so the
    # collector that met the outlet supplies everything the registry needs, here, in the
    # first article it stages from that outlet.  Leave the whole block out for an outlet
    # that is already registered — the registry is the definition, and a staged article
    # never overwrites it.
    #: ISO 3166-1 alpha-2 where the outlet is based (``GB``, never ``UK``).
    source_country: Optional[str] = Field(default=None, pattern=r"^[A-Z]{2}$")
    #: The outlet's **front page**, not the article URL that surfaced it.
    source_url: Optional[str] = Field(default=None, pattern=r"^https?://")
    #: Masthead in English and Chinese, plus the outlet's own language when that is
    #: neither.  Not a slug: a reader sees this on the media card.
    source_name_en: Optional[str] = Field(default=None, min_length=1)
    source_name_zh: Optional[str] = Field(default=None, min_length=1)
    source_name_native: Optional[str] = Field(default=None, min_length=1)
    #: ``serious`` (reports under its own byline and answers for the facts) or ``other``
    #: (everything else we still collect and still count in the "all sources" view).
    #: Decided at collection time rather than deferred to a gate (retiring D-22):
    #: an outlet parked in a placeholder silently distorts a published number, while
    #: "decide now, the next agent can disagree" costs at worst one wrong label.
    source_category: Optional[SourceCategory] = None
    #: General-interest newsroom or industry/sector desk, for an unregistered outlet.
    source_beat_scope: Optional[str] = None
    #: The media card, in English and Chinese: **one sentence for a reader** saying what
    #: kind of institution this is — who runs it, what it covers, what to discount.  This
    #: replaced the old ``source_category_basis``, because a sentence that tells a reader
    #: what the outlet is also tells the next agent why ``source_category`` reads the way
    #: it does, and only one of the two ever reached anybody.
    source_notes_en: Optional[str] = Field(default=None, min_length=10)
    source_notes_zh: Optional[str] = Field(default=None, min_length=4)
    url: str = Field(pattern=r"^https?://")
    title: str = Field(min_length=1)
    subtitle: Optional[str] = None
    publish_date: date
    lang: str
    access_level: AccessLevel = AccessLevel.FULL
    origin: StagingOrigin = Field(default_factory=StagingOrigin)
    #: Body text.  For a `partial` source this is the lead only, and that is recorded
    #: rather than hidden (§3.3 S2).
    body: str = Field(default="")
    #: How this body marks a paragraph boundary — see ``segment.PARAGRAPH_BREAKS``.  The
    #: collector declares it rather than the builder guessing, because guessing wrong is
    #: silent: one wrong reading puts the whole article in P01, the other shatters a
    #: wrapped paragraph into one paragraph per line, and both still produce valid
    #: sentence IDs.  Set `single_newline` when the body came from a JSON-LD
    #: `articleBody`.
    paragraph_break: str = Field(default="blank_line")
    #: Retired (analyze refactor): relevance became a binary inclusion
    #: decision made before staging, and everything staged counts in every denominator.
    #: Kept append-only because historical runs carry it; nothing reads it any more.
    topic_relevance: str = Field(default="core")
    #: Optional hand note for the collection log (why this article, retrieval quirks).
    note: Optional[str] = None

    @field_validator("lang")
    @classmethod
    def _lang(cls, v: str) -> str:
        return normalize_lang(v)

    @field_validator("source_beat_scope")
    @classmethod
    def _beat_scope(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("general", "vertical"):
            raise ValueError(f"source_beat_scope must be general or vertical, got {v!r}")
        return v

    @model_validator(mode="after")
    def _registration_is_complete(self) -> "StagingArticle":
        """All of the registration block, or none of it.

        Half a registration is the failure mode this replaced: the build used to fill the
        rest in with placeholders, and a placeholder in a published number is a wrong
        answer that nobody notices.  Refusing here costs the collector one edit to a file
        it is already writing.
        """
        block = {
            "source_country": self.source_country,
            "source_url": self.source_url,
            "source_name_en": self.source_name_en,
            "source_name_zh": self.source_name_zh,
            "source_category": self.source_category,
            "source_beat_scope": self.source_beat_scope,
            "source_notes_en": self.source_notes_en,
            "source_notes_zh": self.source_notes_zh,
        }
        given = {k for k, v in block.items() if v is not None}
        if given and given != set(block):
            missing = ", ".join(sorted(set(block) - given))
            raise ValueError(
                f"the registration block for {self.source_id!r} is incomplete: {missing}. "
                "An outlet enters the registry complete or not at all — see "
                "skills/collect/references/source-registration.md"
            )
        if given and self.lang not in ("en", "zh-CN") and not self.source_name_native:
            raise ValueError(
                f"{self.source_id!r} publishes in {self.lang!r}, so source_name_native "
                "carries its masthead in its own language"
            )
        return self

    @field_validator("topic_relevance")
    @classmethod
    def _topic_relevance(cls, v: str) -> str:
        if v not in TOPIC_RELEVANCE:
            raise ValueError(f"topic_relevance must be one of {TOPIC_RELEVANCE}, got {v!r}")
        return v

    @field_validator("paragraph_break")
    @classmethod
    def _paragraph_break(cls, v: str) -> str:
        if v not in PARAGRAPH_BREAKS:
            raise ValueError(f"paragraph_break must be one of {PARAGRAPH_BREAKS}, got {v!r}")
        return v


class StagingError(ValueError):
    pass


def load_staging(directory: str | Path) -> list[tuple[Path, StagingArticle]]:
    """Load every ``*.yaml`` in a staging directory, sorted by filename.

    The sort no longer affects identity — ``article_id`` is derived from the article's own
    URL (R-1) — but a stable read order keeps warnings and logs in a stable order too.
    """
    files = sorted(Path(directory).glob("*.yaml")) + sorted(Path(directory).glob("*.yml"))
    out: list[tuple[Path, StagingArticle]] = []
    for path in files:
        raw = load_yaml_text(path.read_text(encoding="utf-8"))
        if raw is None:
            raise StagingError(f"{path}: file is empty")
        try:
            out.append((path, StagingArticle.model_validate(raw)))
        except Exception as exc:  # pragma: no cover - message is the point
            raise StagingError(f"{path}: {exc}") from exc
    return out


#: Named and numeric character references that a body has if extraction took innerHTML
#: instead of text.  Deliberately not a general ``&\w+;`` match: prose legitimately contains
#: "AT&T;" shapes and a false positive here would cry wolf on every corpus.
_HTML_ENTITY = re.compile(r"&(?:nbsp|amp|quot|apos|lsquo|rsquo|ldquo|rdquo|ndash|mdash|hellip|#\d{2,5}|#x[0-9a-fA-F]{2,4});")


def html_entities_in(body: str) -> list[str]:
    """Undecoded character references in a staged body — an extraction bug, not content.

    §2.5 promises a reader that the quoted sentence is findable on the publisher's page.
    A sentence stored as ``Famao&rsquo;s claims`` fails that promise: the page renders an
    apostrophe.  Worse, ``&nbsp;`` survives as a whole "sentence" of its own and occupies a
    sentence ID that an annotation can anchor on.  Both were live in a real corpus and
    neither was visible to any check — the corpus validated, the anchors resolved, and the
    stored text simply was not what the page said.
    """
    return sorted(set(_HTML_ENTITY.findall(body)))


#: A body declared ``blank_line`` whose single-newline reading yields at least this many
#: times more blocks is almost certainly a JSON-LD ``articleBody`` staged under the wrong
#: convention.  Measured against all 181 staged bodies in the three live topics the
#: ratio separates the one known case (28.0) from every correctly declared body (<= 1.0)
#: with nothing in between, so the threshold is not near anything.
PARAGRAPH_BREAK_SUSPICION_RATIO = 4
#: …and only when the single-newline reading finds a real article's worth of paragraphs.
#: A genuinely one-paragraph newsflash has no newlines at all and must not be flagged.
PARAGRAPH_BREAK_SUSPICION_MIN_BLOCKS = 4


def paragraph_break_looks_wrong(body: str, paragraph_break: str) -> Optional[tuple[int, int]]:
    """``(blank_line_blocks, single_newline_blocks)`` when the declaration looks inverted.

    The collector *declares* the convention instead of letting the builder guess,
    which fixed the guessing but left the declaration itself unchecked — and a wrong
    declaration is silent: both readings produce valid sentence IDs, so the corpus looks
    fine and every "which paragraph" answer is wrong.  The two readings of the same bytes
    are cheap to compare, so the builder checks the collector rather than trusting them.

    Only the ``blank_line`` direction is detectable this way.  A body wrongly declared
    ``single_newline`` shatters into one paragraph per line, which is indistinguishable
    from a real article of short paragraphs.
    """
    if paragraph_break != "blank_line":
        return None
    blank = len(split_paragraphs(body, "blank_line"))
    single = len(split_paragraphs(body, "single_newline"))
    if single < PARAGRAPH_BREAK_SUSPICION_MIN_BLOCKS:
        return None
    if single < PARAGRAPH_BREAK_SUSPICION_RATIO * max(blank, 1):
        return None
    return blank, single


def build_paragraphs(
    staged: StagingArticle,
) -> tuple[list[Paragraph], bool, list[tuple[str, str]]]:
    """Headline block (P00) + residue stripping + segmented body.

    Returns the paragraphs, the fallback-splitter flag, and the residue lines that
    :func:`strip_residue` removed (rule, line) so the caller can put them on the record.
    """
    head = [Sentence(index=1, text=staged.title)]
    if staged.subtitle:
        head.append(Sentence(index=2, text=staged.subtitle))
    paragraphs = [Paragraph(index=0, sentences=head)]

    stripped = strip_residue(staged.body)
    body = _body_with_standfirst(stripped.body, staged.subtitle, staged.paragraph_break)
    result = segment(body, staged.lang, staged.paragraph_break)
    for pi, sentences in enumerate(result.paragraphs, start=1):
        paragraphs.append(
            Paragraph(
                index=pi,
                sentences=[Sentence(index=si, text=t) for si, t in enumerate(sentences, start=1)],
            )
        )
    return paragraphs, result.used_fallback, stripped.removed


def _body_with_standfirst(body: str, subtitle: Optional[str], paragraph_break: str) -> str:
    """Put a staged standfirst at the head of the body exactly once.

    ``subtitle`` remains in P00 as headline metadata, but it is also article text under
    the collection contract.  The declared paragraph convention decides the separator;
    using a blank line unconditionally would collapse the standfirst into P01 for a
    ``single_newline`` JSON-LD body.
    """
    if not subtitle or body.startswith(subtitle):
        return body
    separator = "\n" if paragraph_break == "single_newline" else "\n\n"
    return f"{subtitle}{separator}{body}" if body else subtitle


def build_articles(
    staged: Sequence[tuple[Path, StagingArticle]],
    *,
    topic_id: str,
    run_id: str,
    cluster_ids: Optional[dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> tuple[list[Article], list[str], dict[str, list[tuple[str, str]]]]:
    """Turn staged entries into `Article` records with permanent, content-addressed IDs.

    ``article_id`` is ``{GROUP}_{sha256(canonical_url)[:8]}`` (R-1), so the same article
    gets the same ID whenever it is ingested and whatever else is in the corpus.  That is
    what makes a corpus extensible: removing or adding a piece no longer renumbers its
    neighbours, and therefore no longer moves anyone else's sentence anchors.

    ``cluster_ids`` maps article_id -> reporting_cluster_id; when omitted every article
    becomes its own cluster, which is the correct *pre-clustering* state and is what
    :func:`newsab_corpus.cluster.assign_clusters` then refines.

    Returns the articles, a list of warnings (things a human should look at but which
    do not invalidate the corpus), and the residue lines stripped per article — the
    audit trail the corpus run's ``build_report`` carries (stripping is never silent).
    """
    warnings: list[str] = []
    articles: list[Article] = []
    residue_removed: dict[str, list[tuple[str, str]]] = {}
    seen: dict[str, Path] = {}
    timestamp = now or datetime.now(timezone.utc)

    for path, entry in staged:
        prefix = entry.group_id.upper()
        article_id = make_article_id(prefix, entry.url)
        if article_id in seen:
            warnings.append(
                f"{article_id}: {path.name} and {seen[article_id].name} canonicalise to the "
                f"same URL ({canonical_url(entry.url)}); keeping the first and skipping the "
                "second — content addressing deduplicates re-collection for free (R-1)"
            )
            continue
        seen[article_id] = path

        paragraphs, used_fallback, removed = build_paragraphs(entry)
        if removed:
            residue_removed[article_id] = removed
            rules = sorted({rule for rule, _ in removed})
            warnings.append(
                f"{article_id}: {len(removed)} residue line(s) stripped before "
                f"segmentation ({RESIDUE_RULES_VERSION}: {', '.join(rules)})"
            )
        if used_fallback:
            warnings.append(
                f"{article_id}: no tuned splitter for {entry.lang!r}; the conservative "
                "fallback was used and sentence boundaries need a human spot-check"
            )
        entities = html_entities_in(entry.body)
        if entities:
            warnings.append(
                f"{article_id}: the staged body still contains undecoded HTML character "
                f"references ({', '.join(entities)}); extraction took markup where it should "
                "have taken text. The stored sentence is then not what the page shows, so a "
                "reader cannot find the quote (§2.5), and a bare &nbsp; can occupy a "
                "sentence ID of its own. Re-stage with the entities decoded"
            )
        stripped_body = strip_residue(entry.body).body
        effective_body = _body_with_standfirst(
            stripped_body, entry.subtitle, entry.paragraph_break
        )
        suspicion = paragraph_break_looks_wrong(effective_body, entry.paragraph_break)
        if suspicion is not None:
            blank, single = suspicion
            warnings.append(
                f"{article_id}: staged as paragraph_break=blank_line, but the body reads as "
                f"{blank} paragraph(s) that way and {single} as single_newline. That is what "
                "a JSON-LD articleBody looks like: the whole article lands in P01, the "
                "sentence anchors stay valid and every paragraph answer becomes wrong "
                "Check the source and restage, or confirm it really is one block"
            )
        if len(paragraphs) == 1:
            warnings.append(
                f"{article_id}: no body text — only the headline block exists. "
                f"access_level={entry.access_level.value}"
            )

        articles.append(
            Article(
                article_id=article_id,
                topic_id=topic_id,
                source_id=entry.source_id,
                url=entry.url,
                title=entry.title,
                publish_date=entry.publish_date,
                lang=entry.lang,
                structured_text=paragraphs,
                fetch_timestamp=timestamp,
                access_level=entry.access_level,
                origin=entry.origin.to_origin(),
                # Provisional: every article starts as its own cluster.  The authoritative
                # assignment belongs to the corpus run, because clustering is a property of
                # the whole set — adding one wire copy can merge two clusters (R-2).
                reporting_cluster_id=(cluster_ids or {}).get(
                    article_id, make_cluster_id(prefix, article_id)
                ),
                splitter_version=SPLITTER_VERSION,
                provenance=Provenance(
                    skill_version="S2stage-0.1.1",
                    model_id=None,
                    run_id=run_id,
                    timestamp=timestamp,
                ),
            )
        )

    return articles, warnings, residue_removed


def rewrite_clusters(articles: Iterable[Article], cluster_ids: dict[str, str]) -> list[Article]:
    """Return copies carrying their final cluster assignment.

    Records are immutable (§3.2), so this constructs new ones rather than mutating.  It is
    only ever called *before* the corpus is written, so no artifact is ever edited in place.
    """
    out: list[Article] = []
    for article in articles:
        target = cluster_ids.get(article.article_id, article.reporting_cluster_id)
        out.append(
            Article.model_validate({**article.model_dump(mode="json"), "reporting_cluster_id": target})
        )
    return out
