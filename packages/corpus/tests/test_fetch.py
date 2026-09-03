"""The access policy, tested where it has actually failed before.

Every case here corresponds to a mistake a run has already made, or to a rule whose
violation would reach a reader as a finding about the world rather than about a socket.
"""

from __future__ import annotations

import hashlib

import pytest

import newsab_corpus.fetch as fetch_module
from newsab_corpus.fetch import (
    DEFAULT_MIN_TEXT_CHARS,
    FORBIDDEN_UA_SUBSTRINGS,
    OPERATOR_CONFIGURED,
    PRODUCT_TOKEN,
    USER_AGENT,
    BrowserUnavailable,
    Fetcher,
    RobotsPolicy,
    parse_robots,
    visible_text,
    _operator_identity,
)


# ---------------------------------------------------------------------------- identity


def test_user_agent_is_truthful_specific_and_contactable():
    assert USER_AGENT.startswith(f"{PRODUCT_TOKEN}/")
    if OPERATOR_CONFIGURED:
        assert "+https://" in USER_AGENT      # who is doing this
        assert "@" in USER_AGENT              # and how to reach them
        assert "human-operated" in USER_AGENT
    else:
        assert "network disabled" in USER_AGENT
        assert "@" not in USER_AGENT


def test_real_layers_refuse_an_unconfigured_operator(monkeypatch):
    monkeypatch.setattr(fetch_module, "OPERATOR_CONFIGURED", False)
    with pytest.raises(RuntimeError, match="collector identity is not configured"):
        Fetcher()


def test_local_operator_identity_schema(tmp_path):
    identity = tmp_path / "operator_identity.json"
    identity.write_text(
        '{"configured": true, "operator_url": "https://reader.example/about", '
        '"operator_email": "collector@reader.example"}',
        encoding="utf-8",
    )
    assert _operator_identity(identity) == (
        True, "https://reader.example/about", "collector@reader.example"
    )


