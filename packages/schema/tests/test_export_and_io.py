"""Generated artifacts stay in sync, and records survive a disk round-trip."""

import json
from datetime import datetime, timezone

from conftest import make_article, make_observation, provenance
from newsab_schema import LangText, Observation, Provenance, TopicPaths
from newsab_schema.artifacts import (
    append_correction,
    append_manifest,
    artifact_hashes,
    verify_manifest,
)
from newsab_schema.cli import main
from newsab_schema.export import check_in_sync
from newsab_schema.io import load_articles, read_jsonl, write_articles, write_jsonl
from newsab_schema.models.manifest import (
    ArtifactReference,
    CorrectionMapping,
    ManifestEntry,
    content_digest,
    file_digest,
)


def test_dist_is_not_stale():
    stale = check_in_sync()
    assert not stale, (
        f"dist/ is out of date: {stale}. Run `python -m newsab_schema export` — a stale "
        "dist/ serves an old vocabulary to every non-Python consumer."
    )


def test_observation_round_trips_through_jsonl(tmp_path):
    original = [make_observation(observation_id=f"OBS-aabb-river-light-{i:06d}") for i in (1, 2)]
    path = write_jsonl(tmp_path / "observations.jsonl", original)
    assert read_jsonl(path, Observation) == original


def test_article_round_trips_and_keeps_sentence_ids(tmp_path):
    article = make_article()
    write_articles(tmp_path, [article])
    (loaded,) = load_articles(tmp_path)
    assert loaded == article
    assert loaded.sentence_ids() == [
        "CN_001:P00:S01",
        "CN_001:P01:S01",
        "CN_001:P01:S02",
        "CN_001:P02:S01",
    ]
    assert loaded.sentence_text("CN_001:P00:S01") == article.title


def test_article_rejects_cross_group_cluster_id():
    import pytest
    from pydantic import ValidationError

    payload = make_article().model_dump(mode="json")
    payload["reporting_cluster_id"] = "RC-US-001"
    from newsab_schema.models.corpus import Article

    with pytest.raises(ValidationError, match="does not match article_id group"):
        Article.model_validate(payload)


def test_serialisation_is_byte_stable():
    """The artifact hash is part of the audit trail, so the bytes must not wobble."""
    from newsab_schema.io import dump_record

    obs = make_observation()
    assert dump_record(obs) == dump_record(Observation.model_validate_json(dump_record(obs)))


def test_topic_paths_know_what_must_never_be_published(tmp_path):
    paths = TopicPaths.for_topic(tmp_path, "aabb-river-light-2026").ensure()
    assert paths.is_private(paths.article_file("CN_a1f39c02"))
    versioned_article = paths.stage_run_dir(
        "corpus", "s2s-202608171200-aabbccdd"
    ) / "articles" / "CN_001.json"
    assert paths.is_private(versioned_article)
    assert paths.is_private(paths.corpus_dir / "staging" / "cn-0001.yaml")
    assert paths.is_private(paths.gold_worksheet)
    assert not paths.is_private(paths.gold_standard)
    assert not paths.is_private(paths.observations)
    assert not paths.is_private(paths.corpus_index)


def test_manifest_entry_requires_an_explanation_when_it_produced_nothing():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="escalations"):
        ManifestEntry(
            skill_id="s4-annotate",
            skill_version="0.1.0",
            run_id="s4-202608171200-0123abcd",
            topic_id="aabb-river-light-2026",
            timestamp=datetime(2026, 8, 17, tzinfo=timezone.utc),
        )


def test_content_digest_is_order_independent():
    assert content_digest({"a": 1, "b": 2}) == content_digest({"b": 2, "a": 1})


def test_deterministic_stages_record_no_model():
    assert provenance("A1-0.1.0", None).deterministic


def _manifest_entry(paths, run_id, output, *, stage="observations"):
    from newsab_schema.artifacts import run_set_hash

    return ManifestEntry(
        skill_id="fixture",
        skill_version="0.2.0",
        run_id=run_id,
        topic_id=paths.topic_id,
        stage=stage,
        output_set_hash=run_set_hash(paths, stage, run_id),
        output_hashes=artifact_hashes(paths, [output]),
        timestamp=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )


