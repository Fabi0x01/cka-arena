"""Question bank — semantic hashing, dedup, exam sampling, telemetry, and curation."""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
import time
import unicodedata
import uuid

from app import curriculum, db
from app.models import ScenarioEnvelope

# Official CNCF CKA domain weights (LLM_PIPELINE_SPEC §4)
WEIGHTS: dict[str, int] = {
    "Troubleshooting": 30,
    "Cluster Architecture, Installation & Configuration": 25,
    "Services & Networking": 20,
    "Workloads & Scheduling": 15,
    "Storage": 10,
}


def normalize_title(title: str) -> str:
    decomposed = unicodedata.normalize("NFD", title.lower())
    ascii_title = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    cleaned = "".join(ch if ch.isalnum() else " " for ch in ascii_title)
    return " ".join(cleaned.split())


def envelope_hash(env: ScenarioEnvelope) -> str:
    material = {
        "domain": env.domain,
        "subtopics": sorted(env.subtopics),
        "title": normalize_title(env.title),
        "setup": sorted(hashlib.sha256(m.encode()).hexdigest() for m in env.setup.manifests),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def structural_fingerprint(env: ScenarioEnvelope) -> str:
    material = {
        "domain": env.domain,
        "difficulty": env.difficulty,
        "archetype_id": env.archetype_id or "",
        "title": normalize_title(env.title),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def publish_question(
    env: ScenarioEnvelope,
    *,
    source: str = "seed",
    state: str = "published",
    probe_result: dict | None = None,
    generator_meta: dict | None = None,
    quality_score: int | None = None,
    quality_report: dict | None = None,
) -> dict:
    digest = envelope_hash(env)
    fp = structural_fingerprint(env)
    now = time.time()
    q_report_str = json.dumps(quality_report) if quality_report is not None else None
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT id, state, archetype_id, envelope_json FROM bank_questions WHERE envelope_hash = ?",
            (digest,),
        ).fetchone()
        if existing:
            # Upgrade an existing draft with the same hash if now verified for publication
            if existing["state"] == "draft" and state == "published":
                conn.execute(
                    "UPDATE bank_questions SET envelope_json = ?, title = ?, state = 'published',"
                    " probe_result_json = ?, generator_meta_json = ?, archetype_id = ?, fingerprint = ?,"
                    " quality_score = COALESCE(?, quality_score),"
                    " quality_report_json = COALESCE(?, quality_report_json)"
                    " WHERE id = ?",
                    (
                        env.model_dump_json(),
                        env.title,
                        json.dumps(probe_result) if probe_result else None,
                        json.dumps(generator_meta) if generator_meta else None,
                        env.archetype_id,
                        fp,
                        quality_score,
                        q_report_str,
                        existing["id"],
                    ),
                )
                return {"id": existing["id"], "created": True, "upgraded": True}
            if source == "seed" and existing["state"] == "published":
                try:
                    prev_env = json.loads(existing["envelope_json"] or "{}")
                except ValueError:
                    prev_env = {}
                needs_refresh = (
                    (env.archetype_id and existing["archetype_id"] != env.archetype_id)
                    or (env.hints and not prev_env.get("hints"))
                    or (env.fast_solution_commands and not prev_env.get("fast_solution_commands"))
                    or (env.schema_version != prev_env.get("schema_version"))
                    or (env.model_dump() != prev_env)
                )
                if needs_refresh:
                    conn.execute(
                        "UPDATE bank_questions SET envelope_json = ?, archetype_id = ?, fingerprint = ?,"
                        " title = ?, difficulty = ?, weight_pct = ?, estimated_minutes = ? WHERE id = ?",
                        (
                            env.model_dump_json(),
                            env.archetype_id,
                            fp,
                            env.title,
                            env.difficulty,
                            env.weight,
                            env.estimated_minutes,
                            existing["id"],
                        ),
                    )
            return {"id": existing["id"], "created": False}

        if source == "seed" and state == "published":
            seed_row = conn.execute(
                "SELECT id, envelope_hash, envelope_json FROM bank_questions"
                " WHERE source = 'seed' AND json_extract(envelope_json, '$.id') = ?",
                (env.id,),
            ).fetchone()
            if seed_row:
                if seed_row["envelope_hash"] != digest or seed_row["envelope_json"] != env.model_dump_json():
                    conn.execute(
                        "UPDATE bank_questions SET envelope_json = ?, envelope_hash = ?, fingerprint = ?,"
                        " title = ?, domain = ?, subtopics_json = ?, difficulty = ?, weight_pct = ?,"
                        " estimated_minutes = ?, archetype_id = ? WHERE id = ?",
                        (
                            env.model_dump_json(),
                            digest,
                            fp,
                            env.title,
                            env.domain,
                            json.dumps(env.subtopics),
                            env.difficulty,
                            env.weight,
                            env.estimated_minutes,
                            env.archetype_id,
                            seed_row["id"],
                        ),
                    )
                return {"id": seed_row["id"], "created": False}

        if state == "published":
            dup = conn.execute(
                "SELECT id FROM bank_questions WHERE fingerprint = ? AND state = 'published'",
                (fp,),
            ).fetchone()
            if dup:
                return {"id": dup["id"], "created": False, "dedup": "fingerprint"}

        question_id = f"q-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO bank_questions (id, envelope_json, envelope_hash, title, domain,"
            " subtopics_json, difficulty, weight_pct, estimated_minutes, source, state, created_at,"
            " probe_result_json, generator_meta_json, archetype_id, fingerprint,"
            " quality_score, quality_report_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                question_id,
                env.model_dump_json(),
                digest,
                env.title,
                env.domain,
                json.dumps(env.subtopics),
                env.difficulty,
                env.weight,
                env.estimated_minutes,
                source,
                state,
                now,
                json.dumps(probe_result) if probe_result else None,
                json.dumps(generator_meta) if generator_meta else None,
                env.archetype_id,
                fp,
                quality_score,
                q_report_str,
            ),
        )
    return {"id": question_id, "created": True}


