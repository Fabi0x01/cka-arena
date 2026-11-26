"""Testes dos seeds e do envelope (modelos Pydantic)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import DOMAINS, ScenarioEnvelope
from app.seed import load_seeds


def test_seeds_load_and_validate() -> None:
    seeds = load_seeds()
    assert len(seeds) == 30
    domains = {env.domain for _path, env in seeds}
    assert domains == set(DOMAINS)
    ids = [env.id for _path, env in seeds]
    assert len(ids) == len(set(ids)), "ids de seed devem ser únicos"
    for _path, env in seeds:
        assert env.prompt.strip()
        assert env.checks, f"{env.id} sem checks"
        assert env.solution.commands or env.solution.manifests or env.solution.node_commands
    assert sum(1 for _p, env in seeds if env.destructive) == 3


def test_envelope_rejects_unknown_domain() -> None:
    payload = {
        "id": "x", "title": "t", "domain": "Networking", "difficulty": "exam_standard",
        "weight": 3, "prompt": "p", "setup": {"namespaces": []}, "checks": [],
    }
    with pytest.raises(ValidationError):
        ScenarioEnvelope.model_validate(payload)


def test_envelope_rejects_unknown_check_type() -> None:
    payload = {
        "id": "x", "title": "t", "domain": "Storage", "difficulty": "exam_standard",
        "weight": 3, "prompt": "p", "setup": {"namespaces": []},
        "checks": [{"id": "c", "description": "d", "type": "magic_check", "params": {}}],
    }
    with pytest.raises(ValidationError):
        ScenarioEnvelope.model_validate(payload)


def test_seed_prompts_are_english_exam_voice() -> None:
    for _path, env in load_seeds():
        assert "Perform the following tasks" in env.prompt, env.id
        assert "Requisitos" not in env.prompt