def test_manifest_append_activates_version_and_refuses_reuse(tmp_path):
    import pytest
    from newsab_schema.io import ArtifactError

    paths = TopicPaths.for_topic(tmp_path, "aabb-river-light-2026").ensure()
    run_id = "s4-202608171200-aabbccdd"
    run_dir = paths.stage_run_dir("observations", run_id)
    run_dir.mkdir(parents=True)
    output = run_dir / "observations.jsonl"
    output.write_text('{"observation_id":"OBS-aabb-river-light-000001"}\n', encoding="utf-8")
    entry = _manifest_entry(paths, run_id, output)

    append_manifest(paths, entry, activate_stage="observations")
    assert paths.active_run_id("observations") == run_id
    assert paths.observations == output
    assert verify_manifest(paths) == []
    with pytest.raises(ArtifactError, match="duplicate manifest run_id"):
        append_manifest(paths, entry, activate_stage="observations")

    # Verification re-derives the run's content-set fingerprint (R-4) rather than checking
    # bytes at a path, so tampering inside the run directory is still caught — while a
    # legitimately extended corpus or source registry no longer looks like tampering.
    output.write_text("tampered\n", encoding="utf-8")
    assert any("output set changed" in error for error in verify_manifest(paths))


def test_hash_only_members_complete_an_absent_run_file(tmp_path):
    """A submission archive ships a run without its rendered bytes.

    The pin still has to cover the run's whole declared set, so the recorded hash of an
    absent member stands in for it — and only for a member that is genuinely absent.
    """
    import pytest
    from newsab_schema.artifacts import manifest_entry_fingerprint
    from newsab_schema.io import ArtifactError

    paths = TopicPaths.for_topic(tmp_path, "aabb-river-light-2026").ensure()
    run_id = "s4-202608171200-aabbccdd"
    run_dir = paths.stage_run_dir("observations", run_id)
    run_dir.mkdir(parents=True)
    output = run_dir / "observations.jsonl"
    output.write_text('{"observation_id":"OBS-aabb-river-light-000001"}\n', encoding="utf-8")
    rendered = run_dir / "preview.en.html"
    rendered.write_text("<p>rendered</p>", encoding="utf-8")
    entry = _manifest_entry(paths, run_id, output)
    key = f"observations/versions/{run_id}/preview.en.html"
    digest = artifact_hashes(paths, [rendered])[key]

    # With the bytes still here the overlay is a contradiction, not a convenience.
    with pytest.raises(ArtifactError, match="both on disk and declared hash-only"):
        manifest_entry_fingerprint(paths, entry, hash_only={key: digest})

    rendered.unlink()
    with pytest.raises(ArtifactError, match="fingerprints as"):
        manifest_entry_fingerprint(paths, entry)
    assert manifest_entry_fingerprint(paths, entry, hash_only={key: digest}) == entry.output_set_hash

    # A wrong hash cannot pass, and an overlay naming another run leaves this one alone.
    with pytest.raises(ArtifactError, match="fingerprints as"):
        manifest_entry_fingerprint(paths, entry, hash_only={key: "sha256:" + "0" * 64})
    with pytest.raises(ArtifactError, match="fingerprints as"):
        manifest_entry_fingerprint(
            paths, entry, hash_only={"observations/versions/other/preview.en.html": digest}
        )


def test_deactivate_stage_cli_retires_pointer_but_keeps_run(tmp_path):
    paths = TopicPaths.for_topic(tmp_path, "aabb-river-light-2026").ensure()
    run_id = "s4-202608171200-aabbccdd"
    run_dir = paths.stage_run_dir("observations", run_id)
    run_dir.mkdir(parents=True)
    output = run_dir / "observations.jsonl"
    output.write_text('{"observation_id":"OBS-aabb-river-light-000001"}\n', encoding="utf-8")
    append_manifest(paths, _manifest_entry(paths, run_id, output), activate_stage="observations")

    assert main(["deactivate-stage", str(tmp_path), paths.topic_id, "observations"]) == 0
    assert paths.active_run_id("observations") is None
    assert run_dir.is_dir()
    assert any(entry.run_id == run_id for entry in read_jsonl(paths.manifest, ManifestEntry))
    assert verify_manifest(paths) == []

    # Idempotent cleanup makes consolidation scripts safe to re-run.
    assert main(["deactivate-stage", str(tmp_path), paths.topic_id, "observations"]) == 0


def test_finalize_run_cli_records_human_gate(tmp_path):
    paths = TopicPaths.for_topic(tmp_path, "aabb-river-light-2026").ensure()
    output = paths.root / "topic_manifest.yaml"
    output.write_text("topic_id: aabb-river-light-2026\n", encoding="utf-8")

    exit_code = main(
        [
            "finalize-run",
            str(tmp_path),
            paths.topic_id,
            "--skill-id",
            "s0-scope",
            "--skill-version",
            "0.1.0",
            "--run-id",
            "s0-202608180445-a01a0001",
            "--output",
            str(output),
            "--gates-json",
            '{"items":[{"gate":"G1","decided_by":"human",'
            '"decided_at":"2026-08-18T04:45:40Z","decision":"approved"}]}',
        ]
    )

    assert exit_code == 0
    (entry,) = read_jsonl(paths.manifest, ManifestEntry)
    assert entry.gates[0].gate.value == "G1"
    assert entry.gates[0].decided_by.value == "human"