def coverage() -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT domain, difficulty, COUNT(*) AS n FROM bank_questions"
            " WHERE state = 'published' GROUP BY domain, difficulty ORDER BY domain, difficulty"
        ).fetchall()
    return [{"domain": row["domain"], "difficulty": row["difficulty"], "published": row["n"]}
            for row in rows]


def count_published() -> int:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM bank_questions WHERE state = 'published'"
        ).fetchone()
    return int(row["n"])


def state_counts() -> dict[str, int]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT state, COUNT(*) AS n FROM bank_questions GROUP BY state"
        ).fetchall()
    counts = {"published": 0, "draft": 0, "probed": 0, "retired": 0}
    for row in rows:
        counts[row["state"]] = int(row["n"])
    return counts


def recent_published(limit: int = 40) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, title, domain, difficulty, archetype_id, generator_meta_json"
            " FROM bank_questions WHERE state = 'published'"
            " ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_questions(
    *,
    state: str | None = None,
    domain: str | None = None,
    difficulty: str | None = None,
    source: str | None = None,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    clauses = ["1=1"]
    params: list = []
    if state:
        clauses.append("state = ?")
        params.append(state)
    if domain:
        clauses.append("domain = ?")
        params.append(domain)
    if difficulty:
        clauses.append("difficulty = ?")
        params.append(difficulty)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if query:
        clauses.append("(LOWER(COALESCE(title, '')) LIKE ? OR LOWER(subtopics_json) LIKE ?)")
        like = f"%{query.strip().lower()}%"
        params.extend([like, like])
    where = " AND ".join(clauses)
    with db.connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM bank_questions WHERE {where}", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"SELECT id, title, domain, difficulty, weight_pct, estimated_minutes,"
            f" source, state, times_used, last_used_at, first_try_pass_count,"
            f" avg_solve_seconds, archetype_id, retired_reason, created_at, probe_result_json,"
            f" quality_score"
            f" FROM bank_questions WHERE {where}"
            f" ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, max(1, min(500, limit)), max(0, offset)),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        pr_raw = item.pop("probe_result_json", None)
        if pr_raw:
            try:
                pr = json.loads(pr_raw)
                item["probe_error"] = (pr.get("error") or "")[:300]
            except ValueError:
                item["probe_error"] = None
        else:
            item["probe_error"] = None
        items.append(item)
    return {"total": int(total), "items": items, "counts": state_counts()}


