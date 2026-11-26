"""Pedagogical Mastery, Spaced Repetition (SRS), CKA Readiness Score, and Speed Coach."""

from __future__ import annotations

import json
import math
import statistics
import time

from app import curriculum, db
from app.models import DOMAINS, ScenarioEnvelope

CNCF_WEIGHTS = {
    "Troubleshooting": 30,
    "Cluster Architecture, Installation & Configuration": 25,
    "Services & Networking": 20,
    "Workloads & Scheduling": 15,
    "Storage": 10,
}


def record_outcome(
    archetype_id: str | None,
    domain: str,
    *,
    passed: bool,
    first_try: bool,
    solve_seconds: float,
    estimated_minutes: float,
    pass_ratio: float = 1.0,
) -> None:
    """Update SM-2 spaced repetition state and mastery score for an archetype."""
    if not archetype_id:
        return
    now = time.time()
    target_seconds = max(60.0, float(estimated_minutes or 5.0) * 60.0)
    solve_ratio = max(0.15, float(solve_seconds) / target_seconds)

    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM archetype_mastery WHERE archetype_id = ?", (archetype_id,)
        ).fetchone()
        if row:
            attempts = int(row["attempts"]) + 1
            passes = int(row["passes"]) + (1 if passed else 0)
            ftp = int(row["first_try_passes"]) + (1 if (passed and first_try) else 0)
            prev_ewma = row["ewma_solve_ratio"]
            ewma = solve_ratio if prev_ewma is None else (0.65 * float(prev_ewma) + 0.35 * solve_ratio)
            prev_interval = float(row["interval_days"] or 1.0)
        else:
            attempts = 1
            passes = 1 if passed else 0
            ftp = 1 if (passed and first_try) else 0
            ewma = solve_ratio
            prev_interval = 1.0

        if passed and solve_ratio <= 1.5:
            interval = min(30.0, max(1.0, prev_interval * (2.2 if first_try else 1.5)))
        elif passed:
            interval = min(7.0, max(1.0, prev_interval * 1.1))
        else:
            interval = 0.25  # due in 6 hours

        next_review = now + interval * 86400.0
        pass_component = (passes / attempts) * 70.0
        ftp_component = (ftp / attempts) * 15.0
        speed_component = max(0.0, min(15.0, (1.4 - ewma) * 25.0))
        raw_score = pass_component + ftp_component + speed_component
        if not passed:
            raw_score = min(raw_score, 40.0 + 25.0 * max(0.0, min(1.0, pass_ratio)))
        score = round(max(0.0, min(100.0, raw_score)), 1)

        conn.execute(
            "INSERT INTO archetype_mastery"
            " (archetype_id, domain, attempts, passes, first_try_passes,"
            "  ewma_solve_ratio, mastery_score, last_practiced_at, next_review_at, interval_days)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(archetype_id) DO UPDATE SET"
            "  domain = excluded.domain,"
            "  attempts = excluded.attempts,"
            "  passes = excluded.passes,"
            "  first_try_passes = excluded.first_try_passes,"
            "  ewma_solve_ratio = excluded.ewma_solve_ratio,"
            "  mastery_score = excluded.mastery_score,"
            "  last_practiced_at = excluded.last_practiced_at,"
            "  next_review_at = excluded.next_review_at,"
            "  interval_days = excluded.interval_days",
            (
                archetype_id,
                domain,
                attempts,
                passes,
                ftp,
                round(ewma, 3),
                score,
                now,
                next_review,
                round(interval, 2),
            ),
        )


