"""P0 contract checks for the future one-way public exporter.

Reader: P1 exporter implementers. These tests protect the authorization boundary before
there is any copy command: broadening a source root, weakening fail-closed defaults, or
changing the reviewed registry bytes must be an explicit contract change.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path, PurePosixPath

import yaml


REPO = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO / "public_export.yaml"


def _contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def _definition_path(rule: dict) -> Path:
    """Resolve a contract rule in either the private source or assembled public tree."""
    source = REPO / rule["source"]
    return source if source.exists() else REPO / rule["target"]


def _is_relative_safe(raw: str) -> bool:
    path = PurePosixPath(raw)
    return not path.is_absolute() and ".." not in path.parts and raw not in {"", "."}


def test_public_export_is_fail_closed_and_fresh_history():
    contract = _contract()
    policy = contract["source_policy"]
    assert contract["destination"] == {
        "repository": "wenruofeng/newsab",
        "default_branch": "main",
        "history": "fresh",
    }
    assert policy["revision"] == "exact_commit"
    assert policy["tracked_files_only"] is True
    assert policy["require_clean_worktree"] is True
    assert policy["follow_symlinks"] is False
    assert policy["unmatched_paths"] == "deny"
    assert policy["assemble_into_empty_directory"] is True


def test_every_copy_rule_is_named_explained_and_path_safe():
    contract = _contract()
    rules = contract["copies"]
    assert len({rule["id"] for rule in rules}) == len(rules)
    assert all(rule["rationale"].strip() for rule in rules)
    for rule in rules:
        assert rule["select"] in {"file", "tracked_tree", "tracked_patterns"}
        assert _is_relative_safe(rule["source"])
        if "append_source" in rule:
            assert rule["select"] == "file"
            assert _is_relative_safe(rule["append_source"])
        assert _is_relative_safe(rule["target"])
        source = _definition_path(rule)
        assert source.exists(), f"missing definition source: {rule['source']}"
        if rule["select"] == "file":
            assert source.is_file()
            assert "patterns" not in rule
        elif rule["select"] == "tracked_tree":
            assert source.is_dir()
            assert "patterns" not in rule
        else:
            assert source.is_dir()
            assert rule.get("patterns")
            assert all(_is_relative_safe(pattern) for pattern in rule["patterns"])


def test_no_authorized_source_or_target_crosses_a_forbidden_prefix():
    contract = _contract()
    target_forbidden = tuple(
        PurePosixPath(path).parts for path in contract["forbidden_path_prefixes"]
    )
    source_forbidden = (
        *target_forbidden,
        *(PurePosixPath(path).parts for path in contract["forbidden_source_path_prefixes"]),
    )
    for rule in contract["copies"]:
        source_parts = PurePosixPath(rule["source"]).parts
        target_parts = PurePosixPath(rule["target"]).parts
        assert not any(source_parts[: len(prefix)] == prefix for prefix in source_forbidden)
        assert not any(target_parts[: len(prefix)] == prefix for prefix in target_forbidden)


def test_real_topics_site_state_history_and_brand_assets_are_not_selected():
    contract = _contract()
    sources = {rule["source"] for rule in contract["copies"]}
    assert not any(source.startswith("topics/") and source not in {
        "topics/README.md", "topics/.gitignore"
    } for source in sources)
    assert not any(source.startswith("site/") and source != "site/theme_panel.html" for source in sources)
    assert not any(source.startswith("docs/reports") or source.startswith("docs/archive") for source in sources)
    publish = next(rule for rule in contract["copies"] if rule["id"] == "publish-package")
    selected = "\n".join(publish["patterns"])
    for private_name in (
        "favicon.svg", "logo-transparent-dark.svg", "logo-transparent-light.svg",
        "share-card.png", "site_metadata.v1.json",
    ):
        assert private_name not in selected


def test_public_facing_license_and_contribution_sources_are_complete():
    contract = _contract()
    targets = {rule["target"] for rule in contract["copies"]}
    assert {
        "README.md", "README.zh-CN.md", "CONTRIBUTING.md",
        "CONTRIBUTING.zh-CN.md", "LICENSE", "LICENSE_SCOPE.md",
        "THIRD_PARTY_NOTICES.md", "docs/SYNTHETIC_DEMO_INVENTORY.md",
        "AGENTS.md", "CLAUDE.md", "TODO.md", "docs/decisions.md",
        "docs/reports/README.md", "docs/archive/README.md",
    } <= targets
    assert contract["license_policy"] == {
        "default_spdx": "MIT",
        "license_file": "LICENSE",
        "scope_file": "LICENSE_SCOPE.md",
        "notices_file": "THIRD_PARTY_NOTICES.md",
        "inbound_contributions": "inbound_equals_outbound",
        "signoff": "DCO-1.1",
    }


def test_public_documentation_is_english_default_with_chinese_user_peers():
    contract = _contract()
    assert contract["documentation_policy"] == {
        "default_language": "en",
        "user_facing_languages": ["en", "zh-CN"],
        "translation_suffix": ".zh-CN.md",
        "english_only_classes": [
            "agent_facing", "legal", "license", "infrequent_reference"
        ],
    }
    docs = {
        rule["id"]: rule for rule in contract["copies"] if "document_class" in rule
    }
    user_docs = [rule for rule in docs.values() if rule["document_class"] == "user_facing"]
    english_user_docs = [rule for rule in user_docs if rule["language"] == "en"]
    chinese_user_docs = [rule for rule in user_docs if rule["language"] == "zh-CN"]
    assert {rule["id"] for rule in english_user_docs} == {
        "public-readme", "public-contributing"
    }
    assert {rule["translation_of"] for rule in chinese_user_docs} == {
        rule["id"] for rule in english_user_docs
    }
    assert all(rule["target"].endswith(".zh-CN.md") for rule in chinese_user_docs)
    english_only = [
        rule for rule in docs.values() if rule["document_class"] != "user_facing"
    ]
    assert all(rule["language"] == "en" for rule in english_only)
    assert all("translation_of" not in rule for rule in english_only)

    han = re.compile(r"[\u3400-\u9fff]")
    # A language switcher names the other language in that language ("[中文](README.zh-CN.md)"),
    # so a markdown link label is the one place an English-default doc may carry Han; its
    # prose may not.  Drop labels, keep targets, then check what a reader actually reads.
    link = re.compile(r"\[([^\]\n]*)\]\(([^)\n]*)\)")
    for rule in user_docs:
        path = _definition_path(rule)
        text = path.read_text(encoding="utf-8")
        if path.name.endswith(".zh-CN.md"):
            assert han.search(text), f"Chinese peer contains no Chinese text: {path.name}"
        else:
            prose = link.sub(r"(\2)", text)
            assert not han.search(prose), f"English-default/reference doc contains Chinese: {path.name}"
    assert "README.zh-CN.md" in _definition_path(docs["public-readme"]).read_text(encoding="utf-8")
    assert "README.md" in _definition_path(docs["public-readme-zh-cn"]).read_text(encoding="utf-8")
    assert "CONTRIBUTING.zh-CN.md" in _definition_path(docs["public-contributing"]).read_text(encoding="utf-8")
    assert "CONTRIBUTING.md" in _definition_path(docs["public-contributing-zh-cn"]).read_text(encoding="utf-8")


def test_all_active_stage_skills_and_only_the_active_stage_skills_are_selected():
    contract = _contract()
    selected = {
        rule["source"].removeprefix("skills/")
        for rule in contract["copies"]
        if rule["id"].startswith("skill-") and rule["id"] not in {"skill-template"}
    }
    assert selected == {
        "scope", "collect", "annotate", "normalize", "analyze", "write",
        "render-localize", "publish",
    }
    assert "skills/archive" not in {rule["source"] for rule in contract["copies"]}


def test_public_test_allowlist_does_not_import_retired_pipeline_skills():
    rule = next(rule for rule in _contract()["copies"] if rule["id"] == "repository-tests")
    assert rule["select"] == "tracked_patterns"
    assert "test_phase0_pipeline.py" not in rule["patterns"]
    for relative in rule["patterns"]:
        text = (REPO / "tests" / relative).read_text(encoding="utf-8")
        assert "skills/" + "archive/" not in text


def test_registry_review_is_bound_to_the_scanned_bytes():
    contract = _contract()
    rule = next(rule for rule in contract["copies"] if rule["id"] == "source-registry")
    review = rule["content_review"]
    actual = hashlib.sha256(_definition_path(rule).read_bytes()).hexdigest()
    assert actual == review["sha256"]
    assert review["secret_scan"] == "clear"
    assert review["pii_scan"] == "one_public_newsroom_email_retained"


def test_p1_gates_are_ready_and_have_standalone_proofs():
    gates = _contract()["release_gates"]
    assert {gate["id"] for gate in gates} == {
        "synthetic-demo", "synthetic-test-rewrites", "neutral-site-identity", "clean-clone-ci"
    }
    assert {gate["status"] for gate in gates} == {"ready"}
    assert all(gate["specification"] for gate in gates)
    targets = {rule["target"] for rule in _contract()["copies"]}
    assert {
        "tools/public_export.py",
        "tools/public_release_gate.py",
        "tools/skills_check.py",
        ".github/workflows/ci.yml",
        "examples/synthetic-topic",
    } <= targets
    gate = (REPO / "tools/public_release_gate.py").read_text(encoding="utf-8")
    assert '"no:cacheprovider"' in gate


def test_only_the_exported_agent_contract_carries_the_public_clone_section():
    """One contract, single-sourced, plus a public-only §6.  An agent in the private repo
    must not have to work out which of two repositories a first-run rule is addressed to,
    and an agent in a public clone must be told there that its history stops there."""
    contract = _contract()
    appendix = "public/agents_public_clone.md"
    rules = [
        rule for rule in contract["copies"]
        if rule["id"] in {"agent-contract", "claude-agent-contract"}
    ]
    assert {rule["target"] for rule in rules} == {"AGENTS.md", "CLAUDE.md"}
    assert all(rule["source"] == "AGENTS.md" for rule in rules)
    assert all(rule.get("append_source") == appendix for rule in rules)

    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert agents == (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    source = REPO / appendix
    if source.exists():
        # The private repository: the section lives only in the appendix.
        public_clone = source.read_text(encoding="utf-8")
        assert public_clone.startswith("\n## 6. ")
        assert agents.endswith("\n") and "public clone" not in agents
    else:
        # The exported tree: the appendix is already part of the contract an agent reads.
        public_clone = agents
    assert "## 6. You are in a public clone" in public_clone
    assert "do not `git push`" in public_clone
    assert "`.newsab/operator_identity.json`" in public_clone


def test_the_gate_a_public_clone_is_told_to_run_defaults_to_workspace_scope():
    """A clone carries Git history, editable installs, caches and its owner's own work.
    The documented command must keep passing there; byte identity with the manifest is
    the publisher's check, and only the release pipeline asks for it."""
    gate = (REPO / "tools/public_release_gate.py").read_text(encoding="utf-8")
    assert 'choices=("workspace", "release"), default="workspace"' in gate
    contract = _contract()
    # The documented invocation runs inside the checkout's own uv environment.
    for rule_id, prefix in (
        ("public-readme", "uv run "),
        ("public-readme-zh-cn", "uv run "),
        ("public-ci", "run: uv run "),
    ):
        rule = next(rule for rule in contract["copies"] if rule["id"] == rule_id)
        text = _definition_path(rule).read_text(encoding="utf-8")
        commands = [
            line.strip() for line in text.splitlines()
            if line.strip().startswith(f"{prefix}python tools/public_release_gate.py")
        ]
        assert commands == [f"{prefix}python tools/public_release_gate.py"], rule_id


