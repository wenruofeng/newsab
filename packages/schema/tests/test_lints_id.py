"""The Indonesian lint lexicon (lints-0.4).

Before this lexicon existed, every `id` text produced one `lexicon_coverage` FLAG and
nothing else: the id side of topic C carried no mechanical checking while zh and en
carried four rules each.  These tests pin the shapes the lexicon was
written for, and — just as importantly — the shapes it must not fire on.

The lists are agent-authored and unreviewed by an Indonesian speaker.  That is recorded in
the lexicon itself; these tests do not make them calibrated.
"""

from newsab_schema.lints import lint_text
from newsab_schema.lints.rules import LintVerdict


def rules(text: str, profile: str = "editorial_sentence") -> list[str]:
    return [f.rule for f in lint_text(text, "id", profile=profile)]


def test_indonesian_is_no_longer_an_unlintable_language():
    assert "lexicon_coverage" not in rules("Kalimat apa pun.")


def test_an_unlisted_language_still_says_so_rather_than_passing_clean():
    """The honest-silence behaviour must survive: Swahili is in scope but has no lexicon."""
    findings = lint_text("Sentensi yoyote.", "sw")
    assert [f.rule for f in findings] == ["lexicon_coverage"]
    assert findings[0].verdict is LintVerdict.FLAG


def test_a_proposition_without_a_presentation_marker_fails():
    assert "presentation_marker" in rules(
        "Kebijakan kuota diterapkan pemerintah pada Januari 2026.",
        profile="observation_proposition",
    )


def test_a_passive_presentation_marker_satisfies_the_requirement():
    assert "presentation_marker" not in rules(
        "Kuota digambarkan sebagai upaya menjaga harga.",
        profile="observation_proposition",
    )


def test_an_agent_inserted_passive_still_counts_as_describing():
    """"digambarkan pemerintah sebagai" breaks the contiguous phrase — the bare form saves it.

    This is the id twin of the zh bare-form false negative: the form that *names who is
    framing* is the most descriptive one available, and it was the one being rejected.
    """
    assert "presentation_marker" not in rules(
        "Pemberitaan itu digambarkan pemerintah sebagai langkah wajar.",
        profile="observation_proposition",
    )


def test_causal_language_is_caught_in_both_affix_shapes():
    for text in (
        "Kuota diperketat karena harga turun.",
        "Kebijakan itu bertujuan menaikkan harga.",
        "Angka itu mencerminkan tekanan pada peleburan.",
        "Penurunan produksi disebabkan oleh kuota baru.",
    ):
        assert "causal_language" in rules(text), text


def test_a_country_cannot_be_the_subject():
    findings = lint_text("Indonesia menganggap investasi Tiongkok penting.", "id")
    scope = [f for f in findings if f.rule == "scope_subject"]
    assert scope and scope[0].verdict is LintVerdict.FAIL
    assert "disampel" in (scope[0].suggestion or "")


def test_a_named_actor_speaking_is_not_a_country_as_subject():
    """"Kementerian ESDM menyatakan" is legitimate: someone said it, and we name them."""
    assert "scope_subject" not in rules("Kementerian ESDM menyatakan kuota akan direvisi.")


def test_verdict_words_are_flagged_not_failed():
    findings = [f for f in lint_text("Faktanya, laporan itu memelintir angka.", "id")
                if f.rule == "factual_verdict"]
    assert findings
    assert all(f.verdict is LintVerdict.FLAG for f in findings)
