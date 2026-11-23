"""Domain telemetry, recommendations, and generation pipeline health metrics."""

from __future__ import annotations

import json

from app import bank, db
from app.models import DOMAINS


def _pipeline_stats() -> dict:
    counts = bank.state_counts()
    with db.connect() as conn:
        req_row = conn.execute(
            "SELECT COUNT(*) AS jobs,"
            " SUM(scenarios_attempted) AS attempted,"
            " SUM(scenarios_published) AS published"
            " FROM generation_requests WHERE status IN ('done', 'cancelled')"
        ).fetchone()
        lat_row = conn.execute(
            "SELECT COUNT(*) AS calls,"
            " AVG(duration_ms) AS avg_ms"
            " FROM llm_generations WHERE status = 'ok' AND duration_ms IS NOT NULL"
        ).fetchone()
        draft_rows = conn.execute(
            "SELECT probe_result_json FROM bank_questions WHERE state = 'draft' AND probe_result_json IS NOT NULL"
        ).fetchall()

    attempted = int(req_row["attempted"] or 0)
    published = int(req_row["published"] or 0)
    top_errors: dict[str, int] = {}
    for row in draft_rows:
        try:
            err = (json.loads(row["probe_result_json"]).get("error") or "").splitlines()[0][:80]
        except ValueError:
            err = "unknown"
        if err:
            top_errors[err] = top_errors.get(err, 0) + 1
    top_list = [
        {"reason": reason, "count": count}
        for reason, count in sorted(top_errors.items(), key=lambda x: -x[1])[:5]
    ]
    return {
        "bank_states": counts,
        "jobs_completed": int(req_row["jobs"] or 0),
        "attempted": attempted,
        "published": published,
        "publish_rate_pct": round(100 * published / attempted) if attempted else None,
        "llm_calls_timed": int(lat_row["calls"] or 0),
        "avg_llm_ms": round(float(lat_row["avg_ms"])) if lat_row["avg_ms"] is not None else None,
        "top_quarantine_reasons": top_list,
    }


def summary() -> dict:
    with db.connect() as conn:
        sessions = conn.execute(
            "SELECT COUNT(*) AS n,"
            " SUM(CASE WHEN status = 'finished' THEN 1 ELSE 0 END) AS finished"
            " FROM sessions"
        ).fetchone()
        rows = conn.execute(
            "SELECT b.domain AS domain,"
            " COUNT(*) AS total,"
            " SUM(CASE WHEN si.state = 'passed' THEN 1 ELSE 0 END) AS passed,"
            " SUM(CASE WHEN si.state = 'passed' AND si.attempts <= 1 THEN 1 ELSE 0 END) AS first_try,"
            " AVG(CASE WHEN si.state = 'passed' AND si.passed_at IS NOT NULL"
            "      THEN si.passed_at - si.started_at END) AS avg_seconds"
            " FROM session_items si JOIN bank_questions b ON b.id = si.bank_question_id"
            " GROUP BY b.domain"
        ).fetchall()
        check_runs = conn.execute("SELECT COUNT(*) AS n FROM check_runs").fetchone()

    per_domain: dict[str, dict] = {}
    for row in rows:
        total = int(row["total"] or 0)
        passed = int(row["passed"] or 0)
        first_try = int(row["first_try"] or 0)
        per_domain[row["domain"]] = {
            "total": total,
            "passed": passed,
            "first_try_passes": first_try,
            "accuracy_pct": round(100 * passed / total) if total else None,
            "first_try_pct": round(100 * first_try / total) if total else None,
            "avg_minutes": round((row["avg_seconds"] or 0) / 60, 1) if row["avg_seconds"] else None,
        }

    coverage = {f"{cell['domain']}|{cell['difficulty']}": cell["published"] for cell in bank.coverage()}
    weakest = None
    if per_domain:
        scored = [(data["accuracy_pct"] or 0, domain) for domain, data in per_domain.items()]
        scored.sort()
        if scored[0][0] < 100:
            weakest = scored[0][1]
    if weakest is None:
        empties = [domain for domain in DOMAINS
                   if sum(coverage.get(f"{domain}|{difficulty}", 0)
                          for difficulty in ("exam_standard", "killer_hardcore", "boss_fight")) == 0]
        weakest = empties[0] if empties else DOMAINS[0]

    return {
        "sessions": {"total": int(sessions["n"] or 0), "finished": int(sessions["finished"] or 0)},
        "check_runs": int(check_runs["n"] or 0),
        "per_domain": per_domain,
        "coverage": coverage,
        "pipeline": _pipeline_stats(),
        "recommendation": {
            "domain": weakest,
            "reason": (
                "lowest accuracy in past sessions"
                if per_domain and (per_domain.get(weakest, {}).get("accuracy_pct") or 0) < 100
                else "no published questions yet in this domain"
            ),
        },
    }