def test_private_identity_data_is_replaced_by_public_starter_overlays():
    contract = _contract()
    mappings = {rule["target"]: rule["source"] for rule in contract["copies"]}
    assert mappings["packages/corpus/newsab_corpus/data/operator_identity.v1.json"] == (
        "public/neutral/operator_identity.v1.json"
    )
    assert mappings["packages/editorial/newsab_editorial/render/data/site_identity.v1.json"] == (
        "public/neutral/editorial_site_identity.v1.json"
    )
    assert mappings["packages/publish/newsab_publish/data/site_identity.v1.json"] == (
        "public/neutral/site_identity.v1.json"
    )
    assert mappings["packages/publish/newsab_publish/data/site_metadata.v1.json"] == (
        "public/neutral/site_metadata.v1.json"
    )
    assert mappings["examples/theme_panel.html"] == "public/neutral/theme_panel.html"
    for name in (
        "favicon.svg", "logo-transparent-dark.svg", "logo-transparent-light.svg",
        "share-card.png",
    ):
        target = f"packages/publish/newsab_publish/data/{name}"
        assert mappings[target] == f"public/neutral/{name}"


def test_development_only_docs_and_unused_eval_package_are_not_selected():
    targets = {rule["target"] for rule in _contract()["copies"]}
    assert "packages/eval" not in targets
    assert "docs/methods_and_eval_design.md" not in targets
    assert "docs/full_process_flow_chart.md" not in targets
    assert "packages/README.md" not in targets
    assert _contract()["local_runtime_paths"] == [".newsab/operator_identity.json"]