def test_a_local_identity_may_not_borrow_the_production_operators_contact(tmp_path, monkeypatch):
    # The production address is known to the collector only as a digest; the test
    # stands a throwaway address in its place and checks the comparison, not the address.
    borrowed = "collector@production.example"
    monkeypatch.setattr(
        fetch_module,
        "PRODUCTION_OPERATOR_EMAIL_SHA256",
        hashlib.sha256(borrowed.encode("utf-8")).hexdigest(),
    )
    identity = tmp_path / "operator_identity.json"
    identity.write_text(
        '{"configured": true, "operator_url": "https://reader.example/about", '
        '"operator_email": " Collector@Production.example "}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="another operator's contact"):
        _operator_identity(identity)


def test_user_agent_borrows_nobody_elses_name():
    # Both directions of the same lie: a vendor crawler token is impersonation and
    # rewrites which robots group applies; a browser UA is stealth.
    for token in FORBIDDEN_UA_SUBSTRINGS:
        assert token.lower() not in USER_AGENT.lower()


# ------------------------------------------------------------------------------ robots


def _rules_for(text: str):
    return parse_robots(text)


def test_only_our_group_is_read():
    # The aabb-market-meal-2024 incident in one file: the vendor groups disallow everything and
    # none of it is addressed to us.
    agent, rules = _rules_for(
        """
        User-agent: GPTBot
        Disallow: /

        User-agent: ClaudeBot
        Disallow: /

        User-agent: *
        Disallow: /suche
        """
    )
    assert agent == "*"
    policy = RobotsPolicy("group", 200, agent, rules)
    assert policy.allows("https://example.de/politik/artikel-1.html")
    assert not policy.allows("https://example.de/suche?q=x")


def test_a_group_naming_us_wins_over_the_star_group():
    # RFC 9309: the most specific group that names you.  Nothing writes this today, but a
    # publisher who wants to address *us* must be obeyed when they do.
    agent, rules = _rules_for(
        f"""
        User-agent: *
        Disallow: /

        User-agent: {PRODUCT_TOKEN}
        Disallow: /archive
        """
    )
    assert agent == PRODUCT_TOKEN
    policy = RobotsPolicy("group", 200, agent, rules)
    assert policy.allows("https://example.com/news/1")
    assert not policy.allows("https://example.com/archive/1")


def test_groups_sharing_a_user_agent_are_merged():
    agent, rules = _rules_for(
        """
        User-agent: *
        Disallow: /a

        User-agent: *
        Disallow: /b
        """
    )
    policy = RobotsPolicy("group", 200, agent, rules)
    assert not policy.allows("https://example.com/a")
    assert not policy.allows("https://example.com/b")


def test_one_user_agent_line_may_open_a_group_for_several_names():
    agent, rules = _rules_for(
        """
        User-agent: Bingbot
        User-agent: *
        Disallow: /private
        """
    )
    assert agent == "*"
    policy = RobotsPolicy("group", 200, agent, rules)
    assert not policy.allows("https://example.com/private/x")


def test_empty_disallow_imposes_nothing():
    agent, rules = _rules_for("User-agent: *\nDisallow:")
    assert rules == ()
    assert RobotsPolicy("group", 200, agent, rules).allows("https://example.com/anything")


def test_longest_match_wins_and_an_equal_allow_beats_a_disallow():
    agent, rules = _rules_for(
        """
        User-agent: *
        Disallow: /news
        Allow: /news/free
        """
    )
    policy = RobotsPolicy("group", 200, agent, rules)
    assert not policy.allows("https://example.com/news/paid/1")
    assert policy.allows("https://example.com/news/free/1")

    agent, rules = _rules_for("User-agent: *\nDisallow: /x\nAllow: /x")
    assert RobotsPolicy("group", 200, agent, rules).allows("https://example.com/x")


def test_wildcards_and_end_anchors():
    agent, rules = _rules_for(
        """
        User-agent: *
        Disallow: /*.pdf$
        Disallow: /a/*/b
        """
    )
    policy = RobotsPolicy("group", 200, agent, rules)
    assert not policy.allows("https://example.com/docs/report.pdf")
    assert policy.allows("https://example.com/docs/report.pdf.html")
    assert not policy.allows("https://example.com/a/anything/b")


def test_comments_and_case_are_handled():
    agent, rules = _rules_for(
        """
        # a comment
        USER-AGENT: *
        DISALLOW: /secret   # trailing comment
        """
    )
    assert agent == "*"
    assert not RobotsPolicy("group", 200, agent, rules).allows("https://example.com/secret/1")


def test_rules_before_any_user_agent_line_belong_to_nobody():
    agent, rules = _rules_for("Disallow: /\n\nUser-agent: *\nAllow: /")
    assert agent == "*"
    assert RobotsPolicy("group", 200, agent, rules).allows("https://example.com/x")


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 429])
def test_4xx_robots_is_unavailable_so_nothing_is_restricted(status):
    # RFC 9309 §2.3.1, and the rule that was reverse-"fixed" once already: a 403 on
    # robots.txt is not evidence that a rule exists and we should assume the worst.
    fetcher = _fetcher(http={"https://example.com/robots.txt": (status, "")})
    policy = fetcher.robots_policy("https://example.com/a")
    assert policy.verdict == "unavailable"
    assert policy.allows("https://example.com/a")


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_robots_is_unreachable_so_the_host_is_disallowed(status):
    fetcher = _fetcher(http={"https://example.com/robots.txt": (status, "")})
    policy = fetcher.robots_policy("https://example.com/a")
    assert policy.verdict == "unreachable"
    assert not policy.allows("https://example.com/a")


def test_a_transport_error_on_robots_is_unreachable_not_permission():
    fetcher = _fetcher(http={})
    policy = fetcher.robots_policy("https://example.com/a")
    assert policy.verdict == "unreachable"


