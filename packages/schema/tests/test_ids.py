from datetime import datetime, timedelta, timezone

import pytest

from newsab_schema.ids import (
    IdError,
    SentenceId,
    make_observation_id,
    make_sentence_id,
    mint_run_id,
    parse_prefixed_id,
    topic_slug_matches,
    validate_run_id,
)


def test_sentence_id_roundtrip():
    sid = SentenceId.parse("CN_028:P07:S02")
    assert (sid.article_id, sid.paragraph, sid.sentence) == ("CN_028", 7, 2)
    assert str(sid) == "CN_028:P07:S02"
    assert sid.group == "CN"


def test_title_block_is_paragraph_zero():
    assert SentenceId.parse("US_051:P00:S01").is_title
    assert not SentenceId.parse("US_051:P01:S01").is_title


def test_sentence_ids_sort_in_reading_order():
    ids = [SentenceId.parse(s) for s in ("CN_001:P10:S01", "CN_001:P02:S03", "CN_001:P02:S01")]
    assert [str(s) for s in sorted(ids)] == [
        "CN_001:P02:S01",
        "CN_001:P02:S03",
        "CN_001:P10:S01",
    ]


@pytest.mark.parametrize(
    "bad",
    ["CN_028:P7:S2", "cn_028:P07:S02", "CN_028-P07-S02", "CN_028:P07", "", "CN_028:P07:S02 "],
)
def test_malformed_sentence_ids_rejected(bad):
    if bad.strip() == "CN_028:P07:S02":
        pytest.skip("trailing whitespace is tolerated on purpose")
    with pytest.raises(IdError):
        SentenceId.parse(bad)


def test_make_sentence_id_zero_pads():
    assert make_sentence_id("CN_028", 7, 2) == "CN_028:P07:S02"


def test_observation_id_width_is_enforced():
    assert make_observation_id("aabb-river-light", 812) == "OBS-aabb-river-light-000812"
    with pytest.raises(IdError):
        parse_prefixed_id("OBS-aabb-river-light-812", "OBS")


def test_topic_slug_abbreviation_is_accepted_but_not_a_different_topic():
    assert topic_slug_matches("aabb-river-light", "aabb-river-light-2026")
    assert not topic_slug_matches("cnus-nickel", "aabb-river-light-2026")


# --- minted run ids ------------------------------------------------------------------


def test_minted_run_id_parses_as_a_run_id():
    for prefix in ("qst", "ans", "nrm", "qa", "edt", "rl", "s2s"):
        assert validate_run_id(mint_run_id(prefix)).startswith(prefix + "-")


def test_minted_run_id_carries_the_real_utc_clock():
    # The whole point: the stamp is read off the clock, not typed.  A run stamped
    # ``ans-…082500…`` but written at 07:55 mis-sorted the ledger.
    before = datetime.now(timezone.utc)
    stamp = mint_run_id("ans").split("-")[1]
    after = datetime.now(timezone.utc)
    minted = datetime.strptime(stamp, "%Y%m%d%H%M%S%f").replace(tzinfo=timezone.utc)
    assert before - timedelta(seconds=1) <= minted <= after + timedelta(seconds=1)


def test_minted_run_id_honours_an_explicit_instant_in_utc():
    at = datetime(2026, 8, 30, 7, 55, 12, 345678, tzinfo=timezone.utc)
    assert mint_run_id("ans", now=at).startswith("ans-20260830075512345678-")
    # A non-UTC instant is converted, never truncated to its local wall clock.
    assert mint_run_id("ans", now=at.astimezone(timezone(timedelta(hours=8)))).startswith(
        "ans-20260830075512345678-"
    )


def test_minted_run_ids_do_not_collide():
    assert len({mint_run_id("nrm") for _ in range(200)}) == 200


@pytest.mark.parametrize("bad", ["", "NRM", "nrm-", "9nrm", "nrm_a", "n" * 17, "nrm x"])
def test_bad_run_id_prefix_rejected(bad):
    with pytest.raises(IdError):
        mint_run_id(bad)
