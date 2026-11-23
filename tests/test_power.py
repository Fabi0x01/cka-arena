"""Testes do ClusterPowerManager (estado passivo + guarda de job) com stubs."""

from __future__ import annotations

import asyncio

import pytest

from app import power as power_mod
from app.events import EventBroker
from app.power import ClusterPowerManager, JobActiveError


class StubDoctor:
    async def health(self) -> dict:
        return {"nodes_ready": 3}

    async def ensure_baseline_files(self, password=None) -> dict:
        return {}


def make_manager() -> ClusterPowerManager:
    return ClusterPowerManager(EventBroker(), StubDoctor())  # type: ignore[arg-type]


def test_detect_all_vms_stopped_is_off(monkeypatch) -> None:
    async def fake_list_vms():
        return {name: {"state": "Stopped", "ips": []} for name in ("controlplane", "node01", "node02")}

    monkeypatch.setattr(power_mod.ssh_runner, "list_vms", fake_list_vms)
    manager = make_manager()
    result = asyncio.run(manager.detect())
    assert result["state"] == "off"


def test_detect_daemon_down_when_multipass_fails(monkeypatch) -> None:
    async def failing_list_vms():
        raise RuntimeError("cannot connect to the multipass socket")

    monkeypatch.setattr(power_mod.ssh_runner, "list_vms", failing_list_vms)
    manager = make_manager()
    result = asyncio.run(manager.detect())
    assert result["state"] == "daemon_down"
    assert "multipass" in (result["detail"] or "")


def test_detect_running_but_api_down_is_degraded(monkeypatch) -> None:
    async def fake_list_vms():
        return {name: {"state": "Running", "ips": ["192.168.1.10"]} for name in ("controlplane", "node01", "node02")}

    async def not_ready():
        return False

    monkeypatch.setattr(power_mod.ssh_runner, "list_vms", fake_list_vms)
    monkeypatch.setattr(power_mod.cluster, "readyz", not_ready)
    manager = make_manager()
    result = asyncio.run(manager.detect())
    assert result["state"] == "degraded"


def test_start_action_rejects_concurrent_job() -> None:
    manager = make_manager()

    async def scenario() -> None:
        manager._active_job = {"id": "abc123", "action": "start", "started_at": 0.0}
        with pytest.raises(JobActiveError):
            await manager.start_action("start")

    asyncio.run(scenario())


def test_state_change_events_are_published() -> None:
    manager = make_manager()
    queue = manager.broker.subscribe()
    manager._set_state("starting", detail="boot")
    manager._set_state("starting", detail="boot again")  # sem mudança: não publica
    manager._set_state("ready", detail="done")
    messages = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [m["state"] for m in messages] == ["starting", "ready"]
    assert all(m["topic"] == "cluster.power.state_changed" for m in messages)