def get_question(question_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM bank_questions WHERE id = ?", (question_id,)
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    for field in (
        "envelope_json",
        "probe_result_json",
        "generator_meta_json",
        "subtopics_json",
        "quality_report_json",
    ):
        raw = data.get(field)
        if raw:
            try:
                data[field.replace("_json", "")] = json.loads(raw)
            except ValueError:
                data[field.replace("_json", "")] = None
        else:
            data[field.replace("_json", "")] = None
    return data


def retire_question(question_id: str, reason: str = "retired by user") -> bool:
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE bank_questions SET state = 'retired', retired_reason = ? WHERE id = ?",
            (reason.strip()[:300] or "retired", question_id),
        )
    return cur.rowcount > 0


def delete_question(question_id: str) -> tuple[bool, str]:
    with db.connect() as conn:
        used = conn.execute(
            "SELECT COUNT(*) AS n FROM session_items WHERE bank_question_id = ?",
            (question_id,),
        ).fetchone()["n"]
        if used:
            return False, "question is referenced by past sessions (retire it instead)"
        cur = conn.execute("DELETE FROM bank_questions WHERE id = ?", (question_id,))
        if cur.rowcount == 0:
            return False, "question not found"
    return True, ""


def update_after_probe(
    question_id: str,
    env: ScenarioEnvelope,
    *,
    state: str,
    probe_result: dict | None = None,
    quality_score: int | None = None,
    quality_report: dict | None = None,
) -> bool:
    digest = envelope_hash(env)
    fp = structural_fingerprint(env)
    q_report_str = json.dumps(quality_report) if quality_report is not None else None
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE bank_questions SET envelope_json = ?, envelope_hash = ?, title = ?,"
            " state = ?, probe_result_json = ?, retired_reason = NULL, archetype_id = ?, fingerprint = ?,"
            " quality_score = COALESCE(?, quality_score),"
            " quality_report_json = COALESCE(?, quality_report_json)"
            " WHERE id = ?",
            (
                env.model_dump_json(),
                digest,
                env.title,
                state,
                json.dumps(probe_result) if probe_result else None,
                env.archetype_id,
                fp,
                quality_score,
                q_report_str,
                question_id,
            ),
        )
    return cur.rowcount > 0


def record_feedback(
    question_id: str,
    reason_code: str,
    note: str = "",
    *,
    archetype_id: str | None = None,
) -> dict:
    """Persist structured question quality feedback for future Planner pitfall avoidance."""
    clean_code = (reason_code or "other").strip().lower()[:40]
    clean_note = (note or "").strip()[:400]
    with db.connect() as conn:
        if not archetype_id:
            row = conn.execute(
                "SELECT archetype_id FROM bank_questions WHERE id = ?", (question_id,)
            ).fetchone()
            archetype_id = row["archetype_id"] if row else None
        fid = f"qf-{uuid.uuid4().hex[:10]}"
        conn.execute(
            "INSERT INTO question_feedback (id, bank_question_id, archetype_id, reason_code, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (fid, question_id, archetype_id, clean_code, clean_note or None, time.time()),
        )
    return {"id": fid, "bank_question_id": question_id, "archetype_id": archetype_id, "reason_code": clean_code}


