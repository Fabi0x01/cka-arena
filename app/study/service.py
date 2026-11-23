"""Service layer for CKA Study Codex v2 — XP, Ranks, Streak, Shields, 3-Q Gauntlets & Drill Deck."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import time
from typing import Any, Literal

from app import curriculum, db
from app.models import DOMAINS
from app.study.content_arch import ARCH_TOPICS
from app.study.content_network import NETWORK_TOPICS
from app.study.content_storage_ts import STORAGE_TS_TOPICS
from app.study.content_workloads import WORKLOAD_TOPICS
from app.study.models import StudyTopic

TOPICS: tuple[StudyTopic, ...] = tuple(
    sorted(
        (*ARCH_TOPICS, *WORKLOAD_TOPICS, *NETWORK_TOPICS, *STORAGE_TS_TOPICS),
        key=lambda t: t.order,
    )
)
TOPICS_BY_ID: dict[str, StudyTopic] = {topic.id: topic for topic in TOPICS}

STAGE_XP: dict[str, int] = {
    "theory": 25,
    "practice": 35,
    "cheatsheet": 20,
    "quiz": 40,
}
TOPIC_MAX_XP = sum(STAGE_XP.values())  # 120
MAX_TOTAL_XP = TOPIC_MAX_XP * len(TOPICS)  # 4320
DAILY_TOPIC_GOAL = 3

CNCF_WEIGHTS: dict[str, int] = {
    "Troubleshooting": 30,
    "Cluster Architecture, Installation & Configuration": 25,
    "Services & Networking": 20,
    "Workloads & Scheduling": 15,
    "Storage": 10,
}

RANKS: tuple[tuple[int, str, str], ...] = (
    (0, "L1", "Cluster Cadet"),
    (500, "L2", "Pod Operator"),
    (1200, "L3", "Node Engineer"),
    (2100, "L4", "Control Plane Architect"),
    (3100, "L5", "CKA Specialist"),
    (4000, "L6", "CKA Exam Ready"),
)

ValidStage = Literal["theory", "practice", "cheatsheet"]


def _today_iso() -> str:
    return date.today().isoformat()


def _compute_xp(theory: int, practice: int, cheatsheet: int, quiz: int) -> int:
    return (
        STAGE_XP["theory"] * (1 if theory else 0)
        + STAGE_XP["practice"] * (1 if practice else 0)
        + STAGE_XP["cheatsheet"] * (1 if cheatsheet else 0)
        + STAGE_XP["quiz"] * (1 if quiz else 0)
    )


def _rank_for_xp(total_xp: int) -> dict[str, Any]:
    idx = 0
    for i, (threshold, _lvl, _title) in enumerate(RANKS):
        if total_xp >= threshold:
            idx = i
    floor_xp, level, title = RANKS[idx]
    if idx + 1 < len(RANKS):
        next_xp, next_level, next_title = RANKS[idx + 1]
        span = max(1, next_xp - floor_xp)
        ratio = round(min(1.0, max(0.0, (total_xp - floor_xp) / span)), 3)
    else:
        next_xp = MAX_TOTAL_XP
        next_level = level
        next_title = "Max Rank"
        ratio = 1.0
    return {
        "level": level,
        "title": title,
        "current_floor": floor_xp,
        "next_threshold": next_xp,
        "next_level": next_level,
        "next_title": next_title,
        "progress_ratio": ratio,
    }


def _compute_streak(active_days: set[str], today: date | None = None) -> int:
    ref = today or date.today()
    today_str = ref.isoformat()
    yesterday_str = (ref - timedelta(days=1)).isoformat()
    if today_str in active_days:
        cursor = ref
    elif yesterday_str in active_days:
        cursor = ref - timedelta(days=1)
    else:
        return 0
    streak = 0
    while cursor.isoformat() in active_days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _effective_mask(row: dict[str, Any] | None, quiz_count: int) -> int:
    if not row:
        return 0
    mask = int(row.get("quiz_passed_mask") or 0)
    if int(bool(row.get("quiz_passed"))) and mask == 0:
        # Seamless upgrade from v1 single-question completions
        mask = (1 << quiz_count) - 1
    return mask


def _progress_dict(row: dict[str, Any] | None, quiz_count: int = 3) -> dict[str, Any]:
    t = int(bool(row["theory_done"])) if row else 0
    p = int(bool(row["practice_done"])) if row else 0
    c = int(bool(row["cheatsheet_done"])) if row else 0
    mask = _effective_mask(row, quiz_count)
    passed_indices = [i for i in range(quiz_count) if (mask & (1 << i)) != 0]
    quiz_passed_count = len(passed_indices)
    q = 1 if quiz_passed_count >= quiz_count else 0
    attempts = int(row["quiz_attempts"] or 0) if row else 0
    stages_done = t + p + c + q
    xp = _compute_xp(t, p, c, q)
    completed = stages_done == 4
    return {
        "theory_done": bool(t),
        "practice_done": bool(p),
        "cheatsheet_done": bool(c),
        "quiz_passed": bool(q),
        "quiz_passed_mask": mask,
        "quiz_passed_indices": passed_indices,
        "quiz_passed_count": quiz_passed_count,
        "quiz_total": quiz_count,
        "quiz_attempts": attempts,
        "stages_done": stages_done,
        "completed": completed,
        "xp_earned": xp,
        "max_xp": TOPIC_MAX_XP,
        "completed_at": row["completed_at"] if row else None,
    }


def get_overview() -> dict[str, Any]:
    """Return full gamified Study Codex overview across all 36 topics and 59 archetypes."""
    with db.connect() as conn:
        prog_rows = {
            r["topic_id"]: dict(r)
            for r in conn.execute("SELECT * FROM study_progress").fetchall()
        }
        act_rows = {
            r["day"]: dict(r)
            for r in conn.execute("SELECT * FROM study_activity").fetchall()
        }
        bank_counts = {
            r["archetype_id"]: int(r["n"])
            for r in conn.execute(
                "SELECT archetype_id, COUNT(*) AS n FROM bank_questions"
                " WHERE state = 'published' AND archetype_id IS NOT NULL"
                " GROUP BY archetype_id"
            ).fetchall()
        }
        mastery_scores = {
            r["archetype_id"]: float(r["mastery_score"] or 0.0)
            for r in conn.execute("SELECT archetype_id, mastery_score FROM archetype_mastery").fetchall()
        }

    total_xp = 0
    completed_topics = 0
    total_questions = 0
    passed_questions = 0
    domain_buckets: dict[str, dict[str, Any]] = {
        dom: {"domain": dom, "weight_pct": CNCF_WEIGHTS.get(dom, 0), "completed": 0, "total": 0, "xp": 0, "max_xp": 0}
        for dom in sorted(DOMAINS, key=lambda d: -CNCF_WEIGHTS.get(d, 0))
    }

    topics_out: list[dict[str, Any]] = []
    in_progress_candidate: str | None = None
    first_incomplete: str | None = None

    for topic in TOPICS:
        q_count = len(topic.quizzes)
        prog = _progress_dict(prog_rows.get(topic.id), quiz_count=q_count)
        total_xp += prog["xp_earned"]
        total_questions += q_count
        passed_questions += prog["quiz_passed_count"]
        if prog["completed"]:
            completed_topics += 1
        else:
            if first_incomplete is None:
                first_incomplete = topic.id
            if in_progress_candidate is None and (prog["stages_done"] > 0 or prog["quiz_passed_count"] > 0):
                in_progress_candidate = topic.id

        bucket = domain_buckets[topic.domain]
        bucket["total"] += 1
        bucket["xp"] += prog["xp_earned"]
        bucket["max_xp"] += TOPIC_MAX_XP
        if prog["completed"]:
            bucket["completed"] += 1

        arch_bank = sum(bank_counts.get(aid, 0) for aid in topic.archetype_ids)
        practiced_scores = [mastery_scores[aid] for aid in topic.archetype_ids if aid in mastery_scores]
        mastery_avg = round(sum(practiced_scores) / len(practiced_scores), 1) if practiced_scores else None
        search_terms = [
            topic.id,
            topic.title,
            topic.subtitle,
            topic.domain,
            *topic.archetype_ids,
            *(item.label for item in topic.cheatsheet),
            *(item.command for item in topic.cheatsheet),
            *(row.concept for row in topic.decision_matrix),
            *(row.when_to_use for row in topic.decision_matrix),
            *(row.symptom for row in topic.debug_playbook),
            *(row.cause for row in topic.debug_playbook),
        ]

        topics_out.append({
            "id": topic.id,
            "order": topic.order,
            "domain": topic.domain,
            "title": topic.title,
            "subtitle": topic.subtitle,
            "estimated_minutes": topic.estimated_minutes,
            "exam_frequency": topic.exam_frequency,
            "archetype_ids": list(topic.archetype_ids),
            "bank_count": arch_bank,
            "mastery_avg": mastery_avg,
            "progress": prog,
            "search_blob": " ".join(search_terms).lower(),
        })

    domain_shields = [
        {
            **b,
            "shield_unlocked": b["total"] > 0 and b["completed"] == b["total"],
            "progress_ratio": round(b["completed"] / max(1, b["total"]), 3),
        }
        for b in domain_buckets.values()
    ]

    today_str = _today_iso()
    today_row = act_rows.get(today_str)
    active_days = {day for day, row in act_rows.items() if int(row.get("actions_count") or 0) > 0}
    streak_days = _compute_streak(active_days)
    recommended = in_progress_candidate or first_incomplete or TOPICS[0].id

    return {
        "total_xp": total_xp,
        "max_xp": MAX_TOTAL_XP,
        "rank": _rank_for_xp(total_xp),
        "completed_topics": completed_topics,
        "total_topics": len(TOPICS),
        "total_questions": total_questions,
        "passed_questions": passed_questions,
        "streak_days": streak_days,
        "today_xp": int(today_row["xp_gained"] or 0) if today_row else 0,
        "today_completed": int(today_row["topics_completed"] or 0) if today_row else 0,
        "daily_goal": DAILY_TOPIC_GOAL,
        "domain_shields": domain_shields,
        "recommended_topic_id": recommended,
        "topics": topics_out,
    }


def get_topic(topic_id: str) -> dict[str, Any] | None:
    """Return full concept/flow/matrix/docs/practice/playbook/cheatsheet/gauntlet payload."""
    topic = TOPICS_BY_ID.get(topic_id)
    if not topic:
        return None

    now = time.time()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM study_progress WHERE topic_id = ?", (topic_id,)
        ).fetchone()
        bank_counts = {
            r["archetype_id"]: int(r["n"])
            for r in conn.execute(
                "SELECT archetype_id, COUNT(*) AS n FROM bank_questions"
                " WHERE state = 'published' AND archetype_id IS NOT NULL"
                " GROUP BY archetype_id"
            ).fetchall()
        }
        mastery_rows = {
            r["archetype_id"]: dict(r)
            for r in conn.execute("SELECT * FROM archetype_mastery").fetchall()
        }

    prog = _progress_dict(dict(row) if row else None, quiz_count=len(topic.quizzes))
    passed_set = set(prog["quiz_passed_indices"])

    archetypes_detail = []
    for aid in topic.archetype_ids:
        arch = curriculum.ARCHETYPES_BY_ID.get(aid)
        m = mastery_rows.get(aid)
        if not m or int(m.get("attempts") or 0) == 0:
            status = "unseen"
            score = 0.0
        else:
            score = float(m.get("mastery_score") or 0.0)
            nxt = m.get("next_review_at")
            if score >= 75.0 and (nxt or 0) > now:
                status = "mastered"
            elif nxt is not None and nxt <= now:
                status = "review_due"
            elif score < 60.0:
                status = "weak"
            else:
                status = "practiced"
        archetypes_detail.append({
            "id": aid,
            "subtopics": list(arch.subtopics) if arch else [],
            "destructive": bool(arch.destructive) if arch else False,
            "needs_node_ssh": bool(arch.needs_node_ssh) if arch else False,
            "bank_count": bank_counts.get(aid, 0),
            "mastery_score": round(score, 1),
            "status": status,
        })

    idx = next(i for i, t in enumerate(TOPICS) if t.id == topic_id)
    prev_id = TOPICS[idx - 1].id if idx > 0 else None
    next_id = TOPICS[idx + 1].id if idx + 1 < len(TOPICS) else None

    quizzes_payload: list[dict[str, Any]] = []
    for q_idx, q in enumerate(topic.quizzes):
        is_passed = q_idx in passed_set
        q_item: dict[str, Any] = {
            "index": q_idx,
            "tag": q.tag,
            "question": q.question,
            "choices": list(q.choices),
            "passed": is_passed,
        }
        if is_passed:
            q_item["correct_index"] = q.correct_index
            q_item["explanation"] = q.explanation
        quizzes_payload.append(q_item)

    return {
        "id": topic.id,
        "order": topic.order,
        "domain": topic.domain,
        "title": topic.title,
        "subtitle": topic.subtitle,
        "estimated_minutes": topic.estimated_minutes,
        "exam_frequency": topic.exam_frequency,
        "summary": topic.summary,
        "architecture_flow": topic.architecture_flow,
        "theory_points": list(topic.theory_points),
        "decision_matrix": [
            {"concept": r.concept, "behavior": r.behavior, "when_to_use": r.when_to_use}
            for r in topic.decision_matrix
        ],
        "docs_links": [
            {"label": d.label, "url": d.url, "exam_search_term": d.exam_search_term}
            for d in topic.docs_links
        ],
        "practice_steps": [
            {
                "title": s.title,
                "explanation": s.explanation,
                "command": s.command,
                "yaml_snippet": s.yaml_snippet,
                "verify_command": s.verify_command,
                "expected_output": s.expected_output,
            }
            for s in topic.practice_steps
        ],
        "debug_playbook": [
            {"symptom": r.symptom, "cause": r.cause, "fix": r.fix}
            for r in topic.debug_playbook
        ],
        "exam_trap": topic.exam_trap,
        "cheatsheet": [
            {"label": c.label, "command": c.command, "note": c.note}
            for c in topic.cheatsheet
        ],
        "yaml_template": topic.yaml_template,
        "quizzes": quizzes_payload,
        "quiz": quizzes_payload[0],
        "archetypes": archetypes_detail,
        "progress": prog,
        "stage_xp": STAGE_XP,
        "prev_topic_id": prev_id,
        "next_topic_id": next_id,
    }


def _upsert_activity(conn, *, xp_delta: int, actions_delta: int, completed_delta: int, now: float) -> None:
    day = _today_iso()
    conn.execute(
        "INSERT INTO study_activity (day, xp_gained, actions_count, topics_completed, updated_at)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(day) DO UPDATE SET"
        "  xp_gained = MAX(0, study_activity.xp_gained + excluded.xp_gained),"
        "  actions_count = MAX(0, study_activity.actions_count + excluded.actions_count),"
        "  topics_completed = MAX(0, study_activity.topics_completed + excluded.topics_completed),"
        "  updated_at = excluded.updated_at",
        (day, xp_delta, actions_delta, completed_delta, now),
    )


def set_stage(topic_id: str, stage: ValidStage, done: bool = True) -> dict[str, Any]:
    """Toggle completion for theory, practice, or cheatsheet stage and award XP."""
    topic = TOPICS_BY_ID.get(topic_id)
    if not topic:
        raise KeyError(topic_id)
    col_map = {
        "theory": "theory_done",
        "practice": "practice_done",
        "cheatsheet": "cheatsheet_done",
    }
    if stage not in col_map:
        raise ValueError(f"invalid study stage: {stage}")

    q_count = len(topic.quizzes)
    now = time.time()
    val = 1 if done else 0
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM study_progress WHERE topic_id = ?", (topic_id,)).fetchone()
        row_dict = dict(row) if row else None
        prev_prog = _progress_dict(row_dict, quiz_count=q_count)
        state = {
            "theory_done": 1 if prev_prog["theory_done"] else 0,
            "practice_done": 1 if prev_prog["practice_done"] else 0,
            "cheatsheet_done": 1 if prev_prog["cheatsheet_done"] else 0,
            "quiz_passed": 1 if prev_prog["quiz_passed"] else 0,
            "quiz_passed_mask": prev_prog["quiz_passed_mask"],
            "quiz_attempts": prev_prog["quiz_attempts"],
        }
        prev_val = state[col_map[stage]]
        prev_xp = prev_prog["xp_earned"]
        prev_completed = prev_prog["completed"]

        state[col_map[stage]] = val
        new_xp = _compute_xp(
            state["theory_done"], state["practice_done"], state["cheatsheet_done"], state["quiz_passed"]
        )
        now_completed = (
            state["theory_done"] + state["practice_done"] + state["cheatsheet_done"] + state["quiz_passed"] == 4
        )
        completed_at = (row_dict["completed_at"] if row_dict and prev_completed else now) if now_completed else None
        xp_delta = new_xp - prev_xp
        newly_completed = (not prev_completed) and now_completed

        conn.execute(
            "INSERT INTO study_progress"
            " (topic_id, theory_done, practice_done, cheatsheet_done, quiz_passed, quiz_passed_mask,"
            "  quiz_attempts, xp_earned, completed_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(topic_id) DO UPDATE SET"
            "  theory_done = excluded.theory_done,"
            "  practice_done = excluded.practice_done,"
            "  cheatsheet_done = excluded.cheatsheet_done,"
            "  quiz_passed = excluded.quiz_passed,"
            "  quiz_passed_mask = excluded.quiz_passed_mask,"
            "  xp_earned = excluded.xp_earned,"
            "  completed_at = excluded.completed_at,"
            "  updated_at = excluded.updated_at",
            (
                topic_id,
                state["theory_done"],
                state["practice_done"],
                state["cheatsheet_done"],
                state["quiz_passed"],
                state["quiz_passed_mask"],
                state["quiz_attempts"],
                new_xp,
                completed_at,
                now,
            ),
        )
        if prev_val != val:
            _upsert_activity(
                conn,
                xp_delta=xp_delta,
                actions_delta=1 if val else 0,
                completed_delta=1 if newly_completed else 0,
                now=now,
            )

    overview = get_overview()
    progress = next(t["progress"] for t in overview["topics"] if t["id"] == topic_id)
    return {
        "topic_id": topic_id,
        "stage": stage,
        "done": bool(done),
        "xp_delta": xp_delta,
        "newly_completed": newly_completed,
        "progress": progress,
        "overview": overview,
    }


def submit_quiz(topic_id: str, choice_index: int, question_index: int = 0) -> dict[str, Any]:
    """Validate one Boss Gauntlet question, track passed bitmask, and award +40 XP once 3/3 pass."""
    topic = TOPICS_BY_ID.get(topic_id)
    if not topic:
        raise KeyError(topic_id)
    q_count = len(topic.quizzes)
    if question_index < 0 or question_index >= q_count:
        raise ValueError(f"question_index out of range: {question_index}")
    quiz = topic.quizzes[question_index]
    if choice_index < 0 or choice_index >= len(quiz.choices):
        raise ValueError(f"choice_index out of range: {choice_index}")

    now = time.time()
    correct = choice_index == quiz.correct_index

    with db.connect() as conn:
        row = conn.execute("SELECT * FROM study_progress WHERE topic_id = ?", (topic_id,)).fetchone()
        row_dict = dict(row) if row else None
        t = int(bool(row_dict["theory_done"])) if row_dict else 0
        p = int(bool(row_dict["practice_done"])) if row_dict else 0
        c = int(bool(row_dict["cheatsheet_done"])) if row_dict else 0
        prev_mask = _effective_mask(row_dict, q_count)
        prev_q = 1 if len([i for i in range(q_count) if (prev_mask & (1 << i)) != 0]) >= q_count else 0
        attempts = (int(row_dict.get("quiz_attempts") or 0) if row_dict else 0) + 1
        prev_xp = _compute_xp(t, p, c, prev_q)
        prev_completed = (t + p + c + prev_q) == 4

        new_mask = prev_mask | (1 << question_index) if correct else prev_mask
        passed_bits = [i for i in range(q_count) if (new_mask & (1 << i)) != 0]
        all_passed = len(passed_bits) >= q_count
        new_q = 1 if (prev_q or all_passed) else 0
        new_xp = _compute_xp(t, p, c, new_q)
        now_completed = (t + p + c + new_q) == 4
        completed_at = (row_dict["completed_at"] if row_dict and prev_completed else now) if now_completed else None
        xp_delta = new_xp - prev_xp
        newly_completed = (not prev_completed) and now_completed

        conn.execute(
            "INSERT INTO study_progress"
            " (topic_id, theory_done, practice_done, cheatsheet_done, quiz_passed, quiz_passed_mask,"
            "  quiz_attempts, xp_earned, completed_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(topic_id) DO UPDATE SET"
            "  quiz_passed = excluded.quiz_passed,"
            "  quiz_passed_mask = excluded.quiz_passed_mask,"
            "  quiz_attempts = excluded.quiz_attempts,"
            "  xp_earned = excluded.xp_earned,"
            "  completed_at = excluded.completed_at,"
            "  updated_at = excluded.updated_at",
            (topic_id, t, p, c, new_q, new_mask, attempts, new_xp, completed_at, now),
        )
        _upsert_activity(
            conn,
            xp_delta=xp_delta,
            actions_delta=1,
            completed_delta=1 if newly_completed else 0,
            now=now,
        )

    overview = get_overview()
    progress = next(item["progress"] for item in overview["topics"] if item["id"] == topic_id)
    reveal = correct or ((prev_mask & (1 << question_index)) != 0)
    return {
        "topic_id": topic_id,
        "question_index": question_index,
        "correct": correct,
        "correct_index": quiz.correct_index if reveal else None,
        "explanation": (
            quiz.explanation
            if reveal
            else "Not quite — review Core Exam Mechanics, Decision Matrix, and PSI Exam Trap, then try again."
        ),
        "quiz_passed_count": progress["quiz_passed_count"],
        "quiz_total": progress["quiz_total"],
        "gauntlet_cleared": progress["quiz_passed"],
        "xp_delta": xp_delta,
        "newly_completed": newly_completed,
        "progress": progress,
        "overview": overview,
    }


def get_drill_deck(domain: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Build a balanced Speed Recall Blitz deck prioritizing unpassed Boss Check questions."""
    capped_limit = max(1, min(30, int(limit)))
    active_domain = domain if domain and domain != "all" else None

    with db.connect() as conn:
        prog_rows = {
            r["topic_id"]: dict(r)
            for r in conn.execute("SELECT * FROM study_progress").fetchall()
        }

    unpassed_by_dom: dict[str, list[dict[str, Any]]] = defaultdict(list)
    passed_by_dom: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total_unpassed = 0

    for topic in TOPICS:
        if active_domain and topic.domain != active_domain:
            continue
        mask = _effective_mask(prog_rows.get(topic.id), len(topic.quizzes))
        for q_idx, q in enumerate(topic.quizzes):
            already = (mask & (1 << q_idx)) != 0
            card = {
                "topic_id": topic.id,
                "topic_order": topic.order,
                "topic_title": topic.title,
                "domain": topic.domain,
                "question_index": q_idx,
                "tag": q.tag,
                "question": q.question,
                "choices": list(q.choices),
                "already_passed": already,
            }
            if already:
                passed_by_dom[topic.domain].append(card)
            else:
                total_unpassed += 1
                unpassed_by_dom[topic.domain].append(card)

    def _round_robin(buckets: dict[str, list[dict[str, Any]]], need: int) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        ordered_doms = sorted(buckets.keys(), key=lambda d: -CNCF_WEIGHTS.get(d, 0))
        cursors = {d: 0 for d in ordered_doms}
        while len(selected) < need:
            progressed = False
            for dom in ordered_doms:
                pos = cursors[dom]
                lst = buckets[dom]
                if pos < len(lst):
                    selected.append(lst[pos])
                    cursors[dom] = pos + 1
                    progressed = True
                    if len(selected) >= need:
                        break
            if not progressed:
                break
        return selected

    deck = _round_robin(unpassed_by_dom, capped_limit)
    if len(deck) < capped_limit:
        deck.extend(_round_robin(passed_by_dom, capped_limit - len(deck)))

    return {
        "domain": active_domain or "all",
        "count": len(deck),
        "total_unpassed": total_unpassed,
        "items": deck,
    }
