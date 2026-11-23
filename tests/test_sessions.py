"""Testes do fluxo de sessão (engine/doctor stubados, DB temporário)."""

from __future__ import annotations

import asyncio
import json

import pytest

from app import bank, config, db
from app.models import ScenarioEnvelope
from app.sessions import SessionError, SessionService


class StubEngine:
    def __init__(self) -> None:
        self.applied: list[str] = []
        self.cleaned: list[str] = []
        self.report = {"all_passed": False, "infra_error": False, "results": [],
                       "duration_ms": 1, "ran_at": 0.0}

    async def apply_setup(self, env):
        self.applied.append(env.id)

    async def cleanup(self, env):
        self.cleaned.append(env.id)

    async def run_checks(self, env, *, settle=True):
        return self.report


class StubDoctor:
    """Sessões testadas com teardown stubado — o doctor não é exercitado."""


@pytest.fixture()
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init_db()
    envelope = ScenarioEnvelope.model_validate(
        json.loads((config.BASE_DIR / "scenarios" / "seed" / "ts-crashloop-fix.json").read_text())
    )
    bank.publish_question(envelope, source="seed")
    engine = StubEngine()
    svc = SessionService(engine, StubDoctor())  # type: ignore[arg-type]

    async def fake_cleanup_session():
        return {"level": "L1", "namespaces_deleted": [], "drift": {"drift": False, "nodes": {}}}

    async def fake_reset_clean():
        return {"level": "L2-clean", "api_ready": True, "nodes_ready": True,
                "drift": {"drift": False, "nodes": {}}}

    monkeypatch.setattr(svc.teardown, "cleanup_session", fake_cleanup_session)
    monkeypatch.setattr(svc.teardown, "reset_clean", fake_reset_clean)
    return svc, engine


def test_check_blocks_next_until_passed_and_finishes_with_summary(service) -> None:
    svc, engine = service

    async def scenario() -> None:
        session = await svc.create(1)
        session_id = session["session"]["id"]
        assert session["active"]["item_state"] == "active"
        assert engine.applied, "setup deve ser aplicado ao iniciar"

        engine.report = {"all_passed": False, "infra_error": False, "results": [],
                         "duration_ms": 1, "ran_at": 0.0}
        result = await svc.check(session_id)
        assert result["report"]["all_passed"] is False
        assert result["session"]["active"]["item_state"] == "active"
        with pytest.raises(SessionError):
            await svc.next(session_id)

        engine.report = {"all_passed": True, "infra_error": False, "results": [],
                         "duration_ms": 1, "ran_at": 0.0}
        result = await svc.check(session_id)
        assert result["session"]["active"]["item_state"] == "passed"
        assert result["session"]["active"]["envelope"]["reference_solution"], "solução revelada após passar"

        advanced = await svc.next(session_id)
        assert advanced["finished"] is True
        assert engine.cleaned, "cleanup deve rodar ao avançar"

        finished = await svc.finish(session_id, reset="fast")
        assert finished["summary"]["passed"] == 1
        assert finished["cleanup"]["level"] == "L1"

    asyncio.run(scenario())


def test_skip_unlocks_next_and_is_counted(service) -> None:
    svc, engine = service

    async def scenario() -> None:
        session = await svc.create(1)
        session_id = session["session"]["id"]
        updated = await svc.skip(session_id)
        assert updated["active"]["item_state"] == "skipped"
        advanced = await svc.next(session_id)
        assert advanced["finished"] is True
        finished = await svc.finish(session_id, reset="baseline")
        assert finished["summary"]["passed"] == 0
        assert finished["summary"]["skipped"] == 1
        assert finished["cleanup"]["level"] == "L2-clean"

    asyncio.run(scenario())


def test_second_session_blocked_while_active(service) -> None:
    svc, _engine = service

    async def scenario() -> None:
        await svc.create(1)
        with pytest.raises(SessionError):
            await svc.create(1)

    asyncio.run(scenario())
