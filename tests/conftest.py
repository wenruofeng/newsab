"""pytest wiring for the repo-level integration tests.

The fixture *builder* lives in `pipeline_fixture.py` rather than here so that other
packages' test suites can import it (`from pipeline_fixture import build_topic`) without
colliding with their own `conftest.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline_fixture import REPO, TOPIC, build_topic, run_script  # noqa: F401

from newsab_schema.paths import TopicPaths  # noqa: E402


@pytest.fixture
def topic(tmp_path) -> tuple[Path, TopicPaths]:
    """``(topics_root, paths)``.  ``topics_root`` is ``tmp_path/topics`` so the cross-topic
    ``sources/registry.yaml`` (R-3) lands beside it inside the same throwaway tree."""
    paths = build_topic(tmp_path)
    return tmp_path / "topics", paths
