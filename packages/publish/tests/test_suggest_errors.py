"""A refused submission or suggestion says *which* refusal it was.

Every server refusal used to collapse into one sentence — "the archive was not received,
check the invitation, archive and connection" — so a reader who mistyped an invitation
code could only tell an invitation problem from a paused intake by opening the browser
console on the real form.  The modal now maps the codes a reader
can act on to their own sentence and keeps the catch-all for the rest.

These tests pin the two halves that can silently rot apart: the code table in the script
and the copy tables it indexes into.
"""

from __future__ import annotations

import re

import pytest

from newsab_schema import HALO_LOCALE_CODES

from newsab_publish import suggest as G


def _table(name: str) -> dict[str, str]:
    """The literal ``var <name>={...}`` object out of the generated script."""
    script = G.suggestion_js("en")
    match = re.search(rf"\bvar {name}=\{{(.*?)\}};", script, re.S)
    assert match, f"the suggestion script no longer declares {name}"
    return dict(
        (key.strip("'"), value.strip("'"))
        for key, value in re.findall(r"([A-Za-z_-]+|'[^']+'):(1|'[^']+')", match.group(1))
    )


def test_every_mapped_code_names_copy_that_exists_in_every_locale():
    keys = set(_table("ERRORS").values())
    assert keys, "no error code is mapped at all"
    for locale in HALO_LOCALE_CODES:
        missing = keys - set(G._COPY[locale])
        assert not missing, (locale, missing)


@pytest.mark.parametrize(
    "code, key",
    [
        # The three a reader hit or could hit on the live form.
        ("INVITE_REQUIRED", "err_invite"),
        ("TURNSTILE_FAILED", "err_verify"),
        # ...plus the ones a reader can act on rather than only wait out.
        ("DUPLICATE_ARCHIVE", "err_duplicate"),
        ("CONTROL_REFUSED", "err_control"),
        ("UPLOAD_SLOT_EXPIRED", "err_expired"),
        ("COPY_VERSION_CHANGED", "err_reload"),
        ("RATE_LIMITED", "err_rate"),
        # A local archive-reader failure must never read as a server refusal.
        ("envelope", "err_archive"),
        ("archive-size", "err_too_large"),
    ],
)
def test_reader_actionable_codes_have_their_own_sentence(code, key):
    assert _table("ERRORS")[code] == key


def test_a_paused_intake_is_answered_by_the_form_that_asked():
    """The two forms pause independently and say so in their own words, so the shared
    table only marks a code as "paused" and each caller supplies its own string."""
    paused = _table("PAUSED")
    assert set(paused) == {
        "INTAKE_PAUSED",
        "DAILY_BUDGET_REACHED",
        "SUBMISSIONS_PAUSED",
        "SUBMISSION_BUDGET_REACHED",
    }
    script = G.suggestion_js("en")
    assert "explain(error,'paused','failed')" in script
    assert "explain(error,'upload_paused','upload_failed')" in script
    assert "explain(error,'upload_paused','err_archive')" in script


def test_the_catch_all_sentences_survive_for_unmapped_codes():
    """An unrecognised code is not a blank status line: both forms keep the sentence they
    had before this table existed."""
    mapped = set(_table("ERRORS")) | set(_table("PAUSED"))
    for code in ("ORIGIN_REFUSED", "INVALID_JSON", "NOT_FOUND"):
        assert code not in mapped
    for locale in HALO_LOCALE_CODES:
        assert G._COPY[locale]["failed"]
        assert G._COPY[locale]["upload_failed"]


def test_only_the_size_limit_sentence_carries_a_size_slot():
    """``explain`` fills ``{size}`` from the intake config and falls back to the catch-all
    when the limit is unknown; a second sentence with the slot would silently keep it."""
    for locale in HALO_LOCALE_CODES:
        with_slot = {
            key for key, value in G._COPY[locale].items() if "{size}" in value
        }
        assert with_slot == {"archive_summary", "err_too_large"}, locale
