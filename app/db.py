"""SQLite (WAL) — durable schema and idempotent migrations for CKA Arena."""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app import config

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('study', 'mock_exam')),
    difficulty_filter TEXT,
    domains_json TEXT NOT NULL DEFAULT '[]',
    sample_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    started_at REAL NOT NULL,
    finished_at REAL,
    total_weight INTEGER NOT NULL DEFAULT 0,
    earned_weight INTEGER NOT NULL DEFAULT 0,
    earned_weight_exact REAL,
    time_limit_minutes INTEGER,
    variant TEXT NOT NULL DEFAULT 'study',
    strict_psi INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bank_questions (
    id TEXT PRIMARY KEY,
    envelope_json TEXT NOT NULL,
    envelope_hash TEXT NOT NULL UNIQUE,
    title TEXT,
    domain TEXT NOT NULL,
    subtopics_json TEXT NOT NULL DEFAULT '[]',
    difficulty TEXT NOT NULL,
    weight_pct INTEGER NOT NULL,
    estimated_minutes REAL,
    source TEXT NOT NULL CHECK (source IN ('llm', 'seed')),
    state TEXT NOT NULL CHECK (state IN ('draft', 'probed', 'published', 'retired')),
    probe_result_json TEXT,
    times_used INTEGER NOT NULL DEFAULT 0,
    last_used_at REAL,
    first_try_pass_count INTEGER NOT NULL DEFAULT 0,
    avg_solve_seconds REAL,
    generator_meta_json TEXT,
    supersedes_question_id TEXT,
    retired_reason TEXT,
    created_at REAL NOT NULL,
    archetype_id TEXT,
    fingerprint TEXT,
    quality_score REAL,
    quality_report_json TEXT
);

