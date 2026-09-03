"""Two-layer honest fetching — the part of the access policy that is code, not prose.

``skills/collect/references/fetch-extract.md`` §1 states the policy an agent must follow
when it takes a publisher page. Three of its rules had no mechanical enforcement, and each
one has already been broken by a run that believed it was being careful:

* **One honest identity, in both layers.** A collector that volunteers a vendor crawler
  token (``ClaudeBot``, ``GPTBot``, …) makes that vendor's robots group the most specific
  match and then obeys the instruction it just issued to itself. Measured on
  ``aabb-market-meal-2024``: it removed every large German publisher from the sample while
  leaving the Turkish side intact, so the reader would have met a national copyright-lobby
  posture as "the German press covered this less". The identity here is a constant; there
  is no parameter to override it.
* **`robots.txt` 4xx means *unavailable*, and no restrictions apply** (RFC 9309 §2.3.1).
  Only 5xx (and an unreachable host) means "treat as disallowed". This was reverse-"fixed"
  once already.
* **Every HTTP refusal is retried in the browser** before anything is written down — and
  so is a 200 whose body is implausibly thin, because a JS-rendered site answers the
  status check with a shell and a nav menu. Only a both-layer failure is a
  ``fetch_failure``, which is why :class:`~newsab_corpus.collection_log.CollectionLogEntry`
  refuses one without ``layer: browser``.
* **A ``Disallow`` in our group reserves *retention*, not *reading*.** RFC 9309 is a
  crawling convention, not an access control, and the paths it most often names are
  utility paths (``/suche/``, ``/search/``, ``/tag/``, ``/print/``) disallowed for
  crawl-budget and duplicate-content reasons — reading that as a rights reservation reads
  out of it something it does not say. What carries legal weight is *keeping* (EU DSM
  Art. 4(3)), so a matching ``Disallow`` no longer refuses the fetch: the page is
  retrieved and the outcome comes back ``retention: reserved``, meaning it may be staged
  only at ``access_level: partial`` — title and lead. Refusing outright was a sampling
  decision taken at fetch time, and it fell on national press corps unevenly, which is the
  ``detr-doner`` failure wearing different clothes.

The module is deliberately *not* an extractor: choosing the body container is judgement and
stays with the collect agent. What it returns is the page bytes, the layer that got them,
and the robots verdict — which now sets how much of the page may be kept, not whether it
may be read.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

# --------------------------------------------------------------------------------------
# identity — the single definition site
# --------------------------------------------------------------------------------------

#: The robots product token this fetcher answers to.  Nothing in the wild names it today;
#: it exists so that a publisher who wants to address *us* has a name to write.
PRODUCT_TOKEN = "newsab-collect"

FETCHER_VERSION = "0.1"
DEFAULT_IDENTITY_PATH = Path(__file__).with_name("data") / "operator_identity.v1.json"
LOCAL_IDENTITY_PATH = Path(__file__).resolve().parents[3] / ".newsab/operator_identity.json"


def _operator_identity(path: Path | None = None) -> tuple[bool, str, str]:
    """Read a configured local identity, otherwise the release's safe starter default."""
    identity_path = path or (LOCAL_IDENTITY_PATH if LOCAL_IDENTITY_PATH.is_file() else DEFAULT_IDENTITY_PATH)
    payload = json.loads(identity_path.read_text(encoding="utf-8"))
    configured = payload.get("configured") is True
    url = payload.get("operator_url")
    email = payload.get("operator_email")
    if configured:
        parsed = urllib.parse.urlsplit(str(url or ""))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"collector operator_url is not an absolute HTTP(S) URL: {identity_path}")
        if not isinstance(email, str) or "@" not in email:
            raise RuntimeError(f"collector operator_email is not contactable: {identity_path}")
        if identity_path != DEFAULT_IDENTITY_PATH and _is_production_operator(email):
            raise RuntimeError(
                f"collector operator_email is another operator's contact; identify yourself: {identity_path}"
            )
    return configured, str(url or ""), str(email or "")


