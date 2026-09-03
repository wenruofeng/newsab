"""Cost reporting: the arithmetic, the attribution, and its isolation from verification."""

from __future__ import annotations

import csv
import json
import pathlib

import pytest

from newsab_publish.builder import directory_fingerprint, write_closed_file
from newsab_publish.cost import (
    Coverage,
    Evidence,
    SessionUsage,
    Usage,
    UsageRow,
    build_report,
    claude_code_projects_dir,
    collapse,
    cost_dir,
    discover_claude_code_sessions,
    discover_codex_sessions,
    load_rates,
    read_usage_jsonl,
    read_codex_rollout,
    rebuild_index,
    topic_run_ids,
    write_report,
)
from newsab_schema.io import ArtifactError


def row(message_id, *, model="claude-opus-5", out=0, read=0, write=0, ttl=None, inp=0):
    raw = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read}
    if ttl:
        raw["cache_creation"] = {f"ephemeral_{ttl}_input_tokens": write}
    else:
        raw["cache_creation_input_tokens"] = write
    from newsab_publish.cost import _row_from_usage

    return _row_from_usage(message_id, model, "2026-08-29T07:00:00.000Z", raw)


# --- the arithmetic --------------------------------------------------------------------


def test_streaming_duplicates_are_collapsed_not_summed():
    """Three transcript rows for one response are one billed request, not three."""
    rows = [row("msg_a", out=3, read=1000, write=500) for _ in range(3)]
    collapsed = collapse(rows)
    assert len(collapsed) == 1
    assert collapsed[0].usage.cache_read == 1000
    assert collapsed[0].usage.output_tokens == 3


def test_collapse_keeps_the_largest_snapshot_not_the_first():
    """Early streaming snapshots report partial output; taking the first undercounts."""
    rows = [row("msg_a", out=2, read=1000), row("msg_a", out=9001, read=1000)]
    collapsed = collapse(rows)
    assert collapsed[0].usage.output_tokens == 9001


def test_ttl_split_is_read_from_the_record_and_only_assumed_when_absent():
    stated = row("msg_a", write=1000, ttl="1h")
    assert stated.usage.cache_write_1h == 1000 and stated.usage.cache_write_5m == 0
    silent = row("msg_b", write=1000)
    assert silent.usage.cache_write_5m == 1000 and silent.usage.cache_write_1h == 0


def test_each_token_class_is_priced_at_its_own_rate():
    rates = load_rates()
    # 1M of each class on Opus 5: 5 + 25 + 0.5 + 6.25 + 10 = 46.75
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read=1_000_000,
        cache_write_5m=1_000_000,
        cache_write_1h=1_000_000,
    )
    assert rates.price("claude-opus-5", usage) == pytest.approx(46.75)


def test_a_cache_read_is_not_priced_as_input():
    """The whole bill is cache reads; pricing them as input would be 10x wrong."""
    rates = load_rates()
    assert rates.price("claude-opus-5", Usage(cache_read=1_000_000)) == pytest.approx(0.5)


def test_an_unpriced_model_is_an_error_not_a_free_run():
    rates = load_rates()
    with pytest.raises(ArtifactError, match="no price for model"):
        rates.price("claude-from-the-future", Usage(output_tokens=10))


def test_a_model_alias_is_priced_as_its_canonical_name():
    rates = load_rates()
    assert rates.price("sonnet", Usage(output_tokens=1_000_000)) == pytest.approx(10.0)


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5.5", 35.5),
        ("gpt-5.6-sol", 24.4),
        ("gpt-5.6-terra", 14.2),
        ("gpt-5.6-luna", 1.42),
    ],
)
def test_observed_codex_models_use_official_api_list_prices(model, expected):
    usage = Usage(input_tokens=1_000_000, cache_read=1_000_000, output_tokens=1_000_000)
    assert load_rates().price(model, usage) == pytest.approx(expected)


