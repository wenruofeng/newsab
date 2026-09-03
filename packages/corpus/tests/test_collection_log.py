"""The collection log is the only artifact that answers "what would you have found if you
had searched differently?" (§3.3 S2), so its shape is enforced rather than trusted."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from newsab_corpus.collection_log import CollectionLogEntry, variant_coverage

AT = "2026-08-18T00:00:00Z"


def _entry(**kw):
    return CollectionLogEntry.model_validate({"at": AT, "group_id": "cn", **kw})


def test_query_must_carry_the_query_string():
    with pytest.raises(ValidationError):
        _entry(kind="query")


@pytest.mark.parametrize("kind", ["fetch_failure", "excluded"])
def test_failures_must_carry_a_reason(kind):
    with pytest.raises(ValidationError):
        _entry(kind=kind, url="https://example.com/a")


def test_source_added_records_how_the_outlet_entered_the_frame():
    """D19: the frame is open, so an addition has to say what surfaced it -- otherwise a
    source can silently enter the sample only because it happened to cover this topic."""
    entry = _entry(
        kind="source_added",
        source_id="yicai_cn",
        found_via="baidu_news query 国际学生在美居留期限新规",
        snapshot_id="sources-aabb-river-light-2026-02",
    )
    assert entry.source_id == "yicai_cn"

    with pytest.raises(ValidationError):
        _entry(kind="source_added", source_id="yicai_cn")  # no found_via
    with pytest.raises(ValidationError):
        _entry(kind="source_added", found_via="some query")  # no source_id


def test_corrections_are_new_entries_not_edits():
    """§3.2: records are immutable; a correction names the entry it supersedes."""
    entry = _entry(kind="note", corrects="note@2026-08-18T06:45:00Z", note="supersedes it")
    assert entry.corrects == "note@2026-08-18T06:45:00Z"


def test_variant_coverage_reports_unsearched_cells():
    entries = [_entry(kind="query", query="q1", term_variant="policy_name")]
    cov = variant_coverage(entries, {"cn": ["policy_name", "framing_tighten"]})
    assert cov["cn"] == {"searched": ["policy_name"], "missing": ["framing_tighten"]}


def test_fetch_failure_must_survive_the_browser_layer():
    """An HTTP refusal is a transport artifact, not the publisher's answer about who may
    read the page (fetch-extract.md §1.3). Recording one as a block manufactures an
    attention gap, so the model refuses a failure that has not been retried in a browser."""
    now = "2026-08-28T00:00:00Z"

    def _fail(**kw):
        return CollectionLogEntry.model_validate(
            {"at": now, "group_id": "de", "kind": "fetch_failure",
             "url": "https://example.de/a", "reason": "403 from the WAF", **kw}
        )

    assert _fail(layer="browser").layer == "browser"
    with pytest.raises(ValidationError):
        _fail(layer="http")
    with pytest.raises(ValidationError):
        _fail()


def test_logs_written_before_the_rule_are_not_retroactively_invalid():
    """Records are immutable (§3.2): a later rule does not rewrite earlier history."""
    entry = CollectionLogEntry.model_validate(
        {"at": AT, "group_id": "cn", "kind": "fetch_failure",
         "url": "https://example.cn/a", "reason": "paywall"}
    )
    assert entry.layer is None


def test_query_lines_must_record_what_they_staged():
    """The reconciliation reads a missing ``results_staged`` as 0, so an omitted count and
    a real zero are indistinguishable — which is how a round gets hollowed out while every
    line still validates (search-strategy.md §6). Zero must be written, not left out."""
    now = "2026-08-30T00:00:00Z"

    def _query(**kw):
        return CollectionLogEntry.model_validate(
            {"at": now, "group_id": "cn", "kind": "query", "query": "镍矿 出口", **kw}
        )

    assert _query(results_staged=0).results_staged == 0
    assert _query(results_staged=3).results_staged == 3
    with pytest.raises(ValidationError):
        _query()


def test_query_lines_written_before_the_rule_keep_their_silence():
    """Records are immutable (§3.2): a later rule does not invalidate earlier history."""
    entry = _entry(kind="query", query="镍矿 出口")
    assert entry.results_staged is None