#: sha256 of the production collector's casefolded contact email.  A local identity file
#: (the one a clone writes for itself) may not borrow it: the User-Agent it produces would
#: be a false statement about who is fetching, and every complaint would reach the wrong
#: person.  A digest rather than the address, so no clone has to carry the address itself.
PRODUCTION_OPERATOR_EMAIL_SHA256 = "eb7e87757c72ab4ac9432be84b4020620ee46d6195c640bec817bc2f6d8557c0"


def _is_production_operator(email: str) -> bool:
    digest = hashlib.sha256(email.strip().casefold().encode("utf-8")).hexdigest()
    return digest == PRODUCTION_OPERATOR_EMAIL_SHA256


OPERATOR_CONFIGURED, OPERATOR_URL, OPERATOR_EMAIL = _operator_identity()

#: Truthful, specific and contactable when network collection is enabled. An
#: unconfigured public clone exposes no invented identity and cannot open a real layer.
USER_AGENT = (
    f"{PRODUCT_TOKEN}/{FETCHER_VERSION} (+{OPERATOR_URL}; "
    f"human-operated news-comparison research; contact: {OPERATOR_EMAIL})"
    if OPERATOR_CONFIGURED
    else f"{PRODUCT_TOKEN}/{FETCHER_VERSION} (operator identity not configured; network disabled)"
)


def require_operator_identity() -> None:
    """Refuse network access until the public-clone operator identifies themselves."""
    if OPERATOR_CONFIGURED:
        return
    raise RuntimeError(
        "collector identity is not configured; ask the user for their public website "
        "URL and contact email, then write .newsab/operator_identity.json with "
        "configured=true (see AGENTS.md)"
    )

#: Identities that are false statements about who is fetching.  The vendor tokens are
#: impersonation *and* silently rewrite which robots group applies; a bare browser UA is
#: the same lie pointed the other way.  Asserted in the tests, never configurable.
FORBIDDEN_UA_SUBSTRINGS = (
    "ClaudeBot",
    "anthropic-ai",
    "Claude-Web",
    "GPTBot",
    "CCBot",
    "Bytespider",
    "Mozilla/",
    "AppleWebKit",
)

#: Below this many characters of visible text, an HTTP 200 is treated as a refusal and
#: retried in the browser.  Measured on ``aabb-steppe-stone-2025``: six Mongolian pages served
#: 11–448 characters over HTTP and 650–6,200 in the browser.
DEFAULT_MIN_TEXT_CHARS = 600

#: Seconds between two requests to the same host.  Human pace, never crawl pace (§1.4).
DEFAULT_HOST_DELAY = 2.0

DEFAULT_TIMEOUT = 30.0


# --------------------------------------------------------------------------------------
# robots.txt — RFC 9309, read for the group that is actually addressed to us
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RobotsRule:
    allow: bool
    pattern: str

    @property
    def specificity(self) -> int:
        return len(self.pattern.removesuffix("$"))


@dataclass(frozen=True)
class RobotsPolicy:
    """What one origin's ``robots.txt`` says to *this* fetcher, and how we learned it."""

    #: ``group`` a group addressed to us was parsed · ``no-group`` the file had nothing for
    #: us · ``unavailable`` 4xx, so no restrictions apply · ``unreachable`` 5xx or a
    #: transport error, so retention is reserved until the host answers.
    verdict: str
    status: Optional[int]
    agent: Optional[str]
    rules: tuple[RobotsRule, ...] = ()
    detail: str = ""

    @property
    def reachable(self) -> bool:
        return self.verdict != "unreachable"

    def allows(self, url: str) -> bool:
        """Does the group addressed to us allow this path? — the RFC 9309 computation.

        The caller maps a ``False`` to ``retention: reserved`` (§1.4), never to a refusal
        to fetch: what this answers is how much of the page may be kept.
        """
        if self.verdict == "unreachable":
            return False
        return _rules_allow(self.rules, _match_target(url))

    def why(self, url: str) -> str:
        if self.verdict == "unreachable":
            return f"robots.txt unreachable ({self.detail}) — retention reserved"
        if self.verdict == "unavailable":
            return f"robots.txt unavailable ({self.detail}) — no restrictions apply"
        if self.verdict == "no-group":
            return "robots.txt has no group addressed to us — no restrictions apply"
        rule = _matching_rule(self.rules, _match_target(url))
        if rule is None:
            return f"robots.txt group {self.agent!r}: no rule matches this path"
        verb = "Allow" if rule.allow else "Disallow"
        return f"robots.txt group {self.agent!r}: {verb}: {rule.pattern}"


