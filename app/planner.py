"""Slot Planner — coverage-aware CKA curriculum assignment and anti-duplication."""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.curriculum import (
    ARCHETYPES_BY_ID,
    NEUTRAL_NAMESPACES,
    Archetype,
    CausalIncidentBlueprint,
    eligible_archetypes,
    eligible_incidents,
    load_seed_example,
)


@dataclass
class SlotPlan:
    slot_index: int
    domain: str
    difficulty: str
    archetype: Archetype
    incident: CausalIncidentBlueprint | None
    namespace: str
    secondary_namespace: str | None
    avoid_titles: list[str]
    example_json: str


def _focus_score(arch: Archetype, constraints: list[str]) -> int:
    if not constraints:
        return 0
    blob = " ".join(constraints).lower()
    haystack = " ".join([arch.id, *arch.subtopics, arch.guidance]).lower()
    words = [w for w in blob.replace(",", " ").split() if len(w) >= 3 and w not in ("no", "not", "exclude", "only", "with", "and")]
    return sum(1 for w in words if w in haystack)


def plan_slots(
    *,
    domains: list[str],
    difficulty: str,
    count: int,
    constraints: list[str],
    available_addons: set[str],
    coverage_cells: list[dict],
    recent_rows: list[dict],
    seed: str | None = None,
    target_archetype_id: str | None = None,
) -> list[SlotPlan]:
    """Assign distinct domains (deficit-first), archetypes, neutral namespaces, and few-shots."""
    rng = random.Random(seed)
    cell_counts: dict[tuple[str, str], int] = {
        (row["domain"], row["difficulty"]): int(row.get("published") or 0)
        for row in coverage_cells
    }
    recent_archetypes: dict[str, int] = {}
    recent_titles: list[str] = []
    for row in recent_rows:
        aid = row.get("archetype_id")
        if aid:
            recent_archetypes[aid] = recent_archetypes.get(aid, 0) + 1
        title = (row.get("title") or "").strip()
        if title:
            recent_titles.append(title)

    # Order domains by deficit for this difficulty, rotating cleanly across N slots
    domain_order = sorted(
        domains,
        key=lambda d: (cell_counts.get((d, difficulty), 0), rng.random()),
    )

    ns_pool = list(NEUTRAL_NAMESPACES)
    rng.shuffle(ns_pool)
    used_archetypes: set[str] = set()
    used_incidents: set[str] = set()
    plans: list[SlotPlan] = []
    pinned_arch = ARCHETYPES_BY_ID.get(target_archetype_id) if target_archetype_id else None

    for idx in range(count):
        if pinned_arch and idx == 0:
            archetype = pinned_arch
            domain = archetype.domain
        else:
            domain = domain_order[idx % len(domain_order)]
            candidates = eligible_archetypes(domain, difficulty, available_addons, constraints)
            if not candidates:
                candidates = eligible_archetypes(domains[0], difficulty, available_addons, constraints)

            # Prefer unused in this batch, matching focus hint, and least used recently in DB
            ranked = sorted(
                candidates,
                key=lambda a: (
                    1 if a.id in used_archetypes else 0,
                    -_focus_score(a, constraints),
                    recent_archetypes.get(a.id, 0),
                    rng.random(),
                ),
            )
            archetype = ranked[0]
        used_archetypes.add(archetype.id)

        incident: CausalIncidentBlueprint | None = None
        if difficulty == "boss_fight":
            inc_candidates = eligible_incidents(domain, available_addons, constraints)
            if inc_candidates:
                inc_ranked = sorted(
                    inc_candidates,
                    key=lambda inc: (1 if inc.id in used_incidents else 0, rng.random()),
                )
                incident = inc_ranked[0]
                used_incidents.add(incident.id)

        ns = ns_pool[idx % len(ns_pool)]
        if idx >= len(ns_pool):
            ns = f"{ns}-{idx + 1}"
        secondary_ns = None
        if "multi-ns" in archetype.id or difficulty == "killer_hardcore" and "multi" in archetype.guidance.lower():
            secondary_ns = f"{ns}-edge"

        seed_file = incident.example_seed if incident else archetype.example_seed
        plans.append(
            SlotPlan(
                slot_index=idx,
                domain=domain,
                difficulty=difficulty,
                archetype=archetype,
                incident=incident,
                namespace=ns,
                secondary_namespace=secondary_ns,
                avoid_titles=recent_titles[:15],
                example_json=load_seed_example(seed_file),
            )
        )

    return plans
