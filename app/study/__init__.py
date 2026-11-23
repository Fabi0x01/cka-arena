"""CKA Study Codex v2 — structured CNCF syllabus curriculum, XP progression, and Boss Gauntlets."""

from app.study.models import (
    CheatItem,
    ComparisonRow,
    DebugRow,
    PracticeStep,
    RecallQuiz,
    StudyDocLink,
    StudyTopic,
)
from app.study.service import (
    DAILY_TOPIC_GOAL,
    MAX_TOTAL_XP,
    RANKS,
    STAGE_XP,
    TOPIC_MAX_XP,
    TOPICS,
    TOPICS_BY_ID,
    get_drill_deck,
    get_overview,
    get_topic,
    set_stage,
    submit_quiz,
)

__all__ = [
    "CheatItem",
    "ComparisonRow",
    "DAILY_TOPIC_GOAL",
    "DebugRow",
    "MAX_TOTAL_XP",
    "PracticeStep",
    "RANKS",
    "RecallQuiz",
    "STAGE_XP",
    "StudyDocLink",
    "StudyTopic",
    "TOPIC_MAX_XP",
    "TOPICS",
    "TOPICS_BY_ID",
    "get_drill_deck",
    "get_overview",
    "get_topic",
    "set_stage",
    "submit_quiz",
]
