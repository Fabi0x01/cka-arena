"""Unit and FastAPI integration tests for CKA Study Codex v2."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import curriculum, db, main as main_mod, study
from app.study import service as study_service

ALLOWED_DOC_PREFIXES = (
    "https://kubernetes.io/docs/",
    "https://helm.sh/docs/",
    "https://gateway-api.sigs.k8s.io/",
)


def test_study_curriculum_invariants() -> None:
    topics = study.TOPICS
    assert len(topics) == 36
    assert [t.order for t in topics] == list(range(1, 37))
    assert len({t.id for t in topics}) == 36

    covered_archetypes = {aid for t in topics for aid in t.archetype_ids}
    all_archetypes = set(curriculum.ARCHETYPES_BY_ID.keys())
    assert len(all_archetypes) == 59
    assert all_archetypes - covered_archetypes == set()
    assert covered_archetypes - all_archetypes == set()

    total_questions = 0
    for topic in topics:
        assert topic.summary.strip()
        assert topic.architecture_flow.strip()
        assert len(topic.theory_points) >= 5
        assert len(topic.decision_matrix) >= 3
        assert len(topic.docs_links) >= 1
        for doc in topic.docs_links:
            assert doc.url.startswith(ALLOWED_DOC_PREFIXES)
            assert doc.exam_search_term.strip()
        assert len(topic.practice_steps) >= 3
        verified_steps = [s for s in topic.practice_steps if s.verify_command and s.expected_output]
        assert len(verified_steps) >= 2
        assert len(topic.debug_playbook) >= 3
        assert topic.exam_trap.strip()
        assert len(topic.cheatsheet) >= 5
        assert topic.yaml_template.strip()

        assert len(topic.quizzes) == 3
        assert [q.tag for q in topic.quizzes] == ["Architecture", "CLI & YAML", "Exam Trap"]
        for q in topic.quizzes:
            total_questions += 1
            assert len(q.choices) == 4
            assert 0 <= q.correct_index < len(q.choices)
            assert q.explanation.strip()

    assert total_questions == 108


def test_study_rank_and_streak_logic() -> None:
    l1 = study_service._rank_for_xp(0)
    assert l1["level"] == "L1"
    assert l1["next_threshold"] == 500

    l2 = study_service._rank_for_xp(500)
    assert l2["level"] == "L2"
    assert l2["next_level"] == "L3"

    l6 = study_service._rank_for_xp(4320)
    assert l6["level"] == "L6"
    assert l6["progress_ratio"] == 1.0

    today = date(2026, 11, 23)
    streak_days = {
        today.isoformat(),
        (today - timedelta(days=1)).isoformat(),
        (today - timedelta(days=2)).isoformat(),
        (today - timedelta(days=4)).isoformat(),
    }
    assert study_service._compute_streak(streak_days, today=today) == 3
    assert study_service._compute_streak({(today - timedelta(days=1)).isoformat()}, today=today) == 1
    assert study_service._compute_streak({(today - timedelta(days=2)).isoformat()}, today=today) == 0


def test_study_api_gauntlet_progression_and_anti_cheat() -> None:
    db.init_db()
    client = TestClient(main_mod.app)

    r_over = client.get("/api/study/overview")
    assert r_over.status_code == 200
    over = r_over.json()
    assert over["total_topics"] == 36
    assert over["max_xp"] == 4320
    assert over["total_questions"] == 108
    assert over["passed_questions"] == 0
    assert over["total_xp"] == 0
    assert over["streak_days"] == 0
    assert over["daily_goal"] == 3
    assert len(over["domain_shields"]) == 5

    first_id = over["topics"][0]["id"]
    second_id = over["topics"][1]["id"]
    assert over["recommended_topic_id"] == first_id

    # Before passing each Boss Check question, answer & explanation stay hidden
    r_topic = client.get(f"/api/study/topics/{first_id}")
    assert r_topic.status_code == 200
    topic_data = r_topic.json()
    assert topic_data["architecture_flow"].strip()
    assert len(topic_data["decision_matrix"]) >= 3
    assert len(topic_data["debug_playbook"]) >= 3
    assert len(topic_data["quizzes"]) == 3
    for q in topic_data["quizzes"]:
        assert "correct_index" not in q
        assert "explanation" not in q
        assert q["passed"] is False

    assert client.get("/api/study/topics/does-not-exist").status_code == 404

    # Stage completions award XP once (idempotent)
    r_th = client.post(f"/api/study/topics/{first_id}/stage", json={"stage": "theory", "done": True})
    assert r_th.status_code == 200 and r_th.json()["xp_delta"] == 25
    r_th_repeat = client.post(f"/api/study/topics/{first_id}/stage", json={"stage": "theory", "done": True})
    assert r_th_repeat.status_code == 200 and r_th_repeat.json()["xp_delta"] == 0

    r_pr = client.post(f"/api/study/topics/{first_id}/stage", json={"stage": "practice", "done": True})
    assert r_pr.status_code == 200 and r_pr.json()["xp_delta"] == 35
    r_cs = client.post(f"/api/study/topics/{first_id}/stage", json={"stage": "cheatsheet", "done": True})
    assert r_cs.status_code == 200 and r_cs.json()["xp_delta"] == 20
    assert r_cs.json()["overview"]["total_xp"] == 80
    assert r_cs.json()["newly_completed"] is False

    assert client.post(f"/api/study/topics/{first_id}/stage", json={"stage": "bogus", "done": True}).status_code == 422
    assert client.post(
        f"/api/study/topics/{first_id}/quiz", json={"choice_index": 0, "question_index": 9}
    ).status_code == 422

    # Boss Gauntlet: wrong Q0 reveals nothing and adds 0 XP
    quizzes = study.TOPICS_BY_ID[first_id].quizzes
    wrong_q0 = (quizzes[0].correct_index + 1) % len(quizzes[0].choices)
    r_wrong = client.post(
        f"/api/study/topics/{first_id}/quiz", json={"choice_index": wrong_q0, "question_index": 0}
    )
    assert r_wrong.status_code == 200
    assert r_wrong.json()["correct"] is False
    assert r_wrong.json()["correct_index"] is None
    assert r_wrong.json()["xp_delta"] == 0

    # Correct Q0: 1/3 passed, +0 XP until full gauntlet passes
    r_q0 = client.post(
        f"/api/study/topics/{first_id}/quiz",
        json={"choice_index": quizzes[0].correct_index, "question_index": 0},
    )
    assert r_q0.status_code == 200
    q0_data = r_q0.json()
    assert q0_data["correct"] is True
    assert q0_data["correct_index"] == quizzes[0].correct_index
    assert q0_data["quiz_passed_count"] == 1
    assert q0_data["gauntlet_cleared"] is False
    assert q0_data["xp_delta"] == 0

    # Per-question anti-cheat: Q0 exposed, Q1 & Q2 stay hidden
    mid_topic = client.get(f"/api/study/topics/{first_id}").json()
    assert mid_topic["quizzes"][0]["passed"] is True
    assert mid_topic["quizzes"][0]["correct_index"] == quizzes[0].correct_index
    assert "correct_index" not in mid_topic["quizzes"][1]
    assert "correct_index" not in mid_topic["quizzes"][2]

    # Correct Q1: 2/3 passed, still 0 XP
    r_q1 = client.post(
        f"/api/study/topics/{first_id}/quiz",
        json={"choice_index": quizzes[1].correct_index, "question_index": 1},
    )
    assert r_q1.status_code == 200 and r_q1.json()["quiz_passed_count"] == 2 and r_q1.json()["xp_delta"] == 0

    # Correct Q2: 3/3 passed -> +40 XP, topic cleared, streak=1, today_completed=1
    r_q2 = client.post(
        f"/api/study/topics/{first_id}/quiz",
        json={"choice_index": quizzes[2].correct_index, "question_index": 2},
    )
    assert r_q2.status_code == 200
    q2_data = r_q2.json()
    assert q2_data["correct"] is True
    assert q2_data["quiz_passed_count"] == 3
    assert q2_data["gauntlet_cleared"] is True
    assert q2_data["xp_delta"] == 40
    assert q2_data["newly_completed"] is True
    assert q2_data["progress"]["completed"] is True
    assert q2_data["progress"]["xp_earned"] == 120
    assert q2_data["overview"]["total_xp"] == 120
    assert q2_data["overview"]["completed_topics"] == 1
    assert q2_data["overview"]["passed_questions"] == 3
    assert q2_data["overview"]["streak_days"] == 1
    assert q2_data["overview"]["today_completed"] == 1
    assert q2_data["overview"]["recommended_topic_id"] == second_id

    # Re-submitting any cleared question gives 0 extra XP
    r_repeat = client.post(
        f"/api/study/topics/{first_id}/quiz",
        json={"choice_index": quizzes[2].correct_index, "question_index": 2},
    )
    assert r_repeat.status_code == 200
    assert r_repeat.json()["xp_delta"] == 0
    assert r_repeat.json()["newly_completed"] is False


def test_study_drill_deck_and_legacy_migration() -> None:
    db.init_db()
    client = TestClient(main_mod.app)

    # Seed legacy v1 completion row (`quiz_passed=1` with `quiz_passed_mask=0`)
    legacy_id = study.TOPICS[0].id
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO study_progress"
            " (topic_id, theory_done, practice_done, cheatsheet_done, quiz_passed, quiz_passed_mask, quiz_attempts, xp_earned)"
            " VALUES (?, 1, 1, 1, 1, 0, 1, 120)",
            (legacy_id,),
        )

    t0 = client.get(f"/api/study/topics/{legacy_id}").json()
    assert t0["progress"]["quiz_passed"] is True
    assert t0["progress"]["quiz_passed_count"] == 3
    assert t0["progress"]["quiz_passed_mask"] == 7

    # Drill deck excludes passed legacy topic questions and never leaks answers
    r_drill = client.get("/api/study/drill?limit=10")
    assert r_drill.status_code == 200
    drill = r_drill.json()
    assert drill["count"] == 10
    assert len({item["domain"] for item in drill["items"]}) == 5
    for item in drill["items"]:
        assert item["topic_id"] != legacy_id
        assert item["already_passed"] is False
        assert "correct_index" not in item
        assert "explanation" not in item
        assert len(item["choices"]) == 4

    r_storage = client.get("/api/study/drill?domain=Storage&limit=5")
    assert r_storage.status_code == 200
    st_items = r_storage.json()["items"]
    assert len(st_items) == 5
    assert all(item["domain"] == "Storage" for item in st_items)
