"""Identifier grammar and helpers (blueprint §4.1).

Every ID in this project is *parseable*: a reviewer holding only the artifacts must be
able to tell which article a sentence belongs to, which topic an observation belongs to,
and whether a reference points at something that can exist.  That is why these are
regexes with parsers rather than free-form strings.

Widths (``OBS`` 6 digits, ``ANG``/``CLM`` 4) follow the blueprint's worked examples.
They are constants here so a future topic that outgrows them changes one line.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit, urlunsplit

# --- grammars ------------------------------------------------------------------------

#: Group prefix used in ``article_id``: an upper-case, topic-local short code (``CN``,
#: ``US``, ``AFR``).  Groups are semantic sides defined by the topic manifest; a prefix
#: need not be a country code.
GROUP_RE = re.compile(r"^[A-Z]{2,5}$")

#: ``group_id`` as used inside analysis artifacts — the lower-case form of a group prefix.
GROUP_ID_RE = re.compile(r"^[a-z]{2,5}$")

#: ``topic_id``: lower-case slug, hyphen separated (``aabb-river-light-2026``).
TOPIC_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: Width of the content-addressed article key, in hex characters.  8 hex = 32 bits; with a
#: few hundred articles per topic a collision is ~1e-5, and :func:`make_article_id` refuses
#: to mint a colliding key rather than trusting the odds.
ARTICLE_KEY_WIDTH = 8

#: The current article key: the first :data:`ARTICLE_KEY_WIDTH` hex characters of
#: ``sha256(canonical_url)``.  Older corpora used a 3–6 digit build-order serial;
#: that form is still *parsed* so historical artifacts stay readable, but never minted —
#: a serial shifts every downstream sentence anchor when an article is removed from the
#: middle of the corpus, which is exactly what content addressing removes.
_ARTICLE_KEY = rf"[0-9a-f]{{{ARTICLE_KEY_WIDTH}}}|\d{{3,6}}"

#: ``article_id``: ``{GROUP}_{key}`` (``CN_a1f39c02``; legacy ``CN_028``).
ARTICLE_ID_RE = re.compile(rf"^(?P<group>[A-Z]{{2,5}})_(?P<key>{_ARTICLE_KEY})$")

#: ``sentence_id``: ``{article_id}:P{paragraph}:S{sentence}`` (``CN_a1f39c02:P07:S02``).
SENTENCE_ID_RE = re.compile(
    rf"^(?P<article_id>[A-Z]{{2,5}}_(?:{_ARTICLE_KEY})):"
    r"P(?P<para>\d{2,3}):S(?P<sent>\d{2,3})$"
)

#: ``concept_id``: snake_case English (§4.1).
CONCEPT_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

#: ``reporting_cluster_id`` (S2 output).  Not pinned by the blueprint; fixed here so the
#: A1 denominator (D7) is checkable: ``RC-{GROUP}-{key}``.  The key is the article key of
#: the cluster's representative member (its lexicographically smallest ``article_id``), so
#: a cluster is named by content rather than by position in the build order.
CLUSTER_ID_RE = re.compile(rf"^RC-(?P<group>[A-Z]{{2,5}})-(?P<key>{_ARTICLE_KEY})$")

#: ``semantic_cluster_id`` (S6 output), per §4.4's ``SC-03``.
SEMANTIC_CLUSTER_ID_RE = re.compile(r"^SC-\d{2,3}$")

#: ``run_id`` / ``a1_run_id``. Human/model stages may use minute resolution; deterministic
#: writers may use UTC microsecond resolution so two same-input reruns never target the
#: same immutable directory.
RUN_ID_RE = re.compile(r"^[a-z][a-z0-9]{0,15}-(?:\d{12}|\d{20})-[0-9a-f]{8}$")

#: Prefixed serial IDs: prefix, zero-pad width.  ``QST`` (question), ``ANS`` (one
#: cluster's answer to one question) and ``FND`` (one computed finding) belong to the
#: Q×A model (value_chain.md, V-1).
PREFIXED: dict[str, int] = {"OBS": 6, "ANG": 4, "CLM": 4, "QST": 3, "ANS": 6, "FND": 3}

_PREFIXED_RE = {
    prefix: re.compile(
        rf"^{prefix}-(?P<topic>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<serial>\d{{{width}}})$"
    )
    for prefix, width in PREFIXED.items()
}

#: ``FND`` ids minted since the analyze refactor decouple identity from rank:
#: ``FND-{topic-slug}-{question serial}-{kind}`` (e.g. ``FND-aabb-river-light-003-divergence``),
#: so one question can carry one finding per kind and a re-run never renames a finding.
#: The kind suffix is snake_case (underscores, never hyphens), which keeps the grammar
#: unambiguous against hyphenated topic slugs.  The suffix-less legacy form (rank as the
#: serial) still parses — historical runs reference it.
_PREFIXED_RE["FND"] = re.compile(
    r"^FND-(?P<topic>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<serial>\d{3})"
    r"(?:-(?P<suffix>[a-z]+(?:_[a-z]+)*))?$"
)

#: Title/subtitle live in the synthetic paragraph 0 (§4.1).
TITLE_SENTENCE_SUFFIX = "P00:S01"
SUBTITLE_SENTENCE_SUFFIX = "P00:S02"


class IdError(ValueError):
    """Raised when an identifier does not match its grammar."""


# --- sentence IDs ---------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class SentenceId:
    """A parsed ``{article_id}:P{n}:S{n}``.

    Ordering is (article, paragraph, sentence), so a sorted list of ``SentenceId`` is in
    reading order — which is what evidence lists want.
    """

    article_id: str
    paragraph: int
    sentence: int

    @classmethod
    def parse(cls, raw: str) -> "SentenceId":
        m = SENTENCE_ID_RE.match(str(raw).strip())
        if not m:
            raise IdError(
                f"not a sentence_id: {raw!r} (expected {{ARTICLE_ID}}:P{{nn}}:S{{nn}})"
            )
        return cls(m.group("article_id"), int(m.group("para")), int(m.group("sent")))

    def __str__(self) -> str:
        return f"{self.article_id}:P{self.paragraph:02d}:S{self.sentence:02d}"

    @property
    def is_title(self) -> bool:
        """Paragraph 0 is the headline block, which S2 synthesises rather than scrapes."""
        return self.paragraph == 0

    @property
    def group(self) -> str:
        return parse_article_id(self.article_id)[0]


def make_sentence_id(article_id: str, paragraph: int, sentence: int) -> str:
    """Mint a canonical sentence ID (zero-padded to two digits)."""
    validate_article_id(article_id)
    if paragraph < 0 or sentence < 1:
        raise IdError(
            f"paragraph must be >= 0 and sentence >= 1, got P{paragraph}:S{sentence}"
        )
    return str(SentenceId(article_id, paragraph, sentence))


def is_sentence_id(raw: str) -> bool:
    return bool(SENTENCE_ID_RE.match(str(raw).strip()))


def article_of(sentence_id: str) -> str:
    """The article a sentence ID belongs to — used by the §4.2.2 "same article" invariant."""
    return SentenceId.parse(sentence_id).article_id


# --- article / group / topic ----------------------------------------------------------


#: Query parameters that never change which article a URL names.  Dropped before hashing so
#: the same piece shared through three campaigns is one article rather than three.
_TRACKING_PARAMS = ("utm_", "spm", "from_timeline", "isappinstalled", "wxshare", "share_")


def canonical_url(url: str) -> str:
    """The URL form that :func:`article_key` hashes.

    Deliberately conservative: it removes only differences that provably cannot change
    which article is addressed (case of scheme/host, default ports, the fragment, tracking
    parameters, a trailing slash, duplicate slashes).  It does **not** try to unify mobile
    and desktop hosts or resolve redirects — those are collection-time judgements that
    belong in S2 with the evidence in front of it, not in a hash function.
    """
    raw = str(url).strip()
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        raise IdError(f"cannot canonicalise a URL without scheme and host: {url!r}")

    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    port = parts.port
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"

    path = re.sub(r"/{2,}", "/", parts.path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    query = "&".join(
        f"{k}={v}"
        for k, v in sorted(parse_qsl(parts.query, keep_blank_values=True))
        if not any(k.lower().startswith(prefix) for prefix in _TRACKING_PARAMS)
    )
    return urlunsplit((scheme, host, path, query, ""))


def article_key(url: str) -> str:
    """The content-addressed half of an ``article_id``: 8 hex of ``sha256(canonical_url)``."""
    digest = hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()
    return digest[:ARTICLE_KEY_WIDTH]


def parse_article_id(raw: str) -> tuple[str, str]:
    """``("CN", "a1f39c02")``.  The key is returned as a string: it is an opaque label,
    and a legacy ``CN_028`` must keep its zero padding to stay equal to itself."""
    m = ARTICLE_ID_RE.match(str(raw).strip())
    if not m:
        raise IdError(f"not an article_id: {raw!r} (expected {{GROUP}}_{{key}})")
    return m.group("group"), m.group("key")


def article_key_of(article_id: str) -> str:
    return parse_article_id(article_id)[1]


def is_content_addressed(article_id: str) -> bool:
    """False for a legacy build-order serial, which must never be minted again.

    Legacy serials are 3–6 digits and article keys are exactly 8 hex characters, so the
    width alone separates them.
    """
    return len(parse_article_id(article_id)[1]) == ARTICLE_KEY_WIDTH


def validate_article_id(raw: str) -> str:
    parse_article_id(raw)
    return str(raw).strip()


def make_article_id(group: str, url: str) -> str:
    """Mint ``{GROUP}_{sha256(canonical_url)[:8]}``.

    Content addressing, not a build-order serial: the same article gets the same ID
    whenever it is ingested and whatever else is in the corpus, so removing one article
    never shifts another article's sentence anchors, and re-collecting the same URL
    deduplicates for free.
    """
    if not GROUP_RE.match(group):
        raise IdError(f"group prefix must be 2-5 upper-case letters, got {group!r}")
    return f"{group}_{article_key(url)}"


def make_cluster_id(group: str, representative_article_id: str) -> str:
    """Name a reporting cluster after its representative member (D7's denominator unit)."""
    if not GROUP_RE.match(group):
        raise IdError(f"group prefix must be 2-5 upper-case letters, got {group!r}")
    return f"RC-{group}-{article_key_of(representative_article_id)}"


def group_of(article_id: str) -> str:
    """Group *prefix* (upper case) of an article."""
    return parse_article_id(article_id)[0]


def group_id_of(article_id: str) -> str:
    """Group *id* (lower case) as used in analysis artifacts and angle ``groups[]``."""
    return parse_article_id(article_id)[0].lower()


def validate_topic_id(raw: str) -> str:
    if not TOPIC_ID_RE.match(str(raw).strip()):
        raise IdError(f"not a topic_id: {raw!r} (expected lower-case hyphen slug)")
    return str(raw).strip()


# --- prefixed serial IDs (OBS / ANG / CLM) --------------------------------------------


@dataclass(frozen=True, order=True)
class PrefixedId:
    prefix: str
    topic_slug: str
    serial: int
    #: ``FND`` only: the kind suffix of a post-refactor finding id (``divergence``,
    #: ``attention_gap``, …); ``None`` for every other prefix and for legacy FND ids.
    suffix: str | None = None

    def __str__(self) -> str:
        base = f"{self.prefix}-{self.topic_slug}-{self.serial:0{PREFIXED[self.prefix]}d}"
        return f"{base}-{self.suffix}" if self.suffix else base


def parse_prefixed_id(raw: str, prefix: str) -> PrefixedId:
    """Parse ``OBS-``/``ANG-``/``CLM-`` IDs.

    The blueprint's rule is ``{PREFIX}-{topic_id}-{serial}`` while its worked examples
    abbreviate the topic (``OBS-aabb-river-light-000812`` for topic ``aabb-river-light-2026``).  We
    therefore parse the middle as an opaque slug and check it against the record's own
    ``topic_id`` separately, via :func:`topic_slug_matches` — so an abbreviated slug is a
    *consistency* question, not a parse failure.
    """
    if prefix not in _PREFIXED_RE:
        raise IdError(f"unknown ID prefix {prefix!r}; known: {sorted(PREFIXED)}")
    m = _PREFIXED_RE[prefix].match(str(raw).strip())
    if not m:
        width = PREFIXED[prefix]
        raise IdError(
            f"not a {prefix} id: {raw!r} (expected {prefix}-{{topic-slug}}-{{{width} digits}})"
        )
    suffix = m.groupdict().get("suffix")
    return PrefixedId(prefix, m.group("topic"), int(m.group("serial")), suffix)


def make_prefixed_id(prefix: str, topic_slug: str, serial: int) -> str:
    if prefix not in PREFIXED:
        raise IdError(f"unknown ID prefix {prefix!r}; known: {sorted(PREFIXED)}")
    validate_topic_id(topic_slug)
    return str(PrefixedId(prefix, topic_slug, serial))


def topic_slug_matches(id_topic_slug: str, topic_id: str) -> bool:
    """True when an ID's embedded slug is the topic ID or a leading abbreviation of it.

    ``aabb-river-light`` matches topic ``aabb-river-light-2026``; ``ccdd-river-dark`` does not.
    """
    if id_topic_slug == topic_id:
        return True
    return topic_id.startswith(id_topic_slug + "-")


def make_observation_id(topic_slug: str, serial: int) -> str:
    return make_prefixed_id("OBS", topic_slug, serial)


def make_angle_id(topic_slug: str, serial: int) -> str:
    return make_prefixed_id("ANG", topic_slug, serial)


def make_claim_id(topic_slug: str, serial: int) -> str:
    return make_prefixed_id("CLM", topic_slug, serial)


def make_question_id(topic_slug: str, serial: int) -> str:
    return make_prefixed_id("QST", topic_slug, serial)


def make_answer_id(topic_slug: str, serial: int) -> str:
    return make_prefixed_id("ANS", topic_slug, serial)


# --- misc ------------------------------------------------------------------------------


def validate_concept_id(raw: str) -> str:
    if not CONCEPT_ID_RE.match(str(raw).strip()):
        raise IdError(f"not a concept_id: {raw!r} (expected snake_case English)")
    return str(raw).strip()


def validate_cluster_id(raw: str) -> str:
    if not CLUSTER_ID_RE.match(str(raw).strip()):
        raise IdError(f"not a reporting_cluster_id: {raw!r} (expected RC-{{GROUP}}-{{nnn}})")
    return str(raw).strip()


def validate_run_id(raw: str) -> str:
    value = str(raw).strip()
    if not RUN_ID_RE.match(value):
        raise IdError(
            f"not a run_id: {raw!r} (expected {{stage}}-{{yyyymmddHHMM[ssffffff]}}-{{8 hex}})"
        )
    return value


#: The prefix half of a ``run_id`` — the same grammar :data:`RUN_ID_RE` accepts.
RUN_ID_PREFIX_RE = re.compile(r"^[a-z][a-z0-9]{0,15}$")


def mint_run_id(prefix: str, *, now: "datetime | None" = None) -> str:
    """Mint ``{prefix}-{UTC yyyymmddHHMMssffffff}-{8 random hex}``.

    Model-and-human stages used to hand-type this stamp, and a hand-typed stamp is a
    *claim* about when a run happened that nothing checks: an answers run called
    ``ans-…082500…`` that was actually written at 07:55 then mis-sorted the ledger
    for every later reader.  A minted stamp is read off the clock instead, so the run
    directory name and the manifest agree with the filesystem by construction.

    The random suffix is not a checksum — it is what keeps two runs minted in the same
    microsecond from targeting the same immutable directory.
    """
    if not RUN_ID_PREFIX_RE.match(str(prefix).strip()):
        raise IdError(
            f"not a run_id prefix: {prefix!r} "
            "(expected 1-16 lower-case letters/digits starting with a letter)"
        )
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return validate_run_id(
        f"{str(prefix).strip()}-{stamp.strftime('%Y%m%d%H%M%S%f')}-{secrets.token_hex(4)}"
    )