def skill_tree() -> list[dict]:
    """Return 5 domains × all curriculum archetypes with mastery & published bank counts."""
    now = time.time()
    with db.connect() as conn:
        mastery_rows = {
            r["archetype_id"]: dict(r)
            for r in conn.execute("SELECT * FROM archetype_mastery").fetchall()
        }
        pub_rows = {
            r["archetype_id"]: int(r["n"])
            for r in conn.execute(
                "SELECT archetype_id, COUNT(*) AS n FROM bank_questions"
                " WHERE state = 'published' AND archetype_id IS NOT NULL"
                " GROUP BY archetype_id"
            ).fetchall()
        }

    ordered_domains = sorted(DOMAINS, key=lambda d: -CNCF_WEIGHTS.get(d, 0))
    tree: list[dict] = []
    for domain in ordered_domains:
        nodes: list[dict] = []
        for arch in curriculum.ARCHETYPES:
            if arch.domain != domain:
                continue
            m = mastery_rows.get(arch.id)
            if not m or int(m["attempts"]) == 0:
                status = "unseen"
                score = 0.0
                attempts = 0
                passes = 0
                ratio = None
                next_review = None
            else:
                score = float(m["mastery_score"] or 0.0)
                attempts = int(m["attempts"])
                passes = int(m["passes"])
                ratio = m["ewma_solve_ratio"]
                next_review = m["next_review_at"]
                if score >= 75.0 and (next_review or 0) > now:
                    status = "mastered"
                elif next_review is not None and next_review <= now:
                    status = "review_due"
                elif score < 60.0:
                    status = "weak"
                else:
                    status = "practiced"

            nodes.append({
                "id": arch.id,
                "subtopics": list(arch.subtopics),
                "difficulties": list(arch.difficulties),
                "destructive": arch.destructive,
                "needs_node_ssh": arch.needs_node_ssh,
                "published_count": pub_rows.get(arch.id, 0),
                "attempts": attempts,
                "passes": passes,
                "mastery_score": round(score, 1),
                "ewma_solve_ratio": ratio,
                "status": status,
                "next_review_at": next_review,
            })

        practiced = [n for n in nodes if n["attempts"] > 0]
        dom_mastery = round(sum(n["mastery_score"] for n in nodes) / max(1, len(nodes)), 1)
        tree.append({
            "domain": domain,
            "weight_pct": CNCF_WEIGHTS.get(domain, 0),
            "total_archetypes": len(nodes),
            "practiced_archetypes": len(practiced),
            "domain_mastery": dom_mastery,
            "archetypes": nodes,
        })
    return tree