def test_robots_is_read_once_per_origin():
    layers = _Layers({"https://example.com/robots.txt": (200, "User-agent: *\nAllow: /")})
    fetcher = Fetcher(host_delay=0, layers=layers)
    fetcher.robots_policy("https://example.com/a")
    fetcher.robots_policy("https://example.com/b")
    assert layers.http_calls.count("https://example.com/robots.txt") == 1


# ------------------------------------------------------------------- thin-body detection


def test_visible_text_ignores_script_style_and_markup():
    markup = "<html><head><style>p{color:red}</style></head><body><script>x=1</script>" \
             "<nav>Home</nav><p>Real&nbsp;prose here.</p></body></html>"
    text = visible_text(markup)
    assert "x=1" not in text and "color:red" not in text
    assert "Real" in text and "prose here." in text


# ------------------------------------------------------------------------- the two layers


class _Layers:
    """A stand-in for the HTTP client and the browser, recording what each was asked for."""

    def __init__(self, http: dict, browser: dict | None = None, browser_available: bool = True):
        self._http = http
        self._browser = browser or {}
        self._browser_available = browser_available
        self.http_calls: list[str] = []
        self.browser_calls: list[str] = []

    def http_get(self, url):
        self.http_calls.append(url)
        if url not in self._http:
            raise ConnectionError("no route to host")
        status, body = self._http[url]
        return status, url, body

    def browser_get(self, url):
        if not self._browser_available:
            raise BrowserUnavailable("chromium would not start")
        self.browser_calls.append(url)
        if url not in self._browser:
            raise ConnectionError("no route to host")
        status, body = self._browser[url]
        return status, url, body

    def close(self):
        pass


def _fetcher(*, http=None, browser=None, browser_available=True, **kwargs) -> Fetcher:
    layers = _Layers(http or {}, browser, browser_available)
    return Fetcher(host_delay=0, layers=layers, **kwargs)