CREATE TABLE IF NOT EXISTS session_items (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    bank_question_id TEXT NOT NULL REFERENCES bank_questions(id),
    order_index INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'active', 'passed', 'skipped')),
    started_at REAL,
    passed_at REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    flagged INTEGER NOT NULL DEFAULT 0,
    last_check_json TEXT,
    mounted_at REAL,
    earned_weight REAL NOT NULL DEFAULT 0,
    check_pass_ratio REAL NOT NULL DEFAULT 0,
    notes_text TEXT,
    checked_tasks_json TEXT,
    hints_used INTEGER NOT NULL DEFAULT 0,
    context_name TEXT,
    active_seconds REAL NOT NULL DEFAULT 0,
    last_entered_at REAL,
    context_switched INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS generation_requests (
    id TEXT PRIMARY KEY,
    request_json TEXT NOT NULL,
    status TEXT NOT NULL,
    scenarios_attempted INTEGER NOT NULL DEFAULT 0,
    scenarios_published INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS check_runs (
    id TEXT PRIMARY KEY,
    session_item_id TEXT NOT NULL REFERENCES session_items(id),
    ran_at REAL NOT NULL,
    all_passed INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    results_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_generations (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    stage TEXT,
    provider TEXT,
    model TEXT,
    prompt_params_json TEXT,
    attempts_used INTEGER NOT NULL DEFAULT 0,
    raw_response TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    job_id TEXT,
    duration_ms INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    reasoning_tokens INTEGER
);

CREATE TABLE IF NOT EXISTS terminal_sessions (
    id TEXT PRIMARY KEY,
    tab_id TEXT NOT NULL,
    preset TEXT NOT NULL CHECK (preset IN ('host', 'node')),
    node_name TEXT,
    session_item_id TEXT,
    created_at REAL NOT NULL,
    last_activity REAL,
    closed_at REAL,
    exit_status INTEGER
);

CREATE TABLE IF NOT EXISTS command_audit (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    session_item_id TEXT,
    command_text TEXT NOT NULL,
    ran_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS archetype_mastery (
    archetype_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    passes INTEGER NOT NULL DEFAULT 0,
    first_try_passes INTEGER NOT NULL DEFAULT 0,
    ewma_solve_ratio REAL,
    mastery_score REAL NOT NULL DEFAULT 0,
    last_practiced_at REAL,
    next_review_at REAL,
    interval_days REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS study_progress (
    topic_id TEXT PRIMARY KEY,
    theory_done INTEGER NOT NULL DEFAULT 0,
    practice_done INTEGER NOT NULL DEFAULT 0,
    cheatsheet_done INTEGER NOT NULL DEFAULT 0,
    quiz_passed INTEGER NOT NULL DEFAULT 0,
    quiz_passed_mask INTEGER NOT NULL DEFAULT 0,
    quiz_attempts INTEGER NOT NULL DEFAULT 0,
    xp_earned INTEGER NOT NULL DEFAULT 0,
    completed_at REAL,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS study_activity (
    day TEXT PRIMARY KEY,
    xp_gained INTEGER NOT NULL DEFAULT 0,
    actions_count INTEGER NOT NULL DEFAULT 0,
    topics_completed INTEGER NOT NULL DEFAULT 0,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS user_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS question_feedback (
    id TEXT PRIMARY KEY,
    bank_question_id TEXT NOT NULL,
    archetype_id TEXT,
    reason_code TEXT NOT NULL,
    note TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_items_session ON session_items(session_id, order_index);
CREATE INDEX IF NOT EXISTS idx_bank_cell ON bank_questions(domain, difficulty, state);
CREATE INDEX IF NOT EXISTS idx_check_runs_item ON check_runs(session_item_id, ran_at);
CREATE INDEX IF NOT EXISTS idx_command_audit_item ON command_audit(session_item_id, ran_at);
CREATE INDEX IF NOT EXISTS idx_question_feedback_arch ON question_feedback(archetype_id, created_at);
"""

_MIGRATIONS: tuple[str, ...] = (
    "ALTER TABLE bank_questions ADD COLUMN title TEXT",
    "ALTER TABLE bank_questions ADD COLUMN archetype_id TEXT",
    "ALTER TABLE bank_questions ADD COLUMN fingerprint TEXT",
    "ALTER TABLE bank_questions ADD COLUMN quality_score REAL",
    "ALTER TABLE bank_questions ADD COLUMN quality_report_json TEXT",
    "ALTER TABLE sessions ADD COLUMN time_limit_minutes INTEGER",
    "ALTER TABLE sessions ADD COLUMN variant TEXT NOT NULL DEFAULT 'study'",
    "ALTER TABLE sessions ADD COLUMN earned_weight_exact REAL",
    "ALTER TABLE sessions ADD COLUMN strict_psi INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE session_items ADD COLUMN flagged INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE session_items ADD COLUMN last_check_json TEXT",
    "ALTER TABLE session_items ADD COLUMN mounted_at REAL",
    "ALTER TABLE session_items ADD COLUMN earned_weight REAL NOT NULL DEFAULT 0",
    "ALTER TABLE session_items ADD COLUMN check_pass_ratio REAL NOT NULL DEFAULT 0",
    "ALTER TABLE session_items ADD COLUMN notes_text TEXT",
    "ALTER TABLE session_items ADD COLUMN checked_tasks_json TEXT",
    "ALTER TABLE session_items ADD COLUMN hints_used INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE session_items ADD COLUMN context_name TEXT",
    "ALTER TABLE session_items ADD COLUMN active_seconds REAL NOT NULL DEFAULT 0",
    "ALTER TABLE session_items ADD COLUMN last_entered_at REAL",
    "ALTER TABLE session_items ADD COLUMN context_switched INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE llm_generations ADD COLUMN job_id TEXT",
    "ALTER TABLE llm_generations ADD COLUMN duration_ms INTEGER",
    "ALTER TABLE llm_generations ADD COLUMN prompt_tokens INTEGER",
    "ALTER TABLE llm_generations ADD COLUMN completion_tokens INTEGER",
    "ALTER TABLE llm_generations ADD COLUMN reasoning_tokens INTEGER",
    "ALTER TABLE study_progress ADD COLUMN quiz_passed_mask INTEGER NOT NULL DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS idx_bank_fingerprint ON bank_questions(fingerprint, state)",
    "CREATE INDEX IF NOT EXISTS idx_command_audit_item ON command_audit(session_item_id, ran_at)",
    "CREATE INDEX IF NOT EXISTS idx_question_feedback_arch ON question_feedback(archetype_id, created_at)",
)

_WAL_INITIALIZED: set[Path] = set()


def db_path() -> Path:
    return config.DATA_DIR / "cka_arena.db"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if path not in _WAL_INITIALIZED:
        conn.execute("PRAGMA journal_mode=WAL")
        _WAL_INITIALIZED.add(path)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(auto_restore: bool = True) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = db_path()
    if (
        auto_restore
        and not target.exists()
        and config.DATA_DIR.resolve() == (config.BASE_DIR / "data").resolve()
        and config.BACKUP_DB_PATH.is_file()
    ):
        tmp_target = target.with_name(f".{target.name}.{os.getpid()}.restore.tmp")
        try:
            shutil.copy2(config.BACKUP_DB_PATH, tmp_target)
            os.replace(tmp_target, target)
            _WAL_INITIALIZED.discard(target)
            logger.info("Restored initial database from %s", config.BACKUP_DB_PATH)
        finally:
            if tmp_target.exists():
                try:
                    tmp_target.unlink()
                except OSError:
                    pass
    with connect() as conn:
        conn.executescript(SCHEMA)
        for stmt in _MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        conn.execute(
            "UPDATE bank_questions SET title = json_extract(envelope_json, '$.title')"
            " WHERE title IS NULL"
        )
        conn.execute(
            "UPDATE bank_questions SET archetype_id = json_extract(envelope_json, '$.archetype_id')"
            " WHERE archetype_id IS NULL AND json_valid(envelope_json)"
        )