def readiness_report() -> dict:
    """Compute CKA Go/No-Go readiness verdict from 4 objective criteria."""
    now = time.time()
    with db.connect() as conn:
        mock_rows = conn.execute(
            "SELECT s.id, s.title, s.variant, s.finished_at, s.total_weight,"
            " COALESCE(s.earned_weight_exact, s.earned_weight) AS earned_weight,"
            " COUNT(si.id) AS item_count"
            " FROM sessions s"
            " LEFT JOIN session_items si ON si.session_id = s.id"
            " WHERE s.mode = 'mock_exam' AND s.status = 'finished' AND s.total_weight > 0"
            " GROUP BY s.id"
            " ORDER BY s.finished_at DESC LIMIT 8"
        ).fetchall()
        dom_rows = conn.execute(
            "SELECT b.domain AS domain, COUNT(*) AS total,"
            " SUM(CASE WHEN si.state = 'passed' THEN 1 ELSE 0 END) AS passed"
            " FROM session_items si"
            " JOIN sessions s ON s.id = si.session_id"
            " JOIN bank_questions b ON b.id = si.bank_question_id"
            " WHERE si.state IN ('passed', 'skipped')"
            "   AND NOT (si.state = 'skipped' AND COALESCE(si.attempts, 0) = 0 AND s.mode = 'study')"
            " GROUP BY b.domain"
        ).fetchall()
        mastery_rows = [
            dict(r) for r in conn.execute("SELECT * FROM archetype_mastery").fetchall()
        ]

    recent_mocks = []
    for row in mock_rows:
        tw = max(1, int(row["total_weight"] or 0))
        ew = float(row["earned_weight"] or 0.0)
        recent_mocks.append({
            "id": row["id"],
            "title": row["title"],
            "variant": row["variant"] or "guided_mock",
            "finished_at": row["finished_at"],
            "score_pct": round(100.0 * ew / tw, 1),
            "total_weight": tw,
            "earned_weight": round(ew, 1),
            "item_count": int(row["item_count"] or 0),
        })
    full_mocks = [m for m in recent_mocks if m["item_count"] >= 10]
    last3_full = [m["score_pct"] for m in full_mocks[:3]]
    last3_any = [m["score_pct"] for m in recent_mocks[:3]]
    recent_mock_avg = (
        round(sum(last3_full) / len(last3_full), 1)
        if last3_full
        else (round(sum(last3_any) / len(last3_any), 1) if last3_any else None)
    )

    per_domain_acc: dict[str, int] = {}
    for row in dom_rows:
        total = int(row["total"] or 0)
        if total > 0:
            per_domain_acc[row["domain"]] = round(100 * int(row["passed"] or 0) / total)

    domain_values = [per_domain_acc.get(d, 0) for d in DOMAINS]
    domain_floor = min(domain_values) if per_domain_acc else 0

    total_archetypes = len(curriculum.ARCHETYPES)
    passed_archetypes = {
        r["archetype_id"] for r in mastery_rows if int(r["passes"] or 0) > 0
    }
    syllabus_coverage_pct = round(100.0 * len(passed_archetypes) / max(1, total_archetypes), 1)

    ratios = [float(r["ewma_solve_ratio"]) for r in mastery_rows if r["ewma_solve_ratio"] is not None]
    median_pacing = round(statistics.median(ratios), 2) if ratios else None

    c_mock = len(full_mocks) >= 3 and bool(last3_full) and (sum(last3_full) / len(last3_full)) >= 78.0
    c_floor = len(per_domain_acc) == len(DOMAINS) and domain_floor >= 65
    c_cov = syllabus_coverage_pct >= 80.0
    c_pace = median_pacing is not None and median_pacing <= 1.10

    mock_pts = min(35.0, ((recent_mock_avg or 0.0) / 80.0) * 35.0)
    floor_pts = min(25.0, (domain_floor / 70.0) * 25.0)
    cov_pts = min(25.0, (syllabus_coverage_pct / 85.0) * 25.0)
    pace_pts = 0.0 if median_pacing is None else max(0.0, min(15.0, (1.6 - median_pacing) * 25.0))
    readiness_score = round(mock_pts + floor_pts + cov_pts + pace_pts, 1)

    if c_mock and c_floor and c_cov and c_pace:
        verdict = "go"
    elif readiness_score >= 60.0 or (c_mock and recent_mock_avg is not None and recent_mock_avg >= 66.0):
        verdict = "almost"
    else:
        verdict = "not_yet"

    due_count = sum(
        1 for r in mastery_rows if r["next_review_at"] is not None and float(r["next_review_at"]) <= now
    )
    weak_archetypes = sorted(
        [r for r in mastery_rows if float(r["mastery_score"] or 0) < 70.0],
        key=lambda r: float(r["mastery_score"] or 0),
    )[:6]

    return {
        "readiness_score": readiness_score,
        "verdict": verdict,
        "criteria": {
            "mock_exam_avg": {
                "value": recent_mock_avg,
                "target": 78.0,
                "ok": c_mock,
                "mocks_completed": len(full_mocks),
                "mocks_required": 3,
            },
            "domain_floor": {"value": domain_floor, "target": 65, "ok": c_floor},
            "syllabus_coverage_pct": {"value": syllabus_coverage_pct, "target": 80.0, "ok": c_cov},
            "median_pacing_ratio": {"value": median_pacing, "target": 1.10, "ok": c_pace},
        },
        "total_archetypes": total_archetypes,
        "mastered_or_passed_count": len(passed_archetypes),
        "reviews_due": due_count,
        "recent_mocks": recent_mocks,
        "per_domain_accuracy": {d: per_domain_acc.get(d) for d in DOMAINS},
        "weak_archetypes": weak_archetypes,
        "skill_tree": skill_tree(),
    }