def parse_robots(text: str, *, product_token: str = PRODUCT_TOKEN) -> tuple[Optional[str], tuple[RobotsRule, ...]]:
    """Return ``(group name, rules)`` for the one group addressed to this fetcher.

    RFC 9309 §2.2.1: exactly one group applies — the most specific ``User-agent`` that
    names you, and ``*`` when nothing does.  Groups sharing a user-agent are merged.

    Everything else in the file is somebody else's mail.  A ``Disallow`` written for
    ``GPTBot`` is a statement about that vendor's bulk crawler, and adopting it "to be
    safe" is an unmandated sampling decision taken at fetch time — the exact failure this
    module exists to make impossible, so there is no flag to turn it on.
    """
    groups: list[tuple[set[str], list[RobotsRule]]] = []
    agents: set[str] = set()
    rules: list[RobotsRule] = []
    expecting_agent = True

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name = field_name.strip().lower()
        value = value.strip()
        if field_name in ("user-agent", "useragent"):
            if not expecting_agent:
                groups.append((agents, rules))
                agents, rules = set(), []
            expecting_agent = True
            agents.add(value.lower())
        elif field_name in ("allow", "disallow"):
            if not agents:
                continue  # a rule outside any group belongs to nobody
            expecting_agent = False
            if field_name == "disallow" and value == "":
                continue  # RFC 9309: an empty Disallow imposes nothing
            rules.append(RobotsRule(allow=field_name == "allow", pattern=value))
        # sitemap / crawl-delay and other fields do not open or close a group
    if agents:
        groups.append((agents, rules))

    for name in (product_token.lower(), "*"):
        matched = [r for names, r in groups if name in names]
        if matched:
            return name, tuple(rule for group in matched for rule in group)
    return None, ()


def _match_target(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    return _normalize_percent(target)


def _normalize_percent(value: str) -> str:
    # RFC 9309 §2.2.2 compares after normalizing percent-encoding.  Unquote then requote
    # so `/a%2Fb` and `/a/b` — and `/é` and `/%C3%A9` — compare the same way on both sides.
    return urllib.parse.quote(urllib.parse.unquote(value), safe="/?&=*$:@+,;~-._!()'")


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = _normalize_percent(pattern.removesuffix("$")) if pattern else ""
    expr = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile("^" + expr + ("$" if anchored else ""))


def _matching_rule(rules: Sequence[RobotsRule], target: str) -> Optional[RobotsRule]:
    best: Optional[RobotsRule] = None
    for rule in rules:
        if not _pattern_regex(rule.pattern).match(target):
            continue
        if best is None or rule.specificity > best.specificity:
            best = rule
        elif rule.specificity == best.specificity and rule.allow and not best.allow:
            best = rule  # RFC 9309 §2.2.2: an equally specific Allow wins
    return best


def _rules_allow(rules: Sequence[RobotsRule], target: str) -> bool:
    rule = _matching_rule(rules, target)
    return True if rule is None else rule.allow


# --------------------------------------------------------------------------------------
# how thin is too thin
# --------------------------------------------------------------------------------------

_DROPPED_ELEMENTS = re.compile(
    r"<(script|style|noscript|template|svg)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def visible_text(markup: str) -> str:
    """A crude whole-document text projection — enough to tell a shell from an article.

    This is not the extractor.  It answers one question: did the transport hand back a
    document with prose in it, or a navigation menu waiting for JavaScript?
    """
    stripped = _DROPPED_ELEMENTS.sub(" ", markup)
    return _WHITESPACE.sub(" ", html.unescape(_TAG.sub(" ", stripped))).strip()


# --------------------------------------------------------------------------------------
# the fetch itself
# --------------------------------------------------------------------------------------


@dataclass
class Attempt:
    layer: str
    status: Optional[int] = None
    text_chars: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "status": self.status,
            "text_chars": self.text_chars,
            "error": self.error,
        }


@dataclass
class FetchOutcome:
    url: str
    ok: bool
    #: The layer the outcome was decided at.
    #: A failure may only be logged as ``fetch_failure`` when this reads ``browser``:
    #: an HTTP-only refusal is a transport artifact, not the publisher's answer.
    layer: str
    robots: str
    #: How much of this page may be kept (§1.5).  ``full`` — the group addressed to us
    #: allows the path.  ``reserved`` — it disallows it, or ``robots.txt`` was unreachable:
    #: stage this one at ``access_level: partial``, title and lead only.  Never a reason to
    #: skip the page: the retention row is chosen at the scope sitting and applied
    #: identically to both groups, never per outlet at fetch time.
    retention: str = "full"
    final_url: Optional[str] = None
    status: Optional[int] = None
    text_chars: int = 0
    path: Optional[str] = None
    reason: Optional[str] = None
    attempts: list[Attempt] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "ok": self.ok,
            "layer": self.layer,
            "robots": self.robots,
            "retention": self.retention,
            "final_url": self.final_url,
            "status": self.status,
            "text_chars": self.text_chars,
            "path": self.path,
            "reason": self.reason,
            "attempts": [a.to_dict() for a in self.attempts],
        }