def test_gpt_56_cache_writes_use_the_published_125_percent_rate():
    usage = Usage(cache_write_unknown=1_000_000)
    assert load_rates().price("gpt-5.6-sol", usage) == pytest.approx(5.0)


def test_openai_long_context_multiplier_is_per_request():
    usage = Usage(input_tokens=272_001, output_tokens=1_000_000)
    rates = load_rates()
    assert rates.price(
        "gpt-5.6-sol", usage, request_input_tokens=usage.context_tokens
    ) == pytest.approx(272_001 * 8 / 1_000_000 + 30.0)


def test_many_short_requests_are_not_mistaken_for_one_long_request():
    session = SessionUsage(
        session_id="codex",
        source="codex",
        harness="codex",
        provider="openai",
        rows=[
            UsageRow("a", "gpt-5.6-sol", None, Usage(input_tokens=200_000, requests=1)),
            UsageRow("b", "gpt-5.6-sol", None, Usage(input_tokens=200_000, requests=1)),
        ],
    )
    report = build_report("PUB-x", "tt-2026", [session], load_rates(), reader="test")
    assert report.total_usd == pytest.approx(1.6)


def test_overlapping_sessions_do_not_bill_their_minutes_twice():
    """A subagent pool runs *inside* its parent's span; summing would double the clock."""
    parent = SessionUsage(
        session_id="parent",
        source="p",
        rows=[row("a", out=1)],
        stamps=["2026-08-29T07:00:00Z", "2026-08-29T10:00:00Z"],
    )
    pool = SessionUsage(
        session_id="parent/subagents",
        source="p",
        subagent=True,
        rows=[row("b", model="claude-sonnet-5", out=1)],
        stamps=["2026-08-29T07:30:00Z", "2026-08-29T09:30:00Z"],
    )
    report = build_report("PUB-x-1", "topic-x", [parent, pool], load_rates(), reader="test")
    assert report.wall_clock_minutes == 180.0


# --- attribution -----------------------------------------------------------------------


