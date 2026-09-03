"""Fail-closed tests for the standalone public export verifier.

These tests use only temporary ordinary directories.  They deliberately do not create a
Git repository; exact-commit behavior is covered by the exporter integration run itself.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from tools import public_export
from tools.public_export import ExportError, _selected_files, verify_export


NEUTRAL_DEFAULTS = {
    "packages/corpus/newsab_corpus/data/operator_identity.v1.json": {
        "configured": False,
        "operator_email": None,
        "operator_url": None,
    },
    "packages/editorial/newsab_editorial/render/data/site_identity.v1.json": {
        "domain_label": "local-toolkit.example",
    },
    "packages/publish/newsab_publish/data/site_identity.v1.json": {
        "site_name": "Narrative Diff Toolkit",
        "domain_label": "local-toolkit.example",
    },
    "packages/publish/newsab_publish/data/site_metadata.v1.json": {
        "metadata_version": "site-metadata-1.0.0",
    },
}
NEUTRAL_ASSETS = {
    "packages/publish/newsab_publish/data/favicon.svg": "public/neutral/favicon.svg",
    "packages/publish/newsab_publish/data/logo-transparent-dark.svg":
        "public/neutral/logo-transparent-dark.svg",
    "packages/publish/newsab_publish/data/logo-transparent-light.svg":
        "public/neutral/logo-transparent-light.svg",
    "packages/publish/newsab_publish/data/share-card.png": "public/neutral/share-card.png",
}
# Copied from the private tree unchanged; every site-specific string is a slot.
IDENTITY_FREE_DATA = {
    "packages/editorial/newsab_editorial/render/data/chrome_strings_i18n.v1.json": {
        "STRINGS": {"ru": {"footer_note": "Одна история, два изложения"}},
    },
    "packages/editorial/newsab_editorial/render/data/stat_panel_i18n.v1.json": {
        "STAT_READING": {"ru": "Как читать"},
    },
    "packages/publish/newsab_publish/data/about_i18n.v1.json": {
        "copy": {"ru": {"title": "О сайте"}},
    },
    "packages/publish/newsab_publish/data/site_strings_i18n.v1.json": {
        "site_strings": {"ru": {"home": "Главная"}},
    },
    "packages/publish/newsab_publish/data/suggest_i18n.v1.json": {
        "ru": {"title": "Предложите тему для {site_name}"},
    },
}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_export(root: Path) -> None:
    contract = {
        "forbidden_path_prefixes": [".git", "topics/private"],
        "local_runtime_paths": [".newsab/operator_identity.json"],
        "license_policy": {
            "license_file": "LICENSE",
            "scope_file": "LICENSE_SCOPE.md",
            "notices_file": "THIRD_PARTY_NOTICES.md",
        },
    }
    files: dict[str, tuple[bytes, str]] = {
        "LICENSE": (
            b"MIT License\n\nPermission is hereby granted, free of charge.\n",
            "public/LICENSE",
        ),
        "LICENSE_SCOPE.md": (b"# Scope\n", "public/LICENSE_SCOPE.md"),
        "THIRD_PARTY_NOTICES.md": (b"# Notices\n", "public/THIRD_PARTY_NOTICES.md"),
    }
    for target, payload in NEUTRAL_DEFAULTS.items():
        files[target] = (json.dumps(payload).encode(), "public/neutral/example.json")
    for target, source in NEUTRAL_ASSETS.items():
        files[target] = (b"neutral-placeholder", source)
    for target, payload in IDENTITY_FREE_DATA.items():
        files[target] = (json.dumps(payload, ensure_ascii=False).encode(), target)
    contract_bytes = yaml.safe_dump(contract, sort_keys=False).encode()
    files["public_export.yaml"] = (contract_bytes, "public_export.yaml")
    manifest_rows = []
    for relative, (data, source) in sorted(files.items()):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        manifest_rows.append(
            {"path": relative, "sha256": _digest(data), "source": source, "mode": "100644"}
        )
    manifest = {
        "contract_sha256": _digest(contract_bytes),
        "files": manifest_rows,
        "forbidden_identity_hashes": {
            "topic_sha256": [_digest(b"private-topic-2026")],
            "publication_sha256": [],
        },
    }
    (root / "export-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_verify_export_accepts_a_closed_neutral_tree(tmp_path):
    _valid_export(tmp_path)
    result = verify_export(tmp_path)
    assert result["files"] == 17
    assert "neutral_defaults" in result["checks"]


def test_verify_export_accepts_only_the_configured_local_operator_identity(tmp_path, monkeypatch):
    _valid_export(tmp_path)
    identity = tmp_path / ".newsab/operator_identity.json"
    identity.parent.mkdir()
    identity.write_text(json.dumps({
        "configured": True,
        "identity_version": "collector-identity-1.0.0",
        "operator_email": "collector@reader.example",
        "operator_url": "https://reader.example/about",
    }), encoding="utf-8")
    verify_export(tmp_path)

    identity.write_text(json.dumps({"configured": False}), encoding="utf-8")
    with pytest.raises(ExportError, match="configured must be true"):
        verify_export(tmp_path)

    # The guard recognises the production address by digest and never spells it; the
    # test stands a throwaway address in its place and exercises the comparison.
    borrowed = "collector@production.example"
    monkeypatch.setattr(
        public_export,
        "PRODUCTION_OPERATOR_EMAIL_SHA256",
        hashlib.sha256(borrowed.encode("utf-8")).hexdigest(),
    )
    identity.write_text(json.dumps({
        "configured": True,
        "operator_email": "Collector@Production.example",
        "operator_url": "https://reader.example/about",
    }), encoding="utf-8")
    with pytest.raises(ExportError, match="production operator's contact"):
        verify_export(tmp_path)
    assert "@" not in Path(public_export.__file__).read_text(encoding="utf-8").split("PRODUCTION_OPERATOR_EMAIL_SHA256 =")[1].split("\n")[0]


def test_verify_export_refuses_private_workflow_residue_in_prose(tmp_path):
    """Ticket numbers, the private operator word and dangling doc pointers stay private.

    The tokens are assembled at runtime so this test file, which is itself exported,
    does not carry them.
    """
    _valid_export(tmp_path)
    module = tmp_path / "packages/newsab_x/rules.py"
    module.parent.mkdir(parents=True)
    ticket = "T-" + "123"
    word = "foun" + "der"
    clean = (
        'REVIEWER = "' + word + '"\n'
        "# the reviewer signs the bytes, see docs/value_chain.md\n"
        "SOURCE = '" + word + "_annotation'\n"
        "is_" + word + " = False\n"
    )
    module.write_text(clean, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/value_chain.md").write_text("# spec\n", encoding="utf-8")
    assert public_export.scan_workflow_residue(tmp_path, [module]) == []

    dirty = clean + (
        "# ruled at G2 (" + ticket + ")\n"
        "# the " + word + " objected\n"
        "# see docs/private_plan.md\n"
    )
    module.write_text(dirty, encoding="utf-8")
    findings = public_export.scan_workflow_residue(tmp_path, [module])
    assert [row.split(": ", 1)[1] for row in findings] == [
        "private ticket number",
        "private operator word",
        "points at unexported docs/private_plan.md",
    ]
    # Data files are content, not workflow: an outlet's own history is not provenance.
    registry = tmp_path / "sources/registry.yaml"
    registry.parent.mkdir()
    registry.write_text("notes: " + word + " of the paper\n", encoding="utf-8")
    assert public_export.scan_workflow_residue(tmp_path, [registry]) == []


def _clone_noise(root: Path) -> None:
    """Everything an installed, tested, committed-to Git clone grows on its own."""
    (root / ".git").mkdir()
    (root / ".git/config").write_text("[core]\n\trepositoryformatversion = 0\n", encoding="utf-8")
    (root / "packages/newsab_corpus.egg-info").mkdir(parents=True)
    (root / "packages/newsab_corpus.egg-info/PKG-INFO").write_text("Name: x\n", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__/tool.cpython-312.pyc").write_bytes(b"\x00\x01")
    (root / ".pytest_cache").mkdir()
    (root / ".pytest_cache/CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172\n", encoding="utf-8")


def test_workspace_scope_accepts_an_installed_clone_that_has_been_worked_in(tmp_path):
    _valid_export(tmp_path)
    _clone_noise(tmp_path)
    (tmp_path / "docs/reports").mkdir(parents=True)
    (tmp_path / "docs/reports/task_202609011700_local.md").write_text("# local work\n", encoding="utf-8")
    (tmp_path / "LICENSE_SCOPE.md").write_text("# Scope\n\nnotes added by the clone owner\n", encoding="utf-8")

    result = verify_export(tmp_path, "workspace")
    assert result["scope"] == "workspace"
    assert result["files"] == 17

    with pytest.raises(ExportError, match="closed manifest mismatch"):
        verify_export(tmp_path)


def test_release_scope_ignores_clone_noise_but_still_closes_the_manifest(tmp_path):
    _valid_export(tmp_path)
    _clone_noise(tmp_path)
    verify_export(tmp_path)

    (tmp_path / "unreviewed.txt").write_text("surprise", encoding="utf-8")
    with pytest.raises(ExportError, match="closed manifest mismatch"):
        verify_export(tmp_path)


def test_workspace_scope_refuses_a_deleted_released_file(tmp_path):
    _valid_export(tmp_path)
    (tmp_path / "LICENSE_SCOPE.md").unlink()
    with pytest.raises(ExportError, match="missing from this clone"):
        verify_export(tmp_path, "workspace")


def test_workspace_scope_still_scans_released_files_for_leaks(tmp_path):
    _valid_export(tmp_path)
    (tmp_path / "LICENSE_SCOPE.md").write_text(
        "# Scope\n\nsee topics/private-topic-2026 for context\n", encoding="utf-8"
    )
    with pytest.raises(ExportError, match="private topic identifier"):
        verify_export(tmp_path, "workspace")


@pytest.mark.parametrize(
    ("relative", "token"),
    [
        ("packages/publish/newsab_publish/data/suggest_i18n.v1.json", "News A/B"),
        ("packages/editorial/newsab_editorial/render/data/chrome_strings_i18n.v1.json", "news-ab.com"),
    ],
)
def test_translation_data_that_names_the_production_site_is_refused(tmp_path, relative, token):
    """The halo translations are exported as-is, so a brand written back into copy would
    reach the neutral clone; the verifier scans them like the overlaid identity files."""
    _valid_export(tmp_path)
    path = tmp_path / relative
    path.write_text(json.dumps({"x": {"ru": f"about {token}"}}), encoding="utf-8")
    with pytest.raises(ExportError, match="production identity token"):
        verify_export(tmp_path, "workspace")


def test_unknown_verification_scope_is_refused(tmp_path):
    _valid_export(tmp_path)
    with pytest.raises(ExportError, match="unknown verification scope"):
        verify_export(tmp_path, "clone")


@pytest.mark.parametrize("mutation", ["extra", "changed", "private-id"])
def test_verify_export_fails_closed(tmp_path, mutation):
    _valid_export(tmp_path)
    if mutation == "extra":
        (tmp_path / "unreviewed.txt").write_text("surprise", encoding="utf-8")
    elif mutation == "changed":
        (tmp_path / "LICENSE_SCOPE.md").write_text("changed", encoding="utf-8")
    else:
        path = tmp_path / "packages/corpus/newsab_corpus/fetch.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("topic = 'private-topic-2026'", encoding="utf-8")
        manifest_path = tmp_path / "export-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        data = path.read_bytes()
        manifest["files"].append(
            {"path": path.relative_to(tmp_path).as_posix(), "sha256": _digest(data),
             "source": "packages/corpus/newsab_corpus/fetch.py", "mode": "100644"}
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ExportError):
        verify_export(tmp_path)


def test_append_source_is_a_second_tracked_file_not_a_rewrite():
    tree = {
        "AGENTS.md": ("100644", "base-oid"),
        "public/agents_public_clone.md": ("100644", "appendix-oid"),
    }
    rule = {
        "id": "agent-contract", "source": "AGENTS.md", "target": "AGENTS.md",
        "select": "file", "append_source": "public/agents_public_clone.md",
    }
    contract = {"forbidden_path_prefixes": [".git"], "copies": [rule]}
    assert _selected_files(contract, tree) == [
        ("AGENTS.md", "AGENTS.md", "100644", "base-oid",
         ("public/agents_public_clone.md", "appendix-oid")),
    ]

    rule["append_source"] = "public/absent.md"
    with pytest.raises(ExportError, match="append source is not tracked"):
        _selected_files(contract, tree)

    rule["append_source"] = "public/agents_public_clone.md"
    contract["forbidden_source_path_prefixes"] = ["public"]
    with pytest.raises(ExportError, match="forbidden path"):
        _selected_files(contract, tree)

    contract.pop("forbidden_source_path_prefixes")
    rule["select"] = "tracked_tree"
    with pytest.raises(ExportError, match="append_source requires select: file"):
        _selected_files(contract, tree)


def test_selection_rejects_forbidden_targets_and_symlinks():
    tree = {"safe.py": ("120000", "fake-oid")}
    contract = {
        "forbidden_path_prefixes": [".git", "private"],
        "forbidden_source_path_prefixes": ["internal"],
        "copies": [
            {"id": "bad", "source": "safe.py", "target": "private/safe.py", "select": "file"}
        ],
    }
    with pytest.raises(ExportError, match="forbidden path"):
        _selected_files(contract, tree)

    contract["copies"][0]["target"] = "safe.py"
    with pytest.raises(ExportError, match="symlinks are forbidden"):
        _selected_files(contract, tree)

    tree = {"internal/safe.py": ("100644", "fake-oid")}
    contract["copies"][0].update(source="internal/safe.py", target="safe.py")
    with pytest.raises(ExportError, match="forbidden path"):
        _selected_files(contract, tree)