def _write_fixture_skill_md(repo_root, skill_id, *, version="1.2.3", counters=None):
    """A minimal ``skills/<skill_id>/SKILL.md`` with just enough frontmatter for
    ``finalize-run`` to read ``newsab-version`` and, optionally,
    ``newsab-counters``."""
    counters_block = ""
    if counters is not None:
        lines = "\n".join(f"    {name}: {meaning}" for name, meaning in counters.items())
        counters_block = f'\n  newsab-counters: |\n{lines}'
    skill_dir = repo_root / "skills" / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {skill_id}\n"
        "description: fixture skill for finalize-run frontmatter tests, used when.\n"
        "metadata:\n"
        f'  newsab-stage: "{skill_id}"\n'
        f'  newsab-version: "{version}"'
        f"{counters_block}\n"
        "---\n\n"
        f"# {skill_id}\n",
        encoding="utf-8",
    )


def test_finalize_run_defaults_skill_version_from_frontmatter(tmp_path):
    _write_fixture_skill_md(tmp_path, "mystage", version="1.2.3")
    topics_root = tmp_path / "topics"
    paths = TopicPaths.for_topic(topics_root, "aabb-river-light-2026").ensure()
    output = paths.root / "topic_manifest.yaml"
    output.write_text("topic_id: aabb-river-light-2026\n", encoding="utf-8")

    exit_code = main(
        [
            "finalize-run",
            str(topics_root),
            paths.topic_id,
            "--skill-id",
            "mystage",
            "--run-id",
            "my-202608180445-a01a0001",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    (entry,) = read_jsonl(paths.manifest, ManifestEntry)
    assert entry.skill_version == "1.2.3"


def test_finalize_run_rejects_skill_version_mismatch(tmp_path, capsys):
    _write_fixture_skill_md(tmp_path, "mystage", version="1.2.3")
    topics_root = tmp_path / "topics"
    paths = TopicPaths.for_topic(topics_root, "aabb-river-light-2026").ensure()
    output = paths.root / "topic_manifest.yaml"
    output.write_text("topic_id: aabb-river-light-2026\n", encoding="utf-8")

    exit_code = main(
        [
            "finalize-run",
            str(topics_root),
            paths.topic_id,
            "--skill-id",
            "mystage",
            "--skill-version",
            "9.9.9",
            "--run-id",
            "my-202608180445-a01a0002",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "9.9.9" in err
    assert "1.2.3" in err
    assert str(tmp_path / "skills" / "mystage" / "SKILL.md") in err
    assert not paths.manifest.exists()


def test_finalize_run_requires_explicit_version_for_unknown_skill_md(tmp_path):
    # No skills/<id>/SKILL.md anywhere under this fake repo root — same as a skill-id
    # naming a retired skills/archive/<id> skill, which finalize-run deliberately does
    # not look inside: the run keeps the old, fully-explicit contract.
    topics_root = tmp_path / "topics"
    paths = TopicPaths.for_topic(topics_root, "aabb-river-light-2026").ensure()
    output = paths.root / "topic_manifest.yaml"
    output.write_text("topic_id: aabb-river-light-2026\n", encoding="utf-8")

    exit_code = main(
        [
            "finalize-run",
            str(topics_root),
            paths.topic_id,
            "--skill-id",
            "s4-annotate",  # retired skill, lives at skills/archive/s4-annotate only
            "--run-id",
            "my-202608180445-a01a0003",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 1


def test_finalize_run_warns_on_unknown_counter_key(tmp_path, capsys):
    _write_fixture_skill_md(
        tmp_path,
        "mystage",
        version="1.2.3",
        counters={"angles": "number of candidate angle cards"},
    )
    topics_root = tmp_path / "topics"
    paths = TopicPaths.for_topic(topics_root, "aabb-river-light-2026").ensure()
    output = paths.root / "topic_manifest.yaml"
    output.write_text("topic_id: aabb-river-light-2026\n", encoding="utf-8")

    exit_code = main(
        [
            "finalize-run",
            str(topics_root),
            paths.topic_id,
            "--skill-id",
            "mystage",
            "--run-id",
            "my-202608180445-a01a0004",
            "--output",
            str(output),
            "--counters-json",
            '{"angles": 4, "made_up_key": 1}',
        ]
    )

    assert exit_code == 0  # a warning, not a rejection
    err = capsys.readouterr().err
    assert "made_up_key" in err
    assert "warning" in err
    (entry,) = read_jsonl(paths.manifest, ManifestEntry)
    assert entry.counters == {"angles": 4, "made_up_key": 1}


def test_finalize_run_silent_when_counters_are_known(tmp_path, capsys):
    _write_fixture_skill_md(
        tmp_path,
        "mystage",
        version="1.2.3",
        counters={"angles": "number of candidate angle cards"},
    )
    topics_root = tmp_path / "topics"
    paths = TopicPaths.for_topic(topics_root, "aabb-river-light-2026").ensure()
    output = paths.root / "topic_manifest.yaml"
    output.write_text("topic_id: aabb-river-light-2026\n", encoding="utf-8")

    exit_code = main(
        [
            "finalize-run",
            str(topics_root),
            paths.topic_id,
            "--skill-id",
            "mystage",
            "--run-id",
            "my-202608180445-a01a0005",
            "--output",
            str(output),
            "--counters-json",
            '{"angles": 4}',
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().err == ""


def test_correction_mapping_is_append_only_and_hash_bound(tmp_path):
    import pytest
    from newsab_schema.io import ArtifactError

    paths = TopicPaths.for_topic(tmp_path, "aabb-river-light-2026").ensure()
    old_run = "s4-202608171200-aabbccdd"
    new_run = "s4-202608171201-bbccddee"
    old_dir = paths.stage_run_dir("observations", old_run)
    new_dir = paths.stage_run_dir("observations", new_run)
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    old = old_dir / "observations.jsonl"
    new = new_dir / "observations.jsonl"
    old.write_text('{"observation_id":"OBS-aabb-river-light-000001","value":"wrong"}\n', encoding="utf-8")
    new.write_text('{"observation_id":"OBS-aabb-river-light-000002","value":"fixed"}\n', encoding="utf-8")
    append_manifest(paths, _manifest_entry(paths, old_run, old))
    append_manifest(paths, _manifest_entry(paths, new_run, new))
    mapping = CorrectionMapping(
        correction_id="COR-aabb-river-light-2026-0001",
        topic_id=paths.topic_id,
        superseded=ArtifactReference(
            run_id=old_run,
            path=old.relative_to(paths.root).as_posix(),
            sha256=file_digest(old),
            record_id="OBS-aabb-river-light-000001",
        ),
        replacement=ArtifactReference(
            run_id=new_run,
            path=new.relative_to(paths.root).as_posix(),
            sha256=file_digest(new),
            record_id="OBS-aabb-river-light-000002",
        ),
        reason=LangText(text="修正错误标注", lang="zh-CN"),
        provenance=Provenance(
            skill_version="S4-0.2.0",
            model_id="fixture-model",
            run_id=new_run,
            timestamp=datetime(2026, 8, 17, tzinfo=timezone.utc),
        ),
        timestamp=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )
    append_correction(paths, mapping)
    assert verify_manifest(paths) == []
    with pytest.raises(ArtifactError, match="already has a correction"):
        append_correction(paths, mapping.model_copy(update={"correction_id": "COR-aabb-river-light-2026-0002"}))


def test_dist_check_accepts_an_older_generators_equivalent_form(tmp_path):
    """A schema differing only in how the generator spelled a ``$ref`` is not stale.

    Pydantic wrote ``$ref`` with sibling keywords as a single-element ``allOf`` before
    2.9 and inline since.  Comparing bytes would fail the gate for a contributor whose
    pydantic differs from the one that last wrote ``dist/`` — a red gate nobody can fix,
    which is the failure mode ``--scope workspace`` exists to prevent.
    """
    from newsab_schema.export import check_in_sync, json_schema_for, write_all

    write_all(tmp_path)
    target = tmp_path / "topic_manifest.schema.json"
    document = json.loads(target.read_text(encoding="utf-8"))
    rewritten = _wrap_refs_in_all_of(document)
    assert rewritten != document, "fixture needs a $ref carrying sibling keywords"
    target.write_text(
        json.dumps(rewritten, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    assert check_in_sync(tmp_path) == []

    # a real model change is still caught
    changed = json_schema_for("topic_manifest")
    changed["properties"]["invented_field"] = {"type": "string"}
    target.write_text(
        json.dumps(changed, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert check_in_sync(tmp_path) == ["topic_manifest.schema.json"]


def _wrap_refs_in_all_of(node):
    """Re-spell inline ``$ref``-with-siblings the way pydantic < 2.9 did."""
    if isinstance(node, dict):
        out = {key: _wrap_refs_in_all_of(value) for key, value in node.items()}
        if "$ref" in out and len(out) > 1:
            reference = out.pop("$ref")
            out["allOf"] = [{"$ref": reference}]
        return out
    if isinstance(node, list):
        return [_wrap_refs_in_all_of(item) for item in node]
    return node
