"""Testes da telemetria por domínio (DB temporário)."""

from __future__ import annotations

import time

from app import bank, config, db, telemetry
from app.models import ScenarioEnvelope
import json


def test_telemetry_summary_and_recommendation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init_db()
    envelope = ScenarioEnvelope.model_validate(
        json.loads((config.BASE_DIR / "scenarios" / "seed" / "ts-crashloop-fix.json").read_text())
    )
    published = bank.publish_question(envelope, source="seed")
    now = time.time()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, mode, status, started_at, finished_at)"
            " VALUES ('s-1', 'Practice 1', 'study', 'finished', ?, ?)",
            (now - 600, now),
        )
        conn.execute(
            "INSERT INTO session_items (id, session_id, bank_question_id, order_index, state,"
            " started_at, passed_at, attempts) VALUES ('si-1', 's-1', ?, 0, 'passed', ?, ?, 1)",
            (published["id"], now - 300, now - 60),
        )
        conn.execute(
            "INSERT INTO check_runs (id, session_item_id, ran_at, all_passed, duration_ms, results_json)"
            " VALUES ('cr-1', 'si-1', ?, 1, 100, '[]')",
            (now - 200,),
        )

    data = telemetry.summary()
    assert data["sessions"] == {"total": 1, "finished": 1}
    assert data["check_runs"] == 1
    troubleshooting = data["per_domain"]["Troubleshooting"]
    assert troubleshooting["passed"] == 1
    assert troubleshooting["first_try_passes"] == 1
    assert troubleshooting["accuracy_pct"] == 100
    assert troubleshooting["avg_minutes"] == 4.0
    # Como o único domínio praticado está 100%, a recomendação cai em um domínio sem cobertura
    assert data["recommendation"]["domain"] in {
        "Cluster Architecture, Installation & Configuration",
        "Services & Networking",
        "Workloads & Scheduling",
        "Storage",
    }