def _article(chars: int = DEFAULT_MIN_TEXT_CHARS + 100) -> str:
    return "<html><body><p>" + ("word " * (chars // 5)) + "</p></body></html>"


def test_a_healthy_http_fetch_never_opens_the_browser():
    layers = _Layers(
        {
            "https://example.com/robots.txt": (200, "User-agent: *\nAllow: /"),
            "https://example.com/a": (200, _article()),
        }
    )
    fetcher = Fetcher(host_delay=0, layers=layers)
    outcome = fetcher.fetch("https://example.com/a")
    assert outcome.ok and outcome.layer == "http"
    assert layers.browser_calls == []


def test_an_http_403_is_retried_in_the_browser_and_can_succeed():
    # A bot-score 403 is a guess about transport, not the publisher's answer about who may
    # read the page.  This must never be recorded as a fetch_failure.
    fetcher = _fetcher(
        http={
            "https://example.com/robots.txt": (200, "User-agent: *\nAllow: /"),
            "https://example.com/a": (403, "<html><body>Access denied</body></html>"),
        },
        browser={"https://example.com/a": (200, _article())},
    )
    outcome = fetcher.fetch("https://example.com/a")
    assert outcome.ok and outcome.layer == "browser"
    assert [a.layer for a in outcome.attempts] == ["http", "browser"]


def test_a_thin_200_is_also_a_refusal_and_goes_back_to_the_browser():
    # aabb-steppe-stone-2025: JS-rendered pages answered 200 with 11-448 characters of shell.
    fetcher = _fetcher(
        http={
            "https://example.mn/robots.txt": (200, "User-agent: *\nAllow: /"),
            "https://example.mn/a": (200, "<html><body><nav>Мэдээ</nav></body></html>"),
        },
        browser={"https://example.mn/a": (200, _article())},
    )
    outcome = fetcher.fetch("https://example.mn/a")
    assert outcome.ok and outcome.layer == "browser"
    assert outcome.text_chars >= DEFAULT_MIN_TEXT_CHARS


def test_only_a_both_layer_failure_is_reported_as_one():
    fetcher = _fetcher(
        http={
            "https://example.com/robots.txt": (200, "User-agent: *\nAllow: /"),
            "https://example.com/a": (403, "denied"),
        },
        browser={"https://example.com/a": (403, "denied")},
    )
    outcome = fetcher.fetch("https://example.com/a")
    assert not outcome.ok
    # `layer: browser` is exactly what CollectionLogEntry demands of a fetch_failure.
    assert outcome.layer == "browser"


def test_a_missing_browser_is_raised_never_folded_into_a_failure():
    # The dangerous shape: a tooling gap reported as a both-layer refusal, which reaches
    # the reader as media silence.
    fetcher = _fetcher(
        http={
            "https://example.com/robots.txt": (200, "User-agent: *\nAllow: /"),
            "https://example.com/a": (403, "denied"),
        },
        browser_available=False,
    )
    with pytest.raises(BrowserUnavailable):
        fetcher.fetch("https://example.com/a")


def test_a_disallowed_path_is_fetched_but_comes_back_retention_reserved():
    # §1.4: a Disallow in our group reserves what may be *kept*, not what may be read.
    # Refusing the fetch outright removed whole national press corps from the sample —
    # the German press disallows its utility paths, much of the world's does not.
    layers = _Layers(
        {
            "https://example.com/robots.txt": (200, "User-agent: *\nDisallow: /recherche"),
            "https://example.com/recherche": (200, _article()),
        }
    )
    fetcher = Fetcher(host_delay=0, layers=layers)
    outcome = fetcher.fetch("https://example.com/recherche")
    assert outcome.ok and outcome.layer == "http"
    assert outcome.retention == "reserved"
    assert layers.http_calls == [
        "https://example.com/robots.txt",
        "https://example.com/recherche",
    ]


def test_an_allowed_path_keeps_full_retention():
    fetcher = _fetcher(
        http={
            "https://example.com/robots.txt": (200, "User-agent: *\nDisallow: /suche"),
            "https://example.com/artikel/1": (200, _article()),
        }
    )
    outcome = fetcher.fetch("https://example.com/artikel/1")
    assert outcome.ok and outcome.retention == "full"


def test_an_unreachable_robots_reserves_retention_without_blocking_the_fetch():
    # RFC 9309 says 5xx means "treat as disallowed"; under §1.4 that is a retention
    # verdict, so a host having a bad five minutes cannot delete itself from the sample.
    fetcher = _fetcher(
        http={
            "https://example.com/robots.txt": (503, ""),
            "https://example.com/a": (200, _article()),
        }
    )
    outcome = fetcher.fetch("https://example.com/a")
    assert outcome.ok and outcome.retention == "reserved"


def test_the_fetched_document_is_written_where_the_outcome_says(tmp_path):
    fetcher = _fetcher(
        http={
            "https://example.com/robots.txt": (200, "User-agent: *\nAllow: /"),
            "https://example.com/a": (200, _article()),
        }
    )
    outcome = fetcher.fetch("https://example.com/a", out_dir=tmp_path / "raw")
    assert outcome.path is not None
    from pathlib import Path

    assert Path(outcome.path).read_text(encoding="utf-8") == _article()


def test_a_both_layer_refusal_keeps_the_bytes_it_was_refused_with(tmp_path):
    fetcher = _fetcher(
        http={
            "https://example.com/robots.txt": (200, "User-agent: *\nAllow: /"),
            "https://example.com/a": (403, "denied"),
        },
        browser={"https://example.com/a": (403, "<html><body>Are you a robot?</body></html>")},
    )
    outcome = fetcher.fetch("https://example.com/a", out_dir=tmp_path)
    assert not outcome.ok
    assert outcome.path is not None and outcome.path.endswith(".refused.html")