class BrowserUnavailable(RuntimeError):
    """Playwright could not be started, so the browser retry did not happen.

    Raised rather than folded into the outcome on purpose: a missing browser must never
    be reported as a both-layer failure, because that is the shape that reaches the
    reader as media silence.
    """


class _Layers:
    """Lazily-opened HTTP client and browser, both carrying :data:`USER_AGENT`."""

    def __init__(self, *, timeout: float) -> None:
        self._timeout = timeout
        self._client = None
        self._playwright = None
        self._browser = None
        self._context = None

    # -- HTTP ---------------------------------------------------------------------
    @property
    def client(self):
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - environment problem
                raise RuntimeError("the HTTP layer requires the httpx package") from exc
            self._client = httpx.Client(
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
                timeout=self._timeout,
            )
        return self._client

    def http_get(self, url: str) -> tuple[Optional[int], str, str]:
        response = self.client.get(url)
        return response.status_code, str(response.url), response.text

    # -- browser ------------------------------------------------------------------
    @property
    def page_context(self):
        if self._context is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise BrowserUnavailable(
                    "the browser retry requires the Python playwright package"
                ) from exc
            try:
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - depends on the local install
                raise BrowserUnavailable(f"chromium would not start: {exc}") from exc
            self._context = self._browser.new_context(user_agent=USER_AGENT)
        return self._context

    def browser_get(self, url: str) -> tuple[Optional[int], str, str]:
        page = self.page_context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self._timeout * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=self._timeout * 1000)
            except Exception:
                pass  # a page that never goes idle is still a page
            return (response.status if response else None), page.url, page.content()
        finally:
            page.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def __enter__(self) -> "_Layers":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class Fetcher:
    """Fetches URLs under the §1 policy, one host at a time, robots read once per origin."""

    def __init__(
        self,
        *,
        min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
        host_delay: float = DEFAULT_HOST_DELAY,
        timeout: float = DEFAULT_TIMEOUT,
        layers: Optional[_Layers] = None,
    ) -> None:
        self.min_text_chars = min_text_chars
        self.host_delay = host_delay
        if layers is None:
            require_operator_identity()
        self._layers = layers or _Layers(timeout=timeout)
        self._robots: dict[str, RobotsPolicy] = {}
        self._last_request: dict[str, float] = {}

    # -- pacing -------------------------------------------------------------------
    def _wait_turn(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).netloc.lower()
        previous = self._last_request.get(host)
        if previous is not None:
            remaining = self.host_delay - (time.monotonic() - previous)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request[host] = time.monotonic()

    # -- robots -------------------------------------------------------------------
    def robots_policy(self, url: str) -> RobotsPolicy:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        cached = self._robots.get(origin)
        if cached is not None:
            return cached
        policy = self._read_robots(origin)
        self._robots[origin] = policy
        return policy

    def _read_robots(self, origin: str) -> RobotsPolicy:
        self._wait_turn(origin)
        try:
            status, _, text = self._layers.http_get(f"{origin}/robots.txt")
        except Exception as exc:
            return RobotsPolicy("unreachable", None, None, detail=f"{type(exc).__name__}: {exc}")
        if status is not None and 400 <= status < 500:
            # RFC 9309 §2.3.1.  403 included: "unavailable" means no restrictions apply.
            # A host that 403s robots.txt but serves it to a browser is telling us which
            # layer to use next — it is not evidence that a rule exists.
            return RobotsPolicy("unavailable", status, None, detail=f"HTTP {status}")
        if status is None or status >= 500:
            return RobotsPolicy("unreachable", status, None, detail=f"HTTP {status}")
        agent, rules = parse_robots(text)
        if agent is None:
            return RobotsPolicy("no-group", status, None, detail=f"HTTP {status}")
        return RobotsPolicy("group", status, agent, rules, detail=f"HTTP {status}")

    # -- one URL ------------------------------------------------------------------
    def fetch(self, url: str, *, out_dir: Optional[Path] = None) -> FetchOutcome:
        policy = self.robots_policy(url)
        robots_note = policy.why(url)
        # §1.4: a matching Disallow reserves what may be kept, not what may be read.
        retention = "full" if policy.allows(url) else "reserved"
        outcome = FetchOutcome(
            url=url, ok=False, layer="http", robots=robots_note, retention=retention
        )

        self._wait_turn(url)
        markup: Optional[str] = None
        try:
            status, final_url, body = self._layers.http_get(url)
        except Exception as exc:
            outcome.attempts.append(Attempt("http", error=f"{type(exc).__name__}: {exc}"))
        else:
            chars = len(visible_text(body))
            outcome.attempts.append(Attempt("http", status=status, text_chars=chars))
            if status is not None and 200 <= status < 300 and chars >= self.min_text_chars:
                outcome.ok, outcome.status, outcome.final_url, outcome.text_chars = (
                    True, status, final_url, chars,
                )
                markup = body

        if markup is None:
            # §1.3 — a non-2xx *or* an implausibly thin 200 both go back to the browser,
            # and nothing may be written down about this host until they have.
            outcome.layer = "browser"
            self._wait_turn(url)
            try:
                status, final_url, body = self._layers.browser_get(url)
            except BrowserUnavailable:
                raise
            except Exception as exc:
                outcome.attempts.append(Attempt("browser", error=f"{type(exc).__name__}: {exc}"))
                outcome.reason = f"both layers refused: {exc}"
            else:
                chars = len(visible_text(body))
                outcome.attempts.append(Attempt("browser", status=status, text_chars=chars))
                outcome.status, outcome.final_url, outcome.text_chars = status, final_url, chars
                markup = body
                if (status is None or 200 <= status < 300) and chars >= self.min_text_chars:
                    outcome.ok = True
                else:
                    outcome.reason = (
                        f"both layers refused: browser HTTP {status}, "
                        f"{chars} chars of visible text"
                    )

        if markup is not None and out_dir is not None:
            # A refusal keeps its bytes too, under a name that cannot be mistaken for a
            # stageable document.  "Only a both-layer failure is a finding" is checkable
            # only if the thing the browser actually got is on disk to be looked at.
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / _filename_for(url, failed=not outcome.ok)
            path.write_text(markup, encoding="utf-8")
            outcome.path = str(path)
        return outcome

    def close(self) -> None:
        self._layers.close()


