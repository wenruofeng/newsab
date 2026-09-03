"""What a web-gate run is allowed to skip.

The rule these tests exist to hold: **bytes a human has never seen pass are always
checked.**  Sampling only ever thins pages that already passed and went stale because the
chrome or the gate's own code moved — which is exactly the case where a byte-level cache
buys nothing and typography coverage is what matters.
"""

from __future__ import annotations

import json

import pytest

from newsab_publish.gate_selection import (
    PageKey,
    VerifiedCache,
    build_keys,
    chrome_fingerprint,
    gate_fingerprint,
    locale_stratum,
    page_shape,
    plan,
)

GATE = "g" * 64
CHROME = "c" * 64
OTHER_CHROME = "d" * 64


def _key(url: str, sha: str = "sha", suite: str = "topic") -> PageKey:
    locale = url.strip("/").split("/")[0]
    return PageKey(
        url=url, suite=suite, page_sha=sha, stratum=locale_stratum(locale), shape="shape-a"
    )


def _cache(tmp_path, enabled: bool = True) -> VerifiedCache:
    return VerifiedCache(tmp_path / "verified.json", enabled=enabled)


# --------------------------------------------------------------------------------------
# the non-negotiable: new bytes are never sampled away
# --------------------------------------------------------------------------------------


def test_bytes_never_seen_before_are_always_run(tmp_path):
    keys = [_key(f"/{locale}/topics/x/", sha=f"sha-{locale}") for locale in
            ("en", "es", "fr", "ar", "zh-CN", "ja", "ko", "hi", "ru")]
    selection = plan(keys, _cache(tmp_path), gate=GATE, chrome=CHROME)
    assert selection.urls == sorted(key.url for key in keys)
    assert selection.sampled_out == []


def test_a_candidate_bundles_pages_are_all_new_so_all_run(tmp_path):
    """Touchpoint two gates a freshly rendered bundle: nothing about it can be cached."""
    cache = _cache(tmp_path)
    old = _key("/en/topics/x/", sha="published-bytes")
    cache.record(old.cache_key(GATE, CHROME), old)
    candidate = [_key(f"/{locale}/topics/x/", sha=f"candidate-{locale}") for locale in
                 ("en", "zh-CN", "ar")]
    selection = plan(candidate, cache, gate=GATE, chrome=CHROME)
    assert len(selection.run) == 3
    assert selection.cached == [] and selection.sampled_out == []


# --------------------------------------------------------------------------------------
# unchanged bytes under unchanged chrome
# --------------------------------------------------------------------------------------


def test_the_same_bytes_under_the_same_chrome_and_gate_are_skipped(tmp_path):
    cache = _cache(tmp_path)
    keys = [_key("/en/topics/x/", sha="one"), _key("/ar/topics/x/", sha="two")]
    for key in keys:
        cache.record(key.cache_key(GATE, CHROME), key)
    selection = plan(keys, cache, gate=GATE, chrome=CHROME)
    assert selection.run == []
    assert len(selection.cached) == 2


def test_a_gate_code_change_invalidates_every_verdict(tmp_path):
    cache = _cache(tmp_path)
    keys = [_key("/en/topics/x/", sha="one")]
    cache.record(keys[0].cache_key(GATE, CHROME), keys[0])
    selection = plan(keys, cache, gate="h" * 64, chrome=CHROME)
    assert selection.cached == []
    assert len(selection.run) == 1


def test_a_disabled_cache_runs_everything(tmp_path):
    cache = _cache(tmp_path)
    keys = [_key("/en/topics/x/", sha="one")]
    cache.record(keys[0].cache_key(GATE, CHROME), keys[0])
    cache.save()
    off = _cache(tmp_path, enabled=False)
    assert plan(keys, off, gate=GATE, chrome=CHROME).run == keys


# --------------------------------------------------------------------------------------
# stale bytes: sample across typography strata and page shapes
# --------------------------------------------------------------------------------------