def recent_feedback_pitfalls(limit: int = 40) -> dict[str, list[str]]:
    """Return recent user-reported pitfalls grouped by archetype_id for SlotPlanner."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT archetype_id, reason_code, note FROM question_feedback"
            " WHERE archetype_id IS NOT NULL AND archetype_id != ''"
            " ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    grouped: dict[str, list[str]] = {}
    for row in rows:
        aid = row["archetype_id"]
        msg = row["reason_code"] + (f": {row['note']}" if row["note"] else "")
        bucket = grouped.setdefault(aid, [])
        if msg not in bucket and len(bucket) < 5:
            bucket.append(msg)
    return grouped


def record_usage(question_id: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE bank_questions SET times_used = times_used + 1, last_used_at = ?"
            " WHERE id = ?",
            (time.time(), question_id),
        )


def record_pass(question_id: str, solve_seconds: float, *, first_try: bool) -> None:
    solve_seconds = max(1.0, float(solve_seconds))
    with db.connect() as conn:
        row = conn.execute(
            "SELECT avg_solve_seconds, first_try_pass_count FROM bank_questions WHERE id = ?",
            (question_id,),
        ).fetchone()
        if not row:
            return
        prev_avg = row["avg_solve_seconds"]
        passed_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM session_items WHERE bank_question_id = ? AND state = 'passed'",
            (question_id,),
        ).fetchone()["n"]
        n = max(1, int(passed_rows))
        if prev_avg is None:
            new_avg = solve_seconds
        else:
            new_avg = ((float(prev_avg) * max(0, n - 1)) + solve_seconds) / n
        ftp_inc = 1 if first_try else 0
        conn.execute(
            "UPDATE bank_questions SET avg_solve_seconds = ?, first_try_pass_count = first_try_pass_count + ?"
            " WHERE id = ?",
            (round(new_avg, 1), ftp_inc, question_id),
        )


def largest_remainder(total: int, weights: dict[str, int]) -> dict[str, int]:
    """Integer allocation by largest remainder (tie-break: higher weight, then name)."""
    if not weights or total <= 0:
        return {}
    weight_sum = sum(weights.values())
    raw = {domain: total * weight / weight_sum for domain, weight in weights.items()}
    allocation = {domain: int(math.floor(value)) for domain, value in raw.items()}
    remaining = total - sum(allocation.values())
    order = sorted(
        weights,
        key=lambda domain: (raw[domain] - allocation[domain], weights[domain], domain),
        reverse=True,
    )
    for domain in order[:remaining]:
        allocation[domain] += 1
    return allocation


def draw_exam_sample(
    count: int,
    *,
    domains: list[str] | None = None,
    difficulty: str | None = None,
    allow_destructive: bool = False,
    ensure_disjoint_namespaces: bool = False,
    strategy: str = "exam_balanced",
    archetype_id: str | None = None,
) -> dict:
    """Draw questions by official exam percentages, adaptive pedagogy, or disjoint live mock namespaces."""
    eligible = domains or list(WEIGHTS)
    eligible = [domain for domain in eligible if domain in WEIGHTS]
    weights = {domain: WEIGHTS[domain] for domain in eligible}
    allocation = largest_remainder(count, weights)
    now = time.time()

    with db.connect() as conn:
        raw_rows = conn.execute(
            "SELECT id, domain, difficulty, weight_pct, weight_pct AS weight,"
            " estimated_minutes,"
            " COALESCE(title, json_extract(envelope_json, '$.title')) AS title,"
            " times_used, archetype_id,"
            " CASE WHEN json_valid(envelope_json)"
            "   THEN json_extract(envelope_json, '$.setup.namespaces') ELSE '[]' END AS setup_ns_json,"
            " CASE WHEN json_valid(envelope_json)"
            "   THEN json_extract(envelope_json, '$.setup.node_commands') ELSE '[]' END AS node_cmds_json,"
            " COALESCE(CASE WHEN json_valid(envelope_json)"
            "   THEN json_extract(envelope_json, '$.destructive') END, 0) AS destructive"
            " FROM bank_questions WHERE state = 'published'"
        ).fetchall()
        mastery_map = {
            r["archetype_id"]: dict(r)
            for r in conn.execute("SELECT archetype_id, mastery_score, next_review_at FROM archetype_mastery").fetchall()
        }
        failed_qids = {
            r["bank_question_id"]
            for r in conn.execute(
                "SELECT DISTINCT bank_question_id FROM session_items WHERE state = 'skipped'"
                " OR (state != 'passed' AND attempts > 0)"
            ).fetchall()
        }

    rows: list[dict] = []
    for raw_r in raw_rows:
        item = dict(raw_r)
        if not allow_destructive and item.get("destructive"):
            continue
        if archetype_id and item.get("archetype_id") != archetype_id:
            continue
        try:
            ns_list = json.loads(item.pop("setup_ns_json") or "[]") or []
        except ValueError:
            ns_list = []
        try:
            nc_list = json.loads(item.pop("node_cmds_json") or "[]") or []
        except ValueError:
            nc_list = []
        item["_namespaces"] = {str(n) for n in ns_list if n}
        item["_nodes"] = {str(nc.get("node")) for nc in nc_list if isinstance(nc, dict) and nc.get("node")}
        rows.append(item)

    def sort_key(r: dict) -> tuple:
        aid = r.get("archetype_id")
        m = mastery_map.get(aid or "")
        due_rank = 0 if (m and m.get("next_review_at") and float(m["next_review_at"]) <= now) else 1
        m_score = float(m["mastery_score"]) if m else 50.0
        weak_rank = 0 if (m and m_score < 60.0) else 1
        unseen_rank = 0 if (aid and not m) else 1
        if strategy == "weakness_drill":
            return (due_rank, weak_rank, unseen_rank, round(m_score, 1), r["times_used"], random.random())
        if strategy == "mistake_replay":
            return (0 if r["id"] in failed_qids else 1, r["times_used"], round(m_score, 1), random.random())
        if strategy == "speed_blitz":
            est = float(r.get("estimated_minutes") or 5.0)
            return (0 if r["difficulty"] == "exam_standard" else 1, est, r["times_used"], random.random())
        return (r["times_used"], random.random())

    used_ids: set[str] = set()
    used_namespaces: set[str] = set()
    used_nodes: set[str] = set()
    used_archetypes: set[str] = set()
    use_diff_curve = ensure_disjoint_namespaces and count >= 10 and not difficulty and strategy == "exam_balanced"
    tier_targets: dict[str, int] = {}
    tier_counts: dict[str, int] = {"exam_standard": 0, "killer_hardcore": 0, "boss_fight": 0}
    if use_diff_curve:
        std_n = round(count * 0.60)
        hard_n = round(count * 0.30)
        boss_n = max(1, count - std_n - hard_n)
        tier_targets = {"exam_standard": std_n, "killer_hardcore": hard_n, "boss_fight": boss_n}

    def sort_with_curve(cands: list[dict]) -> list[dict]:
        if not use_diff_curve:
            return cands
        def _curve_key(r: dict) -> tuple:
            d = r.get("difficulty") or "exam_standard"
            deficit = tier_targets.get(d, 0) - tier_counts.get(d, 0)
            return (0 if deficit > 0 else 1, -deficit)
        return sorted(cands, key=_curve_key)

    def compatible(r: dict, *, strict_arch: bool = True) -> bool:
        if r["id"] in used_ids:
            return False
        if ensure_disjoint_namespaces:
            if used_namespaces & r["_namespaces"]:
                return False
            if used_nodes & r["_nodes"]:
                return False
        if strict_arch and r.get("archetype_id") and r["archetype_id"] in used_archetypes:
            return False
        return True

    def accept(r: dict) -> dict:
        used_ids.add(r["id"])
        tier_counts[r.get("difficulty") or "exam_standard"] = tier_counts.get(r.get("difficulty") or "exam_standard", 0) + 1
        if ensure_disjoint_namespaces:
            used_namespaces.update(r["_namespaces"])
            used_nodes.update(r["_nodes"])
        if r.get("archetype_id"):
            used_archetypes.add(r["archetype_id"])
        clean = {k: v for k, v in r.items() if not k.startswith("_")}
        return clean

    if archetype_id:
        cands = sorted(rows, key=sort_key)
        picks = [accept(r) for r in cands[:count]]
        return {
            "items": picks,
            "allocation": allocation,
            "difficulty": difficulty,
            "requested": count,
            "returned": len(picks),
            "fallbacks": [],
        }

    def pool(domain: str) -> list[dict]:
        candidates = [r for r in rows if r["domain"] == domain]
        if difficulty:
            candidates = [r for r in candidates if r["difficulty"] == difficulty]
        elif strategy == "speed_blitz":
            ez = [r for r in candidates if r["difficulty"] == "exam_standard"]
            if ez:
                candidates = ez
        return sorted(candidates, key=sort_key)

    picks: list[dict] = []
    fallbacks: list[dict] = []
    for domain, wanted in allocation.items():
        cands = sort_with_curve(pool(domain))
        taken: list[dict] = []
        for strict in (True, False):
            for r in sort_with_curve(cands):
                if len(taken) >= wanted:
                    break
                if compatible(r, strict_arch=strict):
                    taken.append(accept(r))
        picks.extend(taken)
        if len(taken) < wanted:
            fallbacks.append({"domain": domain, "missing": wanted - len(taken)})

    if len(picks) < count:
        rest = sorted(
            [r for r in rows if not difficulty or r["difficulty"] == difficulty],
            key=sort_key,
        )
        for strict in (True, False):
            for row in sort_with_curve(rest):
                if len(picks) >= count:
                    break
                if compatible(row, strict_arch=strict):
                    picks.append(accept(row))
                    fallbacks.append({"domain": row["domain"], "missing": 1, "filled_with": row["domain"]})

    return {
        "items": picks[:count],
        "allocation": allocation,
        "difficulty": difficulty,
        "requested": count,
        "returned": min(len(picks), count),
        "fallbacks": fallbacks,
    }


def prune_bank(*, apply: bool = False) -> dict:
    """Clean quarantined drafts, duplicate title clones, and legacy Frankenstein composer items."""
    with db.connect() as conn:
        draft_rows = conn.execute(
            "SELECT id FROM bank_questions WHERE state = 'draft'"
        ).fetchall()
        draft_ids = [r["id"] for r in draft_rows]

        pub_rows = conn.execute(
            "SELECT id, title, domain, difficulty, source, generator_meta_json, created_at"
            " FROM bank_questions WHERE state = 'published' ORDER BY created_at DESC"
        ).fetchall()

        composer_ids: list[str] = []
        duplicate_ids: list[str] = []
        seen_titles: set[tuple[str, str, str]] = set()
        for row in pub_rows:
            meta_raw = row["generator_meta_json"]
            if meta_raw:
                try:
                    meta = json.loads(meta_raw)
                    if meta.get("units"):
                        composer_ids.append(row["id"])
                        continue
                except ValueError:
                    pass
            key = (row["domain"], row["difficulty"], normalize_title(row["title"] or ""))
            if row["source"] == "seed":
                seen_titles.add(key)
                continue
            if key in seen_titles:
                duplicate_ids.append(row["id"])
            else:
                seen_titles.add(key)

        referenced = {
            r["bank_question_id"]
            for r in conn.execute("SELECT DISTINCT bank_question_id FROM session_items").fetchall()
        }
        deletable_drafts = [qid for qid in draft_ids if qid not in referenced]
        retirable_drafts = [qid for qid in draft_ids if qid in referenced]

        if apply:
            for qid in deletable_drafts:
                conn.execute("DELETE FROM bank_questions WHERE id = ?", (qid,))
            for qid in retirable_drafts:
                conn.execute(
                    "UPDATE bank_questions SET state = 'retired', retired_reason = 'pruned legacy draft' WHERE id = ?",
                    (qid,),
                )
            for qid in composer_ids:
                conn.execute(
                    "UPDATE bank_questions SET state = 'retired', retired_reason = 'pruned legacy composer frankenstein' WHERE id = ?",
                    (qid,),
                )
            for qid in duplicate_ids:
                conn.execute(
                    "UPDATE bank_questions SET state = 'retired', retired_reason = 'pruned duplicate clone' WHERE id = ?",
                    (qid,),
                )

    return {
        "applied": apply,
        "drafts_deleted": len(deletable_drafts),
        "drafts_retired": len(retirable_drafts),
        "composer_retired": len(composer_ids),
        "duplicates_retired": len(duplicate_ids),
    }


def audit_legacy_questions(*, apply: bool = False) -> dict:
    """Identify and optionally retire flawed LLM items across the published bank."""
    import re as _re

    spoiler_re = _re.compile(
        r"\bbecause\s+(?:of\s+)?(?:the\s+|its?\s+|a\s+|an\s+|wrong\s+|missing\s+|incorrect\s+)?(?:selector|container\s+command|image\s+tag|targetport|readiness\s*probe|liveness\s*probe|rolebinding|networkpolicy|port\s+mismatch|wrong\s+command|typo|missing\s+port)"
        r"|\bhas\s+(?:a\s+|an\s+)?(?:wrong\s+(?:selector|targetport|image|command|tag|rolebinding|mountpath)|typo\s+in|missing\s+(?:selector|label|port|volumemount))\b",
        _re.I,
    )
    cluster_check_types = {
        "clusterrole",
        "clusterrolebinding",
        "pv",
        "persistentvolume",
        "sc",
        "storageclass",
        "crd",
        "customresourcedefinition",
        "priorityclass",
        "csr",
        "certificatesigningrequest",
        "node_command_exit_zero",
    }
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, title, domain, difficulty, archetype_id, created_at, envelope_json"
            " FROM bank_questions WHERE source = 'llm' AND state = 'published'"
            " ORDER BY created_at DESC"
        ).fetchall()

        spoiler_ids: list[str] = []
        no_docs_ids: list[str] = []
        sn_excess_ids: list[str] = []
        weak_boss_ids: list[str] = []
        cluster_leak_ids: list[str] = []
        v11_ids: list[str] = []
        legacy_total = 0
        sn_seen = 0
        for r in rows:
            if not r["archetype_id"]:
                legacy_total += 1
            try:
                env = json.loads(r["envelope_json"])
            except ValueError:
                spoiler_ids.append(r["id"])
                continue
            symptom = str(env.get("prompt") or "").split("Perform the following tasks")[0]
            if spoiler_re.search(symptom):
                spoiler_ids.append(r["id"])
                continue
            if not env.get("docs_links"):
                no_docs_ids.append(r["id"])
                continue
            if (
                not r["archetype_id"]
                and r["domain"] == "Services & Networking"
                and r["difficulty"] == "exam_standard"
            ):
                sn_seen += 1
                if sn_seen > 4:
                    sn_excess_ids.append(r["id"])
                    continue
            if r["difficulty"] == "boss_fight":
                sol = env.get("solution") or {}
                nc = sol.get("node_commands") or []
                valid_nc = [
                    c for c in nc if isinstance(c, dict) and str(c.get("command") or "").strip() not in ("", "true", ":")
                ]
                has_setup_nc = bool((env.get("setup") or {}).get("node_commands"))
                if not valid_nc and not has_setup_nc and len(sol.get("commands") or []) < 2 and not sol.get("manifests"):
                    weak_boss_ids.append(r["id"])
                    continue
            # Check cluster-scoped cleanup completeness
            setup_ns = set((env.get("setup") or {}).get("namespaces") or [])
            cleanup_obj = env.get("cleanup") or {}
            cleanup_ns = set(cleanup_obj.get("namespaces") or [])
            has_cleanup_cmds = bool(cleanup_obj.get("commands") or cleanup_obj.get("node_commands"))
            for chk in env.get("checks") or []:
                params = chk.get("params") or {}
                kind = str(params.get("kind") or "").lower()
                if (
                    kind in cluster_check_types
                    and not has_cleanup_cmds
                    and not (cleanup_ns >= setup_ns and bool(setup_ns) and kind in ("clusterrole", "clusterrolebinding"))
                ):
                    if not (setup_ns and cleanup_obj.get("commands") is not None and has_cleanup_cmds):
                        # Only flag if cluster-scoped setup lacks any cleanup commands or teardown labels
                        setup_manifests = "\n".join(str(m) for m in ((env.get("setup") or {}).get("manifests") or []))
                        if not cleanup_obj.get("commands") and not ("labels:" in setup_manifests and "cka-arena/scenario" in setup_manifests):
                            if not setup_ns:
                                cluster_leak_ids.append(r["id"])
                                break
            if str(env.get("schema_version") or "") != "1.2" or len(env.get("hints") or []) < 2 or not env.get("fast_solution_commands"):
                v11_ids.append(r["id"])

        retire_map: dict[str, str] = {}
        for qid in sn_excess_ids:
            retire_map[qid] = "legacy audit: excess Services & Networking exam_standard clone/bloat"
        for qid in no_docs_ids:
            retire_map[qid] = "legacy audit: missing docs_links"
        for qid in weak_boss_ids:
            retire_map[qid] = "legacy audit: boss_fight lacks substantive fault/solution"
        for qid in cluster_leak_ids:
            retire_map[qid] = "legacy audit: cluster-scoped resource missing cleanup"
        for qid in spoiler_ids:
            retire_map[qid] = "legacy audit: symptom spoiler leak"

        if apply and retire_map:
            for qid, reason in retire_map.items():
                conn.execute(
                    "UPDATE bank_questions SET state = 'retired', retired_reason = ? WHERE id = ?",
                    (reason, qid),
                )

    return {
        "applied": apply,
        "scanned_total": len(rows),
        "legacy_total": legacy_total,
        "spoilers_flagged": len(spoiler_ids),
        "no_docs_flagged": len(no_docs_ids),
        "sn_excess_flagged": len(sn_excess_ids),
        "weak_boss_flagged": len(weak_boss_ids),
        "cluster_leak_flagged": len(cluster_leak_ids),
        "v11_flagged": len(v11_ids),
        "retired_count": len(retire_map),
    }


def backfill_archetypes() -> dict[str, int]:
    """Infer archetype_id for published questions and idempotently seed archetype_mastery."""
    from app import mastery

    questions_updated = 0
    mastery_seeded = 0

    with db.connect() as conn:
        null_rows = conn.execute(
            "SELECT id, domain, title, subtopics_json, envelope_json FROM bank_questions"
            " WHERE state = 'published' AND (archetype_id IS NULL OR archetype_id = '')"
        ).fetchall()
        for row in null_rows:
            try:
                subtopics = json.loads(row["subtopics_json"] or "[]")
            except ValueError:
                subtopics = []
            try:
                env_dict = json.loads(row["envelope_json"] or "{}")
            except ValueError:
                env_dict = {}
            inferred = curriculum.infer_archetype_id(
                row["domain"],
                row["title"],
                subtopics,
                env_dict.get("id"),
            )
            if not inferred:
                continue
            env_dict["archetype_id"] = inferred
            conn.execute(
                "UPDATE bank_questions SET archetype_id = ?, envelope_json = ? WHERE id = ?",
                (inferred, json.dumps(env_dict), row["id"]),
            )
            questions_updated += 1

        existing_mastered = {
            r["archetype_id"]
            for r in conn.execute(
                "SELECT archetype_id FROM archetype_mastery WHERE attempts > 0"
            ).fetchall()
        }
        hist_rows = conn.execute(
            "SELECT si.state, si.attempts, si.check_pass_ratio, si.started_at, si.passed_at,"
            " s.started_at AS session_started_at, b.archetype_id, b.domain, b.estimated_minutes"
            " FROM session_items si"
            " JOIN sessions s ON s.id = si.session_id"
            " JOIN bank_questions b ON b.id = si.bank_question_id"
            " WHERE si.state IN ('passed', 'skipped')"
            "   AND b.archetype_id IS NOT NULL AND b.archetype_id != ''"
            " ORDER BY COALESCE(si.passed_at, si.started_at, s.started_at) ASC"
        ).fetchall()

    for row in hist_rows:
        arch_id = row["archetype_id"]
        if arch_id in existing_mastered:
            continue
        passed = row["state"] == "passed"
        attempts = int(row["attempts"] or 0)
        start_ts = float(row["started_at"] or row["session_started_at"] or 0.0)
        end_ts = float(row["passed_at"] or start_ts)
        solve_s = (
            max(1.0, end_ts - start_ts)
            if end_ts > start_ts
            else float(row["estimated_minutes"] or 5.0) * 60.0
        )
        mastery.record_outcome(
            arch_id,
            row["domain"],
            passed=passed,
            first_try=(passed and attempts <= 1),
            solve_seconds=solve_s,
            estimated_minutes=float(row["estimated_minutes"] or 5.0),
            pass_ratio=float(row["check_pass_ratio"] or (1.0 if passed else 0.0)),
        )
        mastery_seeded += 1

    return {"questions_updated": questions_updated, "mastery_seeded": mastery_seeded}


def _main() -> None:
    args = sys.argv[1:]
    db.init_db()
    if args and args[0] == "prune":
        apply = "--apply" in args
        summary = prune_bank(apply=apply)
        print(json.dumps(summary, indent=2))
        return
    if args and args[0] == "audit":
        apply = "--apply" in args
        summary = audit_legacy_questions(apply=apply)
        print(json.dumps(summary, indent=2))
        return
    if args and args[0] == "backfill":
        print(json.dumps(backfill_archetypes(), indent=2))
        return
    print("usage: python -m app.bank <prune|audit|backfill> [--apply]")


if __name__ == "__main__":
    _main()