def _filename_for(url: str, *, failed: bool = False) -> str:
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    slug = re.sub(r"[^a-z0-9]+", "-", (host + parts.path).lower()).strip("-")[:80]
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"{slug or 'page'}-{digest}{'.refused' if failed else ''}.html"


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _read_urls(args: argparse.Namespace) -> list[str]:
    urls = list(args.urls)
    if args.urls_from:
        source = sys.stdin if args.urls_from == "-" else open(args.urls_from, encoding="utf-8")
        with source as handle:
            urls += [line.strip() for line in handle if line.strip() and not line.startswith("#")]
    return urls


def cmd_fetch(args: argparse.Namespace) -> int:
    if args.show_identity:
        print(USER_AGENT)
        return 0 if OPERATOR_CONFIGURED else 2
    urls = _read_urls(args)
    if not urls:
        print("fetch: no URLs given (pass them as arguments or via --urls-from)", file=sys.stderr)
        return 2

    out_dir = Path(args.out) if args.out else None
    try:
        fetcher = Fetcher(
            min_text_chars=args.min_chars, host_delay=args.delay, timeout=args.timeout
        )
    except RuntimeError as exc:
        print(f"fetch: {exc}", file=sys.stderr)
        return 2
    outcomes: list[FetchOutcome] = []
    try:
        # Serial, grouped by host, so a host never sees two overlapping requests (§1.4).
        for url in sorted(urls, key=lambda u: urllib.parse.urlsplit(u).netloc.lower()):
            try:
                outcome = fetcher.fetch(url, out_dir=out_dir)
            except BrowserUnavailable as exc:
                print(f"fetch: {exc}", file=sys.stderr)
                print(
                    "fetch: the browser retry is mandatory — an HTTP-only refusal must "
                    "never be recorded as a fetch_failure. Install the browser "
                    "(`python -m playwright install chromium`) and re-run.",
                    file=sys.stderr,
                )
                return 3
            outcomes.append(outcome)
            if not args.json:
                _print_outcome(outcome)
    finally:
        fetcher.close()

    if args.json:
        print(json.dumps([o.to_dict() for o in outcomes], ensure_ascii=False, indent=2))
    else:
        failures = [o for o in outcomes if not o.ok]
        print(f"-- {len(outcomes) - len(failures)}/{len(outcomes)} fetched, identity {USER_AGENT}")
        reserved = [o for o in outcomes if o.ok and o.retention == "reserved"]
        for outcome in reserved:
            print(
                f"-- {outcome.url}: retention reserved — `access_level: partial`, "
                f"title and lead only"
            )
        for outcome in failures:
            if outcome.layer == "browser":
                print(
                    f"-- {outcome.url}: both layers refused — loggable as "
                    f"`fetch_failure --layer browser`"
                )
            else:
                print(f"-- {outcome.url}: {outcome.reason} (NOT a fetch_failure: {outcome.layer})")
    return 0 if all(o.ok for o in outcomes) else 1


