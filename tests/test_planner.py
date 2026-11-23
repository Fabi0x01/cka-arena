"""Unit tests for CNCF CKA curriculum catalog and coverage-aware SlotPlanner."""

from app import curriculum, models, planner


def test_curriculum_catalog_covers_all_five_domains():
    domains = {a.domain for a in curriculum.ARCHETYPES}
    assert domains == set(models.DOMAINS)
    assert len(curriculum.ARCHETYPES) >= 30
    assert len(curriculum.CAUSAL_INCIDENTS) >= 5
    # No empty domains for any tier
    for domain in models.DOMAINS:
        for tier in ("exam_standard", "killer_hardcore", "boss_fight"):
            cands = curriculum.eligible_archetypes(
                domain, tier, {"gateway", "helm", "metrics-server", "network_policy", "etcdctl", "local-path"}
            )
            assert cands, f"missing archetypes for {domain}/{tier}"


def test_eligible_archetypes_respects_addons_and_constraints():
    without_gw = curriculum.eligible_archetypes(
        "Services & Networking", "exam_standard", set(), []
    )
    assert all("gateway" not in a.requires_addons for a in without_gw)

    without_helm = curriculum.eligible_archetypes(
        "Cluster Architecture, Installation & Configuration",
        "exam_standard",
        {"metrics-server"},
        ["no helm"],
    )
    assert all("helm" not in a.subtopics and "helm" not in a.id for a in without_helm)


def test_plan_slots_prioritizes_deficit_and_distinct_archetypes():
    coverage = [
        {"domain": "Storage", "difficulty": "exam_standard", "published": 0},
        {"domain": "Troubleshooting", "difficulty": "exam_standard", "published": 9},
        {"domain": "Services & Networking", "difficulty": "exam_standard", "published": 5},
    ]
    recent = [
        {"title": "Old Static Route", "archetype_id": "storage-pvc-bind"},
        {"title": "Old Static Route 2", "archetype_id": "storage-pvc-bind"},
    ]
    slots = planner.plan_slots(
        domains=["Troubleshooting", "Services & Networking", "Storage"],
        difficulty="exam_standard",
        count=3,
        constraints=[],
        available_addons={"gateway", "helm", "metrics-server", "network_policy", "etcdctl", "local-path"},
        coverage_cells=coverage,
        recent_rows=recent,
        seed="test-seed",
    )
    assert len(slots) == 3
    # Deficit domain (Storage=0) is slotted first
    assert slots[0].domain == "Storage"
    # Neutral namespaces, all distinct within batch
    namespaces = [s.namespace for s in slots]
    assert len(set(namespaces)) == 3
    assert all(ns in curriculum.NEUTRAL_NAMESPACES for ns in namespaces)
    # Distinct archetypes and avoids the heavily recent archetype
    assert len({s.archetype.id for s in slots}) == 3
    assert slots[0].archetype.id != "storage-pvc-bind"
    assert "Old Static Route" in slots[0].avoid_titles
    assert slots[0].example_json  # dynamic few-shot loaded from seed


def test_plan_slots_focus_hint_and_boss_fight_incidents():
    slots = planner.plan_slots(
        domains=["Cluster Architecture, Installation & Configuration", "Services & Networking"],
        difficulty="boss_fight",
        count=2,
        constraints=["focus on etcd backup and networkpolicy"],
        available_addons={"gateway", "helm", "metrics-server", "network_policy", "etcdctl", "local-path"},
        coverage_cells=[],
        recent_rows=[],
        seed="boss-seed",
    )
    assert len(slots) == 2
    assert all(s.incident is not None for s in slots)
    assert len({s.incident.id for s in slots if s.incident}) == 2
    # Focus hint prefers etcd archetype in cluster architecture
    ca_slot = next(s for s in slots if s.domain == "Cluster Architecture, Installation & Configuration")
    assert "etcd" in ca_slot.archetype.id or "etcd" in ca_slot.archetype.subtopics