def _transcript(path, *, body, model="claude-opus-5", tool=False):
    lines = [
        json.dumps(
            {
                "timestamp": "2026-08-29T07:00:00.000Z",
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "model": model,
                    "usage": {"input_tokens": 1, "output_tokens": 10, "cache_read_input_tokens": 0},
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": body}}
                    ]
                    if tool
                    else [],
                },
            }
        ),
        json.dumps({"timestamp": "2026-08-29T07:05:00.000Z", "type": "user", "note": body}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_session_that_only_discusses_the_topic_is_not_billed_to_it(tmp_path):
    """The failure this rule exists for: a follow-up task that names the topic 19 times."""
    projects = tmp_path / "projects"
    projects.mkdir()
    _transcript(projects / "worker.jsonl", body="editing topics/tt-2026/corpus by hand", tool=True)
    _transcript(projects / "talker.jsonl", body="tt-2026 " * 40)
    sessions = discover_claude_code_sessions(projects, "tt-2026", run_ids=set())
    verdicts = {s.session_id: s.included for s in sessions}
    assert verdicts == {"worker": True, "talker": False}


def test_naming_the_topics_own_run_ids_is_the_other_way_in(tmp_path):
    """A publish session touches site/, not topics/ — its evidence is the run ids."""
    projects = tmp_path / "projects"
    projects.mkdir()
    runs = {"s2s-20260829090914581829-8ef78199", "rl-20260829103256000000-67abdb5e"}
    _transcript(projects / "publisher.jsonl", body="tt-2026 " + " ".join(runs), tool=True)
    sessions = discover_claude_code_sessions(projects, "tt-2026", run_ids=runs)
    assert [s.included for s in sessions] == [True]
    assert "named 2 of the topic's run ids" in sessions[0].reason


def test_one_quoted_run_id_is_not_enough(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    runs = {"s2s-20260829090914581829-8ef78199", "rl-20260829103256000000-67abdb5e"}
    _transcript(projects / "reader.jsonl", body="tt-2026 s2s-20260829090914581829-8ef78199", tool=True)
    sessions = discover_claude_code_sessions(projects, "tt-2026", run_ids=runs)
    assert [s.included for s in sessions] == [False]


def test_the_operator_can_override_either_way_and_it_is_recorded(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    _transcript(projects / "worker.jsonl", body="topics/tt-2026 work", tool=True)
    _transcript(projects / "talker.jsonl", body="tt-2026 " * 40)
    sessions = discover_claude_code_sessions(
        projects,
        "tt-2026",
        run_ids=set(),
        include=["talker"],
        exclude=["worker"],
    )
    report = build_report("PUB-tt-2026-1", "tt-2026", sessions, load_rates(), reader="test")
    reasons = {row["session"]: row["reason"] for row in report.candidates}
    assert reasons == {
        "claude-code:talker": "included by operator",
        "claude-code:worker": "excluded by operator",
    }


def test_every_candidate_session_is_reported_including_the_rejected_ones(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    _transcript(projects / "worker.jsonl", body="topics/tt-2026 work", tool=True)
    _transcript(projects / "talker.jsonl", body="tt-2026 mentioned once")
    sessions = discover_claude_code_sessions(projects, "tt-2026", run_ids=set())
    report = build_report("PUB-tt-2026-1", "tt-2026", sessions, load_rates(), reader="test")
    assert {row["session"] for row in report.candidates} == {
        "claude-code:worker",
        "claude-code:talker",
    }
    assert [line.session_id for line in report.lines] == ["claude-code:worker"]


def test_claude_subagents_are_attributed_individually_not_as_a_parent_pool(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    _transcript(projects / "parent.jsonl", body="topics/tt-2026/root", tool=True)
    pool = projects / "parent" / "subagents"
    pool.mkdir(parents=True)
    _transcript(pool / "worker.jsonl", body="topics/tt-2026/worker", tool=True)
    _transcript(pool / "sibling.jsonl", body="topics/tt-2026 inherited only")
    sessions = discover_claude_code_sessions(projects, "tt-2026", run_ids=set())
    verdicts = {session.session_id: session.included for session in sessions}
    assert verdicts == {
        "parent": True,
        "parent/worker": True,
        "parent/sibling": False,
    }
    worker = next(session for session in sessions if session.session_id == "parent/worker")
    assert worker.parent_key == "claude-code:parent"


def test_local_notices_are_dropped_not_priced(tmp_path):
    """A dropped connection or a session-limit banner is written as an assistant message
    with a zero usage block; it was never an API call."""
    projects = tmp_path / "projects"
    projects.mkdir()
    path = projects / "s.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                {
                    "timestamp": "2026-08-29T07:00:00Z",
                    "message": {
                        "id": "msg_real",
                        "model": "claude-opus-5",
                        "usage": {"output_tokens": 10},
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Read",
                                "input": {"file_path": "topics/tt-2026/run.json"},
                            }
                        ],
                    },
                },
                {
                    "timestamp": "2026-08-29T07:01:00Z",
                    "message": {
                        "id": "msg_notice",
                        "model": "<synthetic>",
                        "usage": {"output_tokens": 0},
                    },
                },
                {"timestamp": "2026-08-29T07:02:00Z", "type": "user", "note": "topics/tt-2026"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    sessions = discover_claude_code_sessions(projects, "tt-2026", run_ids=set())
    report = build_report("PUB-tt-2026-1", "tt-2026", sessions, load_rates(), reader="test")
    assert [line.usage.requests for line in report.lines] == [1]


def test_a_missing_transcript_directory_refuses_rather_than_reporting_zero(tmp_path):
    with pytest.raises(ArtifactError, match="no transcript directory"):
        discover_claude_code_sessions(tmp_path / "nope", "tt-2026", run_ids=set())


def test_transcript_paths_are_recorded_home_relative(tmp_path, monkeypatch):
    """Reports are versioned; an absolute home path is one machine's noise in every clone."""
    from newsab_publish.cost import portable

    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: pathlib.Path("/home/u")))
    assert portable("/home/u/.claude/projects/x.jsonl") == "~/.claude/projects/x.jsonl"
    assert portable("/srv/elsewhere.jsonl") == "/srv/elsewhere.jsonl"


def test_the_claude_code_slug_dashes_every_non_alphanumeric(tmp_path):
    found = claude_code_projects_dir("/home/u/news_ab", home=tmp_path)
    assert found.name == "-home-u-news-ab"


def test_topic_run_ids_are_read_out_of_the_topics_own_artifacts(tmp_path):
    topic = tmp_path / "tt-2026" / "corpus"
    topic.mkdir(parents=True)
    (topic / "run.json").write_text(
        json.dumps({"run_id": "s2s-20260829090914581829-8ef78199"}), encoding="utf-8"
    )
    assert topic_run_ids(tmp_path, "tt-2026") == {"s2s-20260829090914581829-8ef78199"}


# --- harness neutrality ----------------------------------------------------------------


def _codex_record(timestamp, record_type, payload, ordinal=0):
    return {
        "timestamp": timestamp,
        "ordinal": ordinal,
        "type": record_type,
        "payload": payload,
    }


def _codex_rollout(
    path,
    *,
    session="same",
    parent=None,
    tool_text="topics/tt-2026/run.json",
    model="gpt-5.6-sol",
):
    totals_1 = {
        "input_tokens": 60,
        "cached_input_tokens": 40,
        "cache_write_input_tokens": 0,
        "output_tokens": 10,
        "reasoning_output_tokens": 3,
        "total_tokens": 70,
    }
    last_2 = {
        "input_tokens": 40,
        "cached_input_tokens": 30,
        "cache_write_input_tokens": 0,
        "output_tokens": 10,
        "reasoning_output_tokens": 5,
        "total_tokens": 50,
    }
    totals_2 = {
        key: totals_1[key] + last_2[key]
        for key in totals_1
    }
    meta = {
        "id": session,
        "session_id": parent or session,
        "cwd": str(path.parents[4]),
        "model_provider": "openai",
        "cli_version": "0.fixture",
    }
    if parent:
        meta["parent_thread_id"] = parent
    records = [
        _codex_record("2026-08-29T07:00:00Z", "session_meta", meta, 0),
        _codex_record("2026-08-29T07:00:01Z", "turn_context", {"model": model}, 1),
        _codex_record(
            "2026-08-29T07:00:02Z",
            "response_item",
            {"type": "custom_tool_call", "name": "exec", "input": tool_text},
            2,
        ),
        _codex_record(
            "2026-08-29T07:00:03Z",
            "event_msg",
            {"type": "token_count", "info": {"last_token_usage": totals_1, "total_token_usage": totals_1}},
            3,
        ),
        _codex_record(
            "2026-08-29T07:05:00Z",
            "event_msg",
            {"type": "token_count", "info": {"last_token_usage": last_2, "total_token_usage": totals_2}},
            4,
        ),
        # Rate-limit metadata can cause Codex to repeat the same cumulative + last
        # snapshot without another model call.
        _codex_record(
            "2026-08-29T07:05:01Z",
            "event_msg",
            {"type": "token_count", "info": {"last_token_usage": last_2, "total_token_usage": totals_2}},
            5,
        ),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def test_codex_cached_and_reasoning_are_subsets_not_extra_tokens(tmp_path):
    path = tmp_path / "repo" / ".codex" / "sessions" / "2026" / "08" / "29" / "rollout-a.jsonl"
    _codex_rollout(path)
    session, _ = read_codex_rollout(path)
    usage = Usage()
    for item in session.rows:
        usage.add(item.usage)
    assert usage.input_tokens == 30
    assert usage.cache_read == 70
    assert usage.context_tokens == 100
    assert usage.output_tokens == 20
    assert usage.reasoning_output_tokens == 8
    assert usage.requests == 2  # cumulative snapshots were not summed
    assert session.usage_complete is True


def test_codex_discovers_topic_working_parent_and_child_and_restores_namespaced_ids(tmp_path):
    repo = tmp_path / "repo"
    root = tmp_path / "sessions"
    parent_path = root / "2026" / "08" / "29" / "rollout-parent.jsonl"
    child_path = root / "2026" / "08" / "29" / "rollout-child.jsonl"
    _codex_rollout(parent_path, session="same")
    _codex_rollout(child_path, session="child", parent="same")
    # Fixture helper derives cwd from its layout; replace it with the requested repo.
    for path in (parent_path, child_path):
        text = path.read_text(encoding="utf-8").replace(str(path.parents[4]), str(repo))
        path.write_text(text, encoding="utf-8")
    sessions = discover_codex_sessions(root, repo, "tt-2026", run_ids=set())
    assert {session.key for session in sessions} == {"codex:same", "codex:child"}
    child = next(session for session in sessions if session.session_id == "child")
    assert child.parent_key == "codex:same"
    assert child.included is True


def test_codex_parent_relation_alone_does_not_pull_in_an_unrelated_sibling(tmp_path):
    repo = tmp_path / "repo"
    root = tmp_path / "sessions"
    parent_path = root / "2026" / "08" / "29" / "rollout-parent.jsonl"
    sibling_path = root / "2026" / "08" / "29" / "rollout-sibling.jsonl"
    _codex_rollout(parent_path, session="parent")
    _codex_rollout(
        sibling_path,
        session="sibling",
        parent="parent",
        tool_text="unrelated work that only inherited mention tt-2026",
    )
    for path in (parent_path, sibling_path):
        text = path.read_text(encoding="utf-8").replace(str(path.parents[4]), str(repo))
        path.write_text(text, encoding="utf-8")
    sessions = discover_codex_sessions(root, repo, "tt-2026", run_ids=set())
    sibling = next(session for session in sessions if session.session_id == "sibling")
    assert sibling.parent_key == "codex:parent"
    assert sibling.included is False


def test_codex_user_or_inherited_text_is_not_artifact_access(tmp_path):
    repo = tmp_path / "repo"
    root = tmp_path / "sessions"
    path = root / "2026" / "08" / "29" / "rollout-talk.jsonl"
    _codex_rollout(path, session="talk", tool_text="no topic")
    text = path.read_text(encoding="utf-8").replace(str(path.parents[4]), str(repo))
    records = [json.loads(line) for line in text.splitlines()]
    records.insert(
        2,
        _codex_record(
            "2026-08-29T07:00:01Z",
            "response_item",
            {"type": "message", "role": "user", "content": "topics/tt-2026/inherited"},
            2,
        ),
    )
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    sessions = discover_codex_sessions(root, repo, "tt-2026", run_ids=set())
    assert len(sessions) == 1
    assert sessions[0].included is False
    assert sessions[0].evidence.transcript_path_mentions > 0
    assert sessions[0].evidence.path_mentions == 0


def test_same_raw_session_id_from_two_harnesses_does_not_collide():
    claude = SessionUsage(
        session_id="same",
        source="claude",
        harness="claude-code",
        provider="anthropic",
        rows=[row("claude-m", out=1)],
    )
    codex = SessionUsage(
        session_id="same",
        source="codex",
        harness="codex",
        provider="openai",
        rows=[UsageRow("codex-m", "gpt-5.6-sol", None, Usage(output_tokens=1, requests=1))],
    )
    report = build_report("PUB-x", "tt-2026", [claude, codex], load_rates(), reader="combined")
    assert {line.session_id for line in report.lines} == {"claude-code:same", "codex:same"}
    assert report.pricing_status == "complete"
    assert report.total_usd is not None
    assert report.priced_usd > 0


def test_combined_harness_wall_clock_is_a_union_and_all_tokens_are_kept():
    sessions = [
        SessionUsage(
            session_id="c-root",
            source="c",
            harness="claude-code",
            provider="anthropic",
            rows=[row("c1", out=1)],
            stamps=["2026-08-29T07:00:00Z", "2026-08-29T10:00:00Z"],
        ),
        SessionUsage(
            session_id="c-sub",
            source="c",
            harness="claude-code",
            provider="anthropic",
            parent_session_id="c-root",
            subagent=True,
            rows=[row("c2", out=1)],
            stamps=["2026-08-29T08:00:00Z", "2026-08-29T09:00:00Z"],
        ),
        SessionUsage(
            session_id="x-root",
            source="x",
            harness="codex",
            provider="openai",
            rows=[UsageRow("x1", "gpt-5.6-sol", None, Usage(output_tokens=1, requests=1))],
            stamps=["2026-08-29T09:00:00Z", "2026-08-29T11:00:00Z"],
        ),
        SessionUsage(
            session_id="x-sub",
            source="x",
            harness="codex",
            provider="openai",
            parent_session_id="x-root",
            subagent=True,
            rows=[UsageRow("x2", "gpt-5.6-sol", None, Usage(output_tokens=1, requests=1))],
            stamps=["2026-08-29T09:30:00Z", "2026-08-29T10:30:00Z"],
        ),
    ]
    report = build_report("PUB-x", "tt-2026", sessions, load_rates(), reader="combined")
    assert report.wall_clock_minutes == 240.0
    assert sum(usage.output_tokens for usage in report.totals_by_model.values()) == 4
    assert report.totals_by_harness["claude-code"].wall_clock_minutes == 180.0
    assert report.totals_by_harness["codex"].wall_clock_minutes == 120.0
    assert report.totals_by_harness["claude-code"].usage.total_tokens == 2
    assert report.totals_by_harness["codex"].usage.total_tokens == 2
    assert report.total_usd is not None


def test_any_harness_can_feed_the_same_report_through_usage_jsonl(tmp_path):
    path = tmp_path / "usage.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                    {
                        "topic_id": "tt-2026",
                        "session": "codex-1",
                    "message_id": "m1",
                    "model": "claude-sonnet-5",
                    "timestamp": "2026-08-29T07:00:00Z",
                    "output_tokens": 1_000_000,
                },
                    {
                        "topic_id": "tt-2026",
                        "session": "codex-1",
                    "message_id": "m1",
                    "model": "claude-sonnet-5",
                    "timestamp": "2026-08-29T07:00:01Z",
                    "output_tokens": 1_000_000,
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    sessions = read_usage_jsonl(path, "tt-2026")
    report = build_report("PUB-x-1", "tt-2026", sessions, load_rates(), reader="test")
    # One message id written twice is still one response: $10, not $20.
    assert report.total_usd == pytest.approx(10.0)


def test_neutral_usage_requires_an_explicit_topic_binding(tmp_path):
    path = tmp_path / "usage.jsonl"
    path.write_text(json.dumps({"session": "s", "message_id": "m"}) + "\n", encoding="utf-8")
    with pytest.raises(ArtifactError, match="topic_id/work-span"):
        read_usage_jsonl(path, "tt-2026")


def test_a_usage_record_without_a_session_is_refused(tmp_path):
    path = tmp_path / "usage.jsonl"
    path.write_text(
        json.dumps({"topic_id": "tt-2026", "message_id": "m1", "model": "claude-opus-5"})
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ArtifactError, match="no session id"):
        read_usage_jsonl(path)


# --- isolation from verification -------------------------------------------------------


def _report(publication_id="PUB-tt-2026-abcdef123456", topic_id="tt-2026"):
    session = SessionUsage(
        session_id="s1",
        source="s1.jsonl",
        harness="claude-code",
        provider="anthropic",
        evidence=Evidence(mentions=9, path_mentions=9, run_ids=0),
        rows=[row("m1", out=100)],
        stamps=["2026-08-29T07:00:00Z", "2026-08-29T07:10:00Z"],
    )
    return build_report(publication_id, topic_id, [session], load_rates(), reader="test")


def test_a_cost_report_changes_no_byte_the_verifier_hashes(tmp_path):
    """The user's question: can this be backfilled without disturbing any review?

    ``verify_site`` fingerprints the production tree and reads four named files out of
    ``site/audit/<publication_id>/``.  A cost report is written outside both.
    """
    site = tmp_path / "site"
    production = site / "public"
    write_closed_file(production, "zh-CN/index.html", b"home\n")
    before = directory_fingerprint(production)

    write_report(site, _report())
    rebuild_index(site)

    assert directory_fingerprint(production) == before
    assert cost_dir(site) not in production.parents
    # The four archived render inputs verify_candidate reads live one level up, per
    # publication; nothing the cost report writes can shadow one of them.
    verifier_inputs = {
        "topics_by_article.json",
        "site_metadata.json",
        "theme_tokens.json",
        "source_registry.yaml",
    }
    written = {path.name for path in cost_dir(site).iterdir()}
    assert not (written & verifier_inputs)
    assert all(path.parent.name == "cost" for path in cost_dir(site).iterdir())


def test_reports_are_recomputable_in_place(tmp_path):
    """Backfill and re-run must overwrite cleanly — this is not an append-only artifact."""
    site = tmp_path / "site"
    write_report(site, _report())
    csv_path, json_path = write_report(site, _report())
    assert csv_path.read_text(encoding="utf-8").count("\n") == 2  # header + one session
    assert json.loads(json_path.read_text(encoding="utf-8"))["topic_id"] == "tt-2026"


def test_the_index_carries_the_totals_the_per_publication_csv_deliberately_omits(tmp_path):
    site = tmp_path / "site"
    write_report(site, _report("PUB-aa-2026-000000000001", "aa-2026"))
    write_report(site, _report("PUB-bb-2026-000000000002", "bb-2026"))
    index = rebuild_index(site)
    lines = index.read_text(encoding="utf-8").strip().split("\n")
    assert lines[0].startswith("topic_id,as_of_publication_id")
    assert len(lines) == 3
    with index.open(encoding="utf-8", newline="") as handle:
        first = next(csv.DictReader(handle))
    assert first["claude_total_tokens"] == "100"
    assert first["codex_total_tokens"] == "0"
    assert first["total_tokens"] == "100"
    assert first["claude_usd"] == first["total_usd"]
    # A per-publication CSV has no TOTAL row, so summing its rows is always correct.
    body = (cost_dir(site) / "aa-2026.csv").read_text(encoding="utf-8")
    assert "TOTAL" not in body


def test_a_republished_topic_keeps_one_history_not_two(tmp_path):
    """Eight of the first nine topics were superseded; keying by publication would have
    reported the same sessions twice and made the index unsummable."""
    site = tmp_path / "site"
    write_report(site, _report("PUB-tt-2026-000000000001", "tt-2026"))
    write_report(site, _report("PUB-tt-2026-000000000002", "tt-2026"))
    rebuild_index(site)
    rows = (cost_dir(site) / "index.csv").read_text(encoding="utf-8").strip().split("\n")
    assert len(rows) == 2  # header + one topic
    assert rows[1].startswith("tt-2026,PUB-tt-2026-000000000002")


def test_every_report_pins_the_prices_it_was_computed_with(tmp_path):
    """List prices move; a report that does not say which table it used cannot be reread."""
    payload = _report().to_json()
    assert payload["rates_version"] == load_rates().version
    assert payload["rates_fingerprint"] == load_rates().fingerprint
    assert "not an invoice" in payload["pricing_note"]