def _print_outcome(outcome: FetchOutcome) -> None:
    mark = "ok " if outcome.ok else "FAIL"
    trail = " -> ".join(
        f"{a.layer} {a.error or a.status} {a.text_chars}c" for a in outcome.attempts
    )
    print(f"{mark} [{outcome.layer}] {outcome.url}")
    print(f"     {outcome.robots}")
    if outcome.retention == "reserved":
        print("     retention: RESERVED — stage at `access_level: partial` (title + lead)")
    if trail:
        print(f"     {trail}")
    if outcome.path:
        print(f"     {outcome.path}")
    if outcome.reason and not outcome.ok:
        print(f"     {outcome.reason}")


def build_fetch_parser(sub) -> None:
    p = sub.add_parser(
        "fetch",
        help="fetch publisher pages under the collect access policy (honest UA, "
        "robots by our group only and only to set retention, browser retry on every "
        "refusal)",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("urls", nargs="*", help="publisher page URLs")
    p.add_argument("--urls-from", metavar="FILE", help="read URLs from a file, or - for stdin")
    p.add_argument("--out", metavar="DIR", help="write each fetched document here")
    p.add_argument(
        "--min-chars",
        type=int,
        default=DEFAULT_MIN_TEXT_CHARS,
        help=f"visible-text floor below which a 200 is retried in the browser "
        f"(default {DEFAULT_MIN_TEXT_CHARS})",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_HOST_DELAY,
        help=f"seconds between two requests to the same host (default {DEFAULT_HOST_DELAY})",
    )
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p.add_argument("--json", action="store_true", help="machine-readable outcomes on stdout")
    p.add_argument(
        "--show-identity",
        action="store_true",
        help="print the user agent both layers send, and exit",
    )
    p.set_defaults(func=cmd_fetch)