def _nine_locales(cache, sha_prefix="v1"):
    keys = []
    for locale in ("en", "es", "fr", "ar", "zh-CN", "ja", "ko", "hi", "ru"):
        for topic in ("alpha", "beta", "gamma"):
            key = _key(f"/{locale}/topics/{topic}/", sha=f"{sha_prefix}-{locale}-{topic}")
            cache.record(key.cache_key(GATE, CHROME), key)
            keys.append(key)
    return keys


def test_a_chrome_change_samples_one_page_per_typography_stratum(tmp_path):
    cache = _cache(tmp_path)
    keys = _nine_locales(cache)
    selection = plan(keys, cache, gate=GATE, chrome=OTHER_CHROME)
    assert len(keys) == 27
    # One page shape here, so one page per stratum: rtl, cjk-unspaced, hangul, indic,
    # cyrillic-long, latin.
    assert len(selection.run) == 6
    assert len(selection.sampled_out) == 21
    assert {key.stratum for key in selection.run} == {
        "rtl", "cjk-unspaced", "hangul", "indic", "cyrillic-long", "latin"
    }


def test_every_stratum_present_in_the_tree_is_represented(tmp_path):
    cache = _cache(tmp_path)
    keys = _nine_locales(cache)
    covered = {key.stratum for key in plan(keys, cache, gate=GATE, chrome=OTHER_CHROME).run}
    assert covered == {key.stratum for key in keys}


def test_two_page_shapes_are_sampled_separately(tmp_path):
    cache = _cache(tmp_path)
    keys = []
    for shape in ("shape-a", "shape-b"):
        for locale in ("en", "ar"):
            key = PageKey(
                url=f"/{locale}/topics/{shape}/",
                suite="topic",
                page_sha=f"{shape}-{locale}",
                stratum=locale_stratum(locale),
                shape=shape,
            )
            cache.record(key.cache_key(GATE, CHROME), key)
            keys.append(key)
    selection = plan(keys, cache, gate=GATE, chrome=OTHER_CHROME)
    assert len(selection.run) == 4
    assert {(key.shape, key.stratum) for key in selection.run} == {
        ("shape-a", "latin"), ("shape-a", "rtl"), ("shape-b", "latin"), ("shape-b", "rtl")
    }


def test_the_representative_rotates_with_the_chrome_fingerprint(tmp_path):
    """Two chrome revisions in a row must not keep re-testing the same page."""
    cache = _cache(tmp_path)
    keys = _nine_locales(cache)
    picked = set()
    for chrome in ("a" * 64, "b" * 64, "e" * 64, "f" * 64):
        picked |= {key.url for key in plan(keys, cache, gate=GATE, chrome=chrome).run}
    latin = {url for url in picked if url.startswith(("/en/", "/es/", "/fr/"))}
    assert len(latin) > 1


def test_the_same_chrome_always_picks_the_same_pages(tmp_path):
    cache = _cache(tmp_path)
    keys = _nine_locales(cache)
    first = plan(keys, cache, gate=GATE, chrome=OTHER_CHROME).urls
    second = plan(keys, cache, gate=GATE, chrome=OTHER_CHROME).urls
    assert first == second


def test_sample_size_widens_the_stratum(tmp_path):
    cache = _cache(tmp_path)
    keys = _nine_locales(cache)
    selection = plan(keys, cache, gate=GATE, chrome=OTHER_CHROME, per_stratum=2)
    assert len(selection.run) == 12


def test_full_checks_everything_including_cached_pages(tmp_path):
    cache = _cache(tmp_path)
    keys = _nine_locales(cache)
    selection = plan(keys, cache, gate=GATE, chrome=CHROME, full=True)
    assert len(selection.run) == len(keys)
    assert selection.cached == [] and selection.sampled_out == []


