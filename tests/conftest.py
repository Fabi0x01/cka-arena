"""Global pytest fixtures — isolate persistent state from real user data."""

from __future__ import annotations

import pytest

from app import config, db


@pytest.fixture(autouse=True)
def _isolate_persistent_state(tmp_path, monkeypatch):
    """Prevent any test from accidentally mutating data/cka_arena.db or llm_config.json."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "LLM_CONFIG_PATH", tmp_path / "llm_config.json")
    db._WAL_INITIALIZED.clear()