def daily_study_plan() -> dict:
    """Compute a prioritized Today's CKA Mission from SRS due dates, domain deficits, and mock progress."""
    from datetime import date
    from app.study import service as study_svc

    now = time.time()
    exam_target_date: str | None = None
    days_remaining: int | None = None
    with db.connect() as conn:
        pref = conn.execute(
            "SELECT value_json FROM user_settings WHERE key = 'exam_target_date'"
        ).fetchone()
        if pref and pref["value_json"]:
            try:
                exam_target_date = json.loads(pref["value_json"])
                if exam_target_date:
                    days_remaining = (date.fromisoformat(str(exam_target_date)) - date.today()).days
            except (ValueError, TypeError):
                exam_target_date = None
        mastery_rows = {
            r["archetype_id"]: dict(r)
            for r in conn.execute("SELECT * FROM archetype_mastery").fetchall()
        }
        pub_archs = {
            r["archetype_id"]
            for r in conn.execute(
                "SELECT DISTINCT archetype_id FROM bank_questions WHERE state = 'published' AND archetype_id IS NOT NULL"
            ).fetchall()
        }
        full_mocks = conn.execute(
            "SELECT COUNT(*) AS n FROM ("
            "  SELECT s.id FROM sessions s JOIN session_items si ON si.session_id = s.id"
            "  WHERE s.mode = 'mock_exam' AND s.status = 'finished'"
            "  GROUP BY s.id HAVING COUNT(si.id) >= 10"
            ")"
        ).fetchone()["n"]

    items: list[dict] = []
    # 1. Due SM-2 reviews
    due = sorted(
        [
            r for r in mastery_rows.values()
            if r.get("next_review_at") is not None and float(r["next_review_at"]) <= now and r["archetype_id"] in pub_archs
        ],
        key=lambda r: (float(r.get("mastery_score") or 0.0), float(r["next_review_at"])),
    )
    if due:
        top_due = due[0]
        items.append({
            "kind": "srs_review",
            "label": f"SRS Review Due ({len(due)} archetype{'s' if len(due) != 1 else ''})",
            "detail": f"Practice `{top_due['archetype_id']}` (mastery {round(float(top_due.get('mastery_score') or 0))}%)",
            "action_type": "practice_archetype",
            "archetype_id": top_due["archetype_id"],
        })

    # 2. High-weight unseen or weak archetype
    weighted_archs = sorted(
        [a for a in curriculum.ARCHETYPES if not a.destructive and a.id in pub_archs],
        key=lambda a: (
            0 if a.id not in mastery_rows else 1,
            float((mastery_rows.get(a.id) or {}).get("mastery_score") or 0.0),
            -CNCF_WEIGHTS.get(a.domain, 0),
        ),
    )
    if weighted_archs:
        target = weighted_archs[0]
        topic_id = study_svc.topic_id_for_archetype(target.id)
        items.append({
            "kind": "weakness_focus",
            "label": f"High-Yield Focus: {target.domain.split(',')[0]} ({CNCF_WEIGHTS.get(target.domain, 0)}%)",
            "detail": f"Master `{target.id}` ({', '.join(target.subtopics[:2])})",
            "action_type": "codex_topic" if topic_id else "practice_archetype",
            "topic_id": topic_id,
            "archetype_id": target.id,
        })

    # 3. Pacing drill if slow or starting out
    ratios = [float(r["ewma_solve_ratio"]) for r in mastery_rows.values() if r.get("ewma_solve_ratio") is not None]
    med_pace = round(statistics.median(ratios), 2) if ratios else None
    if med_pace is None or med_pace > 1.1:
        items.append({
            "kind": "speed_blitz",
            "label": "Speed Blitz (5Q · 25m)",
            "detail": f"Build imperative kubectl speed (current pace: {med_pace}x target)" if med_pace else "Calibrate imperative kubectl speed vs 1.10x target",
            "action_type": "launch_variant",
            "variant": "speed_blitz",
            "count": 5,
        })

    # 4. Calibrated Blind Mock requirement
    if int(full_mocks or 0) < 3:
        items.append({
            "kind": "blind_mock",
            "label": f"Full Blind Mock Exam ({full_mocks}/3 complete)",
            "detail": "15Q PSI-strict 120m simulation required for exam readiness Go verdict.",
            "action_type": "launch_variant",
            "variant": "blind_exam",
            "count": 15,
        })

    if days_remaining is not None:
        headline = (
            f"{max(0, days_remaining)} day(s) until target CKA exam ({exam_target_date}) · "
            f"{len(due)} SRS due · {full_mocks}/3 full mocks done"
        )
    else:
        headline = f"{len(due)} SRS review(s) due · {full_mocks}/3 full mocks complete"

    return {
        "exam_target_date": exam_target_date,
        "days_remaining": days_remaining,
        "mocks_completed": int(full_mocks or 0),
        "mocks_required": 3,
        "reviews_due": len(due),
        "headline": headline,
        "items": items[:4],
    }


