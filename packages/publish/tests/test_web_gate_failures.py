"""One gate run reports every failure it found, not only the first.

A whole-tree run costs minutes, so fail-fast made each round surface exactly one defect:
an `/ar/` RTL assertion hid an unrelated `/ru/` card overflow and the two bugs had to
be found serially, each at full price.  These tests pin the two halves of the fix — the
run keeps going after a failure, and a step still stops at *its own* first failure so the
report is not a cascade of assertions reading an already-broken page.
"""

from __future__ import annotations

import pytest

from newsab_publish import chrome
from newsab_publish.web_gate import (
    Gate,
    _assert,
    _check_chrome,
    _check_semantics,
    _sequence,
)
from newsab_schema.io import ArtifactError


def _page(*, locale: str = "en", theme: bool = True, inline_style: bool = False) -> str:
    token = ' data-theme-token="paper"' if theme else ""
    style = "<style>p{}</style>" if inline_style else ""
    return (
        f'<!doctype html><html lang="{locale}"{token} data-site-locale="{locale}">'
        f'<head><link rel="stylesheet" href="{chrome.STYLESHEET_URL}">'
        f'<script src="{chrome.SCRIPT_URL}" defer></script>{style}</head>'
        "<body></body></html>"
    )


def _tree(root, pages: dict[str, str]) -> list[str]:
    urls = []
    for locale, text in pages.items():
        target = root / locale / "topics" / "aabb-river-light-2026"
        target.mkdir(parents=True)
        (target / "index.html").write_text(text, encoding="utf-8")
        urls.append(f"/{locale}/topics/aabb-river-light-2026/")
    return sorted(urls)


def test_a_clean_run_raises_nothing():
    gate = Gate()
    with gate.step("first"):
        _assert(True, "unreachable")
    gate.raise_if_failed()


def test_two_independent_failures_are_both_reported():
    gate = Gate()
    with gate.step("ar home"):
        _assert(False, "/ar/: suggestion control is not before About")
    with gate.step("ru home"):
        _assert(False, "/ru/ at 768px: card content escapes its own card")
    with pytest.raises(ArtifactError) as caught:
        gate.raise_if_failed()
    message = str(caught.value)
    assert "2 failure(s)" in message
    assert "/ar/: suggestion control is not before About" in message
    assert "/ru/ at 768px: card content escapes its own card" in message


def test_a_step_stops_at_its_own_first_failure():
    """Everything after a failed assertion in the same step is reading a broken page."""
    reached = []
    gate = Gate()
    with gate.step("one page"):
        _assert(False, "first")
        reached.append("second")
        _assert(False, "second")
    assert reached == []
    assert gate.failures == ["first"]


def test_an_unexpected_error_inside_a_step_is_a_failure_not_a_crash():
    gate = Gate()
    with gate.step("/en/: evidence modal"):
        raise TimeoutError("locator.click: Timeout 3000ms exceeded")
    with gate.step("/en/: share controls"):
        _assert(False, "share landing differs")
    assert len(gate.failures) == 2
    assert gate.failures[0].startswith("/en/: evidence modal: TimeoutError")


def test_a_failed_step_does_not_stop_the_later_steps_of_the_same_page():
    """The `_sequence` runner is what keeps one bad step from ending a page."""

    class FakePage:
        def __init__(self):
            self.dismissed = 0

        def evaluate(self, _script):
            self.dismissed += 1

    page = FakePage()
    gate = Gate()
    ran = []

    def bad():
        ran.append("bad")
        _assert(False, "/en/: evidence modal did not open")

    def good():
        ran.append("good")

    _sequence(gate, page, [("bad step", bad), ("good step", good)])
    assert ran == ["bad", "good"]
    assert gate.failures == ["/en/: evidence modal did not open"]
    # Recovery runs exactly once — after the failure, never after a clean step.
    assert page.dismissed == 1


def test_static_chrome_checks_name_every_bad_page(tmp_path):
    urls = _tree(
        tmp_path,
        {
            "en": _page(theme=False),
            "zh-CN": _page(inline_style=True),
            "fr": _page(),
        },
    )
    gate = Gate()
    _check_chrome(gate, tmp_path, urls, dict.fromkeys(
        (chrome.STYLESHEET_PATH, chrome.SCRIPT_PATH), b""
    ))
    joined = "\n".join(gate.failures)
    assert "/en/topics/aabb-river-light-2026/: page does not state a theme token" in joined
    assert (
        "/zh-CN/topics/aabb-river-light-2026/: content document still inlines a stylesheet"
        in joined
    )
    assert "/fr/" not in joined


def test_check_semantics_without_a_gate_still_raises_for_unit_tests(tmp_path):
    """The single-page contract other tests rely on is unchanged when no gate is passed."""
    urls = _tree(tmp_path, {"en": _page()})
    with pytest.raises(ArtifactError):
        _check_semantics(tmp_path, urls)
    gate = Gate()
    assert _check_semantics(tmp_path, urls, gate) == 1
    assert len(gate.failures) == 1
