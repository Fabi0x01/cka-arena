"""Dataclasses for CKA Study Codex v2 topics, decision matrices, playbooks, and quizzes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class StudyDocLink:
    label: str
    url: str
    exam_search_term: str


@dataclass(frozen=True)
class ComparisonRow:
    concept: str
    behavior: str
    when_to_use: str


@dataclass(frozen=True)
class DebugRow:
    symptom: str
    cause: str
    fix: str


@dataclass(frozen=True)
class PracticeStep:
    title: str
    explanation: str
    command: str
    yaml_snippet: str = ""
    verify_command: str = ""
    expected_output: str = ""


@dataclass(frozen=True)
class CheatItem:
    label: str
    command: str
    note: str = ""


@dataclass(frozen=True)
class RecallQuiz:
    question: str
    choices: tuple[str, ...]
    correct_index: int
    explanation: str
    tag: str = "Scenario"


@dataclass(frozen=True)
class StudyTopic:
    id: str
    order: int
    domain: str
    title: str
    subtitle: str
    estimated_minutes: int
    exam_frequency: Literal["High", "Core", "Critical"]
    archetype_ids: tuple[str, ...]
    summary: str
    architecture_flow: str
    theory_points: tuple[str, ...]
    decision_matrix: tuple[ComparisonRow, ...]
    docs_links: tuple[StudyDocLink, ...]
    practice_steps: tuple[PracticeStep, ...]
    debug_playbook: tuple[DebugRow, ...]
    exam_trap: str
    cheatsheet: tuple[CheatItem, ...]
    yaml_template: str
    quizzes: tuple[RecallQuiz, ...]

    @property
    def quiz(self) -> RecallQuiz:
        return self.quizzes[0]
