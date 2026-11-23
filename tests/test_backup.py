"""Unit tests for sanitized portable SQLite backup & auto-restore."""

from __future__ import annotations

import json
import sqlite3

from app import backup, config, db, study


def _seed_sample_db() -> None:
    db.init_db(auto_restore=False)
    topic_id = study.TOPICS[0].id
    study.set_stage(topic_id, "theory", True)

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO bank_questions"
            " (id, envelope_json, envelope_hash, title, domain, difficulty, weight_pct, source, state, created_at, archetype_id, fingerprint)"
            " VALUES ('q-bak-1', '{}', 'eh1', 'Sample Q', 'Workloads & Scheduling', 'exam_standard', 8, 'llm', 'published', 1000.0, 'wl-hpa-autoscale', 'fp1')"
        )
        conn.execute(
            "INSERT INTO archetype_mastery (archetype_id, domain, attempts, passes, first_try_passes, mastery_score)"
            " VALUES ('wl-hpa-autoscale', 'Workloads & Scheduling', 3, 3, 2, 92.0)"
        )
        conn.execute(
            "INSERT INTO sessions (id, title, mode, status, started_at, total_weight, earned_weight)"
            " VALUES ('sess-1', 'Mock Run', 'study', 'active', 1000.0, 10, 5)"
        )
        conn.execute(
            "INSERT INTO session_items (id, session_id, bank_question_id, order_index, state, earned_weight)"
            " VALUES ('si-1', 'sess-1', 'q-bak-1', 0, 'pending', 8.0)"
        )
        conn.execute(
            "INSERT INTO check_runs (id, session_item_id, ran_at, all_passed, duration_ms, results_json)"
            " VALUES ('cr-1', 'si-1', 1001.0, 1, 120, '[]')"
        )
        # Ephemeral tables that must be scrubbed from portable backups
        conn.execute(
            "INSERT INTO generation_requests (id, request_json, status, created_at)"
            " VALUES ('req-1', '{}', 'done', 1000.0)"
        )
        conn.execute(
            "INSERT INTO llm_generations (id, created_at, stage, raw_response, status)"
            " VALUES ('gen-1', 1000.0, 'build', 'big raw trace', 'ok')"
        )
        conn.execute(
            "INSERT INTO command_audit (id, session_id, session_item_id, command_text, ran_at)"
            " VALUES ('ca-1', 'sess-1', 'si-1', 'k get pods', 1002.0)"
        )
        conn.execute(
            "INSERT INTO terminal_sessions (id, tab_id, preset, created_at)"
            " VALUES ('term-1', 'tab-1', 'host', 1000.0)"
        )


def test_create_backup_preserves_durable_data_and_scrubs_ephemeral(tmp_path) -> None:
    _seed_sample_db()
    bak_db = tmp_path / "backups" / "cka_arena_backup.db"
    man_path = tmp_path / "backups" / "manifest.json"

    meta = backup.create_backup(dst_path=bak_db, manifest_path=man_path)
    assert bak_db.is_file()
    assert man_path.is_file()
    assert meta["ai_keys_included"] is False
    assert meta["counts"]["published_questions"] == 1
    assert meta["counts"]["study_progress"] == 1
    assert meta["counts"]["study_activity"] == 1
    assert meta["counts"]["archetype_mastery"] == 1
    assert meta["counts"]["sessions"] == 1
    assert meta["counts"]["session_items"] == 1
    assert meta["counts"]["check_runs"] == 1

    conn = sqlite3.connect(bak_db)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
        assert conn.execute("SELECT status FROM sessions WHERE id = 'sess-1'").fetchone()[0] == "finished"
        for tbl in backup.EPHEMERAL_TABLES:
            assert conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0] == 0
    finally:
        conn.close()

    parsed = json.loads(man_path.read_text(encoding="utf-8"))
    assert parsed["sha256"] == meta["sha256"]


def test_restore_backup_and_first_boot_auto_restore(tmp_path, monkeypatch) -> None:
    _seed_sample_db()
    bak_db = tmp_path / "backups" / "cka_arena_backup.db"
    man_path = tmp_path / "backups" / "manifest.json"
    backup.create_backup(dst_path=bak_db, manifest_path=man_path)

    # Restore refuses overwrite without force=True
    refused = backup.restore_backup(backup_path=bak_db, force=False)
    assert refused["restored"] is False
    assert refused["reason"] == "target_exists"

    # Mutate live DB then force restore -> old data replaced and .bak kept
    with db.connect() as conn:
        conn.execute("DELETE FROM check_runs")
        conn.execute("DELETE FROM session_items")
        conn.execute("DELETE FROM bank_questions")
    forced = backup.restore_backup(backup_path=bak_db, force=True)
    assert forced["restored"] is True
    assert forced["counts"]["published_questions"] == 1
    assert forced["pre_restore_backup"].endswith(".bak")

    # Simulate a brand-new clone where BASE_DIR/data does not exist yet
    fresh_root = tmp_path / "fresh_clone"
    fresh_data = fresh_root / "data"
    monkeypatch.setattr(config, "BASE_DIR", fresh_root)
    monkeypatch.setattr(config, "DATA_DIR", fresh_data)
    monkeypatch.setattr(config, "BACKUP_DB_PATH", bak_db)
    db._WAL_INITIALIZED.clear()

    db.init_db(auto_restore=True)
    assert (fresh_data / "cka_arena.db").is_file()
    overview = study.get_overview()
    assert overview["total_xp"] == 25

    # Skip auto-restore if DATA_DIR points outside BASE_DIR/data (e.g. test isolation)
    isolated_data = tmp_path / "isolated_data"
    monkeypatch.setattr(config, "DATA_DIR", isolated_data)
    db._WAL_INITIALIZED.clear()
    db.init_db(auto_restore=True)
    assert study.get_overview()["total_xp"] == 0
