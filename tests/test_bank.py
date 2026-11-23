"""Testes do banco de questões: hash semântico e dedup."""

from __future__ import annotations

import json

from app import bank, config, db
from app.models import ScenarioEnvelope


def _seed_envelope() -> ScenarioEnvelope:
    return ScenarioEnvelope.model_validate(
        json.loads((config.BASE_DIR / "scenarios" / "seed" / "ts-crashloop-fix.json").read_text())
    )


def test_envelope_hash_is_deterministic_and_title_normalized() -> None:
    env = _seed_envelope()
    assert bank.envelope_hash(env) == bank.envelope_hash(env)
    other = env.model_copy(update={"title": "Fix a CrashLooping Deployment!!!"})
    assert bank.envelope_hash(env) == bank.envelope_hash(other)
    different = env.model_copy(update={"subtopics": ["Other"]})
    assert bank.envelope_hash(env) != bank.envelope_hash(different)


def test_publish_dedups_by_hash(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init_db()
    env = _seed_envelope()

    first = bank.publish_question(env, source="seed")
    second = bank.publish_question(env, source="seed")

    assert first["created"] is True
    assert second["created"] is False
    assert first["id"] == second["id"]
    assert bank.count_published() == 1
    assert bank.coverage() == [
        {"domain": "Troubleshooting", "difficulty": "exam_standard", "published": 1}
    ]


def _insert_synthetic(conn, domain, count, difficulty="exam_standard", prefix="syn"):
    for index in range(count):
        conn.execute(
            "INSERT INTO bank_questions (id, envelope_json, envelope_hash, domain, subtopics_json,"
            " difficulty, weight_pct, estimated_minutes, source, state, created_at)"
            " VALUES (?, '{}', ?, ?, '[]', ?, 4, 4, 'seed', 'published', 0)",
            (f"{prefix}-{domain[:4]}-{index}", f"hash-{prefix}-{domain[:4]}-{index}", domain, difficulty),
        )


def test_largest_remainder_allocation() -> None:
    assert list(bank.largest_remainder(15, bank.WEIGHTS).values()) == [5, 4, 3, 2, 1]
    assert list(bank.largest_remainder(5, bank.WEIGHTS).values()) == [2, 1, 1, 1, 0]
    assert list(bank.largest_remainder(3, bank.WEIGHTS).values()) == [1, 1, 1, 0, 0]


def test_draw_exam_sample_respects_exam_percentages(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init_db()
    with db.connect() as conn:
        for domain, count in zip(bank.WEIGHTS, [5, 4, 3, 2, 1]):
            _insert_synthetic(conn, domain, count)

    sample = bank.draw_exam_sample(15)
    assert sample["returned"] == 15
    counts = {}
    for item in sample["items"]:
        counts[item["domain"]] = counts.get(item["domain"], 0) + 1
    assert counts == {domain: n for domain, n in zip(bank.WEIGHTS, [5, 4, 3, 2, 1])}

    small = bank.draw_exam_sample(5)
    small_counts = {}
    for item in small["items"]:
        small_counts[item["domain"]] = small_counts.get(item["domain"], 0) + 1
    assert small_counts == {domain: n for domain, n in zip(bank.WEIGHTS, [2, 1, 1, 1])}

    no_repeat = bank.draw_exam_sample(15)["items"]
    assert len({item["id"] for item in no_repeat}) == 15


def test_draw_falls_back_when_cells_are_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init_db()
    with db.connect() as conn:
        _insert_synthetic(conn, "Troubleshooting", 3)

    sample = bank.draw_exam_sample(5)
    assert sample["returned"] == 3
    assert sample["fallbacks"], "deve sinalizar células vazias"
