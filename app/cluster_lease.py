"""ClusterLease — mutual exclusion between active practice, AI generation, reset, and power."""

from __future__ import annotations

from dataclasses import dataclass


class ClusterBusyError(RuntimeError):
    def __init__(self, owner: str, detail: str) -> None:
        super().__init__(detail)
        self.owner = owner
        self.detail = detail


@dataclass
class ClusterLease:
    """Inspect live runtime managers to prevent destructive cluster collisions."""

    power: object | None = None
    pipeline: object | None = None
    sessions: object | None = None
    app_state: object | None = None

    def _power_busy(self) -> str | None:
        if self.power and getattr(self.power, "_active_job", None):
            return f"cluster power job ({self.power._active_job.get('action')}) is running"
        return None

    def _reset_busy(self) -> str | None:
        if self.app_state and getattr(self.app_state, "reset_running", False):
            return "clean reset (L2) is currently running"
        return None

    def _generation_busy(self) -> str | None:
        if self.pipeline and getattr(self.pipeline, "active_job_id", None):
            return f"AI generation job ({self.pipeline.active_job_id}) is running"
        return None

    def _session_busy(self) -> str | None:
        if self.sessions and self.sessions.active_session_id():
            return f"practice session ({self.sessions.active_session_id()}) is active"
        return None

    def ensure_for_generation(self) -> None:
        for check in (self._power_busy, self._reset_busy, self._session_busy):
            msg = check()
            if msg:
                raise ClusterBusyError("cluster_busy", f"cannot generate now: {msg}")

    def ensure_for_practice(self) -> None:
        for check in (self._power_busy, self._reset_busy, self._generation_busy):
            msg = check()
            if msg:
                raise ClusterBusyError("cluster_busy", f"cannot start practice now: {msg}")

    def ensure_for_reset(self) -> None:
        for check in (self._power_busy, self._generation_busy, self._session_busy):
            msg = check()
            if msg:
                raise ClusterBusyError("cluster_busy", f"cannot reset cluster now: {msg}")

    def ensure_for_power(self, action: str) -> None:
        if action in ("stop", "restart"):
            for check in (self._reset_busy, self._generation_busy):
                msg = check()
                if msg:
                    raise ClusterBusyError("cluster_busy", f"cannot {action} cluster now: {msg}")
