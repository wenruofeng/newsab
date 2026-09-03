from __future__ import annotations

from pathlib import Path

import pytest

from submission_fixture import build_tree, pack_fixture


@pytest.fixture(scope="session")
def fixture_tree(tmp_path_factory) -> tuple[Path, object]:
    """``(tree_root, TopicPaths)`` — topics/ plus sources/ inside one throwaway root."""
    root = tmp_path_factory.mktemp("synthetic-tree")
    paths = build_tree(root)
    return root, paths


@pytest.fixture(scope="session")
def good_archive(fixture_tree, tmp_path_factory) -> tuple[Path, dict]:
    root, _ = fixture_tree
    out = tmp_path_factory.mktemp("archive") / "submission.tgz"
    report = pack_fixture(root, out)
    return out, report
