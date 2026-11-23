"""Portable sanitized SQLite backup & restore for CKA Arena (no API keys)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from typing import Any

from app import config, db

EPHEMERAL_TABLES: tuple[str, ...] = (
    "terminal_sessions",
    "command_audit",
    "generation_requests",
    "llm_generations",
)

COUNT_QUERIES: tuple[tuple[str, str], ...] = (
    ("published_questions", "SELECT COUNT(*) FROM bank_questions WHERE state = 'published'"),
    ("total_bank_questions", "SELECT COUNT(*) FROM bank_questions"),
    ("study_progress", "SELECT COUNT(*) FROM study_progress"),
    ("study_activity", "SELECT COUNT(*) FROM study_activity"),
    ("archetype_mastery", "SELECT COUNT(*) FROM archetype_mastery"),
    ("sessions", "SELECT COUNT(*) FROM sessions"),
    ("session_items", "SELECT COUNT(*) FROM session_items"),
    ("check_runs", "SELECT COUNT(*) FROM check_runs"),
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_counts(conn: sqlite3.Connection) -> dict[str, int]:
    existing = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    counts: dict[str, int] = {}
    for key, query in COUNT_QUERIES:
        tbl = query.split(" FROM ", 1)[1].split(" ", 1)[0]
        if tbl in existing:
            counts[key] = int(conn.execute(query).fetchone()[0])
        else:
            counts[key] = 0
    return counts


def _cleanup_sidecars(db_file: Path) -> None:
    for suffix in ("-wal", "-shm"):
        side = Path(f"{db_file}{suffix}")
        if side.exists():
            try:
                side.unlink()
            except OSError:
                pass


def create_backup(
    src_path: Path | None = None,
    dst_path: Path | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Create a clean, portable, single-file SQLite snapshot + manifest.json."""
    src = src_path or db.db_path()
    dst = dst_path or config.BACKUP_DB_PATH
    manifest = manifest_path or config.BACKUP_MANIFEST_PATH

    if not src.is_file():
        raise FileNotFoundError(f"source database not found: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
    _cleanup_sidecars(tmp_path)
    if tmp_path.exists():
        tmp_path.unlink()

    try:
        src_conn = sqlite3.connect(src, timeout=15)
        tmp_conn = sqlite3.connect(tmp_path, timeout=15)
        try:
            src_conn.backup(tmp_conn)
        finally:
            src_conn.close()
            tmp_conn.close()

        snap = sqlite3.connect(tmp_path, timeout=15)
        try:
            snap.execute("PRAGMA journal_mode=DELETE")
            tables = {
                r[0]
                for r in snap.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
            if "sessions" in tables:
                snap.execute(
                    "UPDATE sessions SET status = 'finished',"
                    " finished_at = COALESCE(finished_at, started_at)"
                    " WHERE status = 'active'"
                )
            for tbl in EPHEMERAL_TABLES:
                if tbl in tables:
                    snap.execute(f'DELETE FROM "{tbl}"')
            snap.commit()
            snap.execute("VACUUM")
            counts = _collect_counts(snap)
        finally:
            snap.close()

        _cleanup_sidecars(tmp_path)
        os.replace(tmp_path, dst)
    finally:
        _cleanup_sidecars(tmp_path)
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    meta = {
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "db_file": dst.name,
        "size_bytes": dst.stat().st_size,
        "sha256": _sha256(dst),
        "ai_keys_included": False,
        "counts": counts,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    tmp_manifest = manifest.with_name(f".{manifest.name}.{os.getpid()}.tmp")
    tmp_manifest.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_manifest, manifest)
    return meta


def restore_backup(
    backup_path: Path | None = None,
    dst_path: Path | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Restore SQLite database from portable backup snapshot."""
    src = backup_path or config.BACKUP_DB_PATH
    dst = dst_path or db.db_path()

    if not src.is_file():
        return {"restored": False, "reason": "backup_not_found", "source": str(src)}
    if dst.exists() and not force:
        return {"restored": False, "reason": "target_exists", "target": str(dst)}

    dst.parent.mkdir(parents=True, exist_ok=True)
    backup_before: str | None = None
    if dst.exists() and force:
        bak = dst.with_name(f"{dst.name}.pre-restore-{int(time.time())}.bak")
        shutil.copy2(dst, bak)
        backup_before = str(bak)
        _cleanup_sidecars(dst)

    tmp_dst = dst.with_name(f".{dst.name}.{os.getpid()}.restore.tmp")
    try:
        shutil.copy2(src, tmp_dst)
        os.replace(tmp_dst, dst)
    finally:
        if tmp_dst.exists():
            try:
                tmp_dst.unlink()
            except OSError:
                pass

    _cleanup_sidecars(dst)
    db._WAL_INITIALIZED.discard(dst)

    if dst.resolve() == db.db_path().resolve():
        db.init_db(auto_restore=False)

    conn = sqlite3.connect(dst, timeout=15)
    try:
        counts = _collect_counts(conn)
    finally:
        conn.close()

    res: dict[str, Any] = {
        "restored": True,
        "source": str(src),
        "target": str(dst),
        "counts": counts,
    }
    if backup_before:
        res["pre_restore_backup"] = backup_before
    return res


def status_report(
    src_path: Path | None = None,
    backup_path: Path | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Return status of live database vs portable backup snapshot."""
    src = src_path or db.db_path()
    bak = backup_path or config.BACKUP_DB_PATH
    man = manifest_path or config.BACKUP_MANIFEST_PATH

    live_info: dict[str, Any] = {"exists": src.is_file(), "path": str(src)}
    if src.is_file():
        live_info["size_bytes"] = src.stat().st_size
        conn = sqlite3.connect(src, timeout=10)
        try:
            live_info["counts"] = _collect_counts(conn)
        finally:
            conn.close()

    bak_info: dict[str, Any] = {"exists": bak.is_file(), "path": str(bak)}
    if bak.is_file():
        bak_info["size_bytes"] = bak.stat().st_size
        bak_info["sha256"] = _sha256(bak)
        conn = sqlite3.connect(bak, timeout=10)
        try:
            bak_info["counts"] = _collect_counts(conn)
        finally:
            conn.close()

    manifest_data = json.loads(man.read_text(encoding="utf-8")) if man.is_file() else None
    return {"live": live_info, "backup": bak_info, "manifest": manifest_data}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "status"
    force = "--force" in args

    if cmd == "create":
        meta = create_backup()
        print(json.dumps(meta, indent=2))
        return 0
    if cmd == "restore":
        res = restore_backup(force=force)
        print(json.dumps(res, indent=2))
        return 0 if res.get("restored") else 1
    if cmd == "status":
        print(json.dumps(status_report(), indent=2))
        return 0

    print("usage: python -m app.backup [create | restore [--force] | status]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