def test_an_unclassified_language_gets_a_stratum_of_its_own(tmp_path):
    """A new script must never be folded into an existing stratum and skipped."""
    cache = _cache(tmp_path)
    keys = []
    for locale in ("en", "th"):
        key = _key(f"/{locale}/topics/x/", sha=f"v1-{locale}")
        cache.record(key.cache_key(GATE, CHROME), key)
        keys.append(key)
    selection = plan(keys, cache, gate=GATE, chrome=OTHER_CHROME)
    assert {key.url for key in selection.run} == {"/en/topics/x/", "/th/topics/x/"}
    assert locale_stratum("th") == "unclassified:th"


# --------------------------------------------------------------------------------------
# the fingerprints the whole scheme rests on
# --------------------------------------------------------------------------------------


def test_the_gate_fingerprint_is_stable_within_a_checkout():
    """It is derived from the package source, so it moves only when an assertion does."""
    first = gate_fingerprint()
    assert first == gate_fingerprint()
    assert len(first) == 64


def test_the_chrome_fingerprint_prefers_deployed_bytes_over_the_overlay(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "site.css").write_text("deployed", encoding="utf-8")
    overlay = {"assets/site.css": b"in-memory", "assets/site.js": b"script"}
    deployed = chrome_fingerprint(tmp_path, overlay)
    (tmp_path / "assets" / "site.css").write_text("changed", encoding="utf-8")
    assert chrome_fingerprint(tmp_path, overlay) != deployed


def test_a_candidate_root_with_no_chrome_on_disk_uses_the_overlay(tmp_path):
    overlay = {"assets/site.css": b"in-memory"}
    assert chrome_fingerprint(tmp_path, overlay) == chrome_fingerprint(tmp_path, overlay)
    assert chrome_fingerprint(tmp_path, {"assets/site.css": b"other"}) != chrome_fingerprint(
        tmp_path, overlay
    )


# --------------------------------------------------------------------------------------
# the on-disk record
# --------------------------------------------------------------------------------------


def test_the_cache_round_trips_and_survives_a_corrupt_file(tmp_path):
    cache = _cache(tmp_path)
    key = _key("/en/topics/x/")
    cache.record(key.cache_key(GATE, CHROME), key)
    cache.save()
    assert _cache(tmp_path).holds(key.cache_key(GATE, CHROME))
    (tmp_path / "verified.json").write_text("{not json", encoding="utf-8")
    assert not _cache(tmp_path).holds(key.cache_key(GATE, CHROME))


def test_a_cache_written_by_an_older_format_is_ignored(tmp_path):
    (tmp_path / "verified.json").write_text(
        json.dumps({"version": 0, "entries": {"k": {}}}), encoding="utf-8"
    )
    assert _cache(tmp_path).entries == {}


def test_page_shape_reads_furniture_not_content():
    a = '<div data-kindpanel="one"><span data-share-angle="q1" data-tip="x"></span></div>'
    b = '<div data-kindpanel="one"><span data-share-angle="q9" data-tip="y"></span></div>'
    assert page_shape(a) == page_shape(b)
    assert page_shape(a) != page_shape(a + '<div data-kindpanel="two"></div>')


def test_build_keys_reads_the_page_bytes_and_its_locale(tmp_path):
    target = tmp_path / "ar" / "topics" / "x"
    target.mkdir(parents=True)
    target.joinpath("index.html").write_text('<html data-tip="1">', encoding="utf-8")
    (key,) = build_keys(tmp_path, ["/ar/topics/x/"], "topic")
    assert key.stratum == "rtl" and key.suite == "topic" and len(key.page_sha) == 64


@pytest.mark.parametrize(
    "locale,stratum",
    [("ar", "rtl"), ("zh-CN", "cjk-unspaced"), ("ja", "cjk-unspaced"), ("ko", "hangul"),
     ("hi", "indic"), ("ru", "cyrillic-long"), ("en", "latin"), ("fr", "latin")],
)
def test_the_shipped_locales_land_in_the_intended_strata(locale, stratum):
    assert locale_stratum(locale) == stratum