def test_halo_translation_data_is_exported_identity_free_and_the_legal_notice_is_not():
    """The publisher and renderer do not import without the seven halo locales'
    translation files, which are copied unchanged — so nothing in them may name the
    production site (site name, about paragraph, contact and footer domain are identity
    slots filled at import).  The privacy notice is news-ab.com's own promise and stays
    private; ``legal.py`` ships it for the official identity only."""
    contract = _contract()
    rules = {rule["id"]: rule for rule in contract["copies"]}
    expected = {
        "editorial-package": (
            "newsab_editorial/render/data/chrome_strings_i18n.v1.json",
            "newsab_editorial/render/data/stat_panel_i18n.v1.json",
        ),
        "publish-package": (
            "newsab_publish/data/about_i18n.v1.json",
            "newsab_publish/data/site_strings_i18n.v1.json",
            "newsab_publish/data/suggest_i18n.v1.json",
        ),
    }
    for rule_id, names in expected.items():
        rule = rules[rule_id]
        for name in names:
            assert name in rule["patterns"], (rule_id, name)
            data = (REPO / rule["source"] / name).read_text(encoding="utf-8").casefold()
            for token in ("news a/b", "news-ab.com", "wenruofeng", "gmail.com"):
                assert token not in data, (name, token)
    assert not any("legal" in pattern for pattern in rules["publish-package"]["patterns"])
    assert not any("legal" in rule["source"] for rule in contract["copies"])


def test_publish_package_exports_root_level_tests_as_well_as_nested_tests():
    rule = next(rule for rule in _contract()["copies"] if rule["id"] == "publish-package")
    assert "newsab_publish/*.py" in rule["patterns"]
    assert "tests/*.py" in rule["patterns"]


def test_neutral_share_card_is_reproducible_without_third_party_assets():
    generator = REPO / "public/neutral/generate_assets.py"
    card = REPO / "public/neutral/share-card.png"
    if not generator.exists():
        generator = REPO / "tools/generate_neutral_assets.py"
        card = REPO / "packages/publish/newsab_publish/data/share-card.png"
    spec = importlib.util.spec_from_file_location("neutral_asset_generator", generator)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.build_png() == card.read_bytes()