def analyze_command_efficiency(
    commands_list: list[str],
    envelope: ScenarioEnvelope,
    solve_seconds: float,
) -> dict:
    """Summarize candidate shell command efficiency and suggest CKA exam speedups (v2)."""
    clean_cmds = [c.strip() for c in commands_list if c and c.strip()]
    target_s = max(60.0, float(envelope.estimated_minutes or 5.0) * 60.0)
    pacing_ratio = round(float(solve_seconds) / target_s, 2)

    alias_hits = sum(1 for c in clean_cmds if c == "k" or c.startswith("k "))
    dry_run_hits = sum(1 for c in clean_cmds if "$do" in c or "--dry-run=client" in c)
    fast_delete_hits = sum(1 for c in clean_cmds if "$now" in c or "--force --grace-period=0" in c)
    edit_hits = sum(1 for c in clean_cmds if " edit " in f" {c} ")
    long_resource_hits = sum(
        1 for c in clean_cmds
        if any(f" {word}" in f" {c} " for word in ("pods", "deployments", "services", "networkpolicies"))
    )
    missing_ns_hits = sum(
        1 for c in clean_cmds
        if (c.startswith("k ") or c.startswith("kubectl "))
        and " -n " not in f" {c} "
        and " --namespace" not in c
        and any(verb in f" {c} " for verb in (" get ", " describe ", " patch ", " delete "))
        and envelope.setup.namespaces
    )

    tips: list[str] = []
    if clean_cmds and alias_hits == 0 and any(c.startswith("kubectl ") for c in clean_cmds):
        tips.append("Use the `k` alias (`k get po`, `k describe`) to save ~15–20% keystrokes.")
    if clean_cmds and dry_run_hits == 0 and len(clean_cmds) >= 4:
        tips.append("Generate boilerplate fast with `k create ... $do > out.yaml` (`$do` = `--dry-run=client -o yaml`).")
    if edit_hits >= 2:
        tips.append("Avoid slow `kubectl edit` retries — prefer `k patch`, `k set`, or `-o yaml > f.yaml && k replace --force -f f.yaml`.")
    if long_resource_hits >= 2:
        tips.append("Use shortnames (`po`, `deploy`, `svc`, `netpol`, `ns`) instead of full resource names.")
    if missing_ns_hits >= 2:
        tips.append("Always pass `-n <namespace>` or switch default namespace (`k config set-context --current --namespace=...`).")
    if pacing_ratio > 1.25:
        tips.append(
            f"Time pacing was {pacing_ratio}x target ({round(solve_seconds / 60, 1)}m vs {envelope.estimated_minutes}m) — practice the fast shortcuts below."
        )
    if envelope.fast_solution_commands:
        tips.append("Fast shortcuts: " + "  |  ".join(envelope.fast_solution_commands[:3]))

    return {
        "command_count": len(clean_cmds),
        "solve_seconds": round(float(solve_seconds), 1),
        "target_seconds": round(target_s, 1),
        "pacing_ratio": pacing_ratio,
        "shortcuts_used": {
            "k_alias": alias_hits,
            "dry_run": dry_run_hits,
            "fast_delete": fast_delete_hits,
            "shortnames_missed": long_resource_hits,
            "edit_calls": edit_hits,
        },
        "tips": tips,
        "recent_commands": clean_cmds[-12:],
    }
