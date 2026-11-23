"""Seeds: publica no banco (`python -m app.seed`) ou valida gates+probe (`python -m app.seed validate [ids]`)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app import bank, config, db
from app.doctor import ClusterDoctor
from app.events import EventBroker
from app.llm_client import LLMClient
from app.models import ScenarioEnvelope
from app.pipeline import GenerationPipeline
from app.scenario_engine import ScenarioEngine


def seed_dir() -> Path:
    return config.BASE_DIR / "scenarios" / "seed"


def load_seeds() -> list[tuple[Path, ScenarioEnvelope]]:
    seeds: list[tuple[Path, ScenarioEnvelope]] = []
    for path in sorted(seed_dir().glob("*.json")):
        envelope = ScenarioEnvelope.model_validate(json.loads(path.read_text()))
        seeds.append((path, envelope))
    return seeds


async def validate(ids: list[str] | None = None, gates_only: bool = False) -> int:
    """Roda gates determinísticos + Solvability Probe em cada seed (sem publicar).

    gates_only=True: sem cluster (CI) — valida apenas os gates determinísticos.
    """
    engine = ScenarioEngine()
    doctor = ClusterDoctor()
    pipeline = GenerationPipeline(LLMClient(), EventBroker(), engine, doctor)
    failures = 0
    for path, envelope in load_seeds():
        if ids and envelope.id not in ids:
            continue
        errors = await pipeline._gates(envelope)
        if errors:
            failures += 1
            print(f"GATE FAIL   {envelope.id}: {' | '.join(errors)[:400]}")
            continue
        if gates_only:
            print(f"GATES OK    {envelope.id}")
            continue
        ok, detail, _kind = await pipeline._probe(envelope)
        failures += 0 if ok else 1
        print(f"{'PROBE OK  ' if ok else 'PROBE FAIL'} {envelope.id}: {detail[:400]}")
    return failures


def main() -> None:
    args = sys.argv[1:]
    db.init_db()
    if args and args[0] == "validate":
        gates_only = "--gates-only" in args
        ids = [arg for arg in args[1:] if not arg.startswith("--")]
        failures = asyncio.run(validate(ids or None, gates_only=gates_only))
        raise SystemExit(1 if failures else 0)
    created = 0
    for path, envelope in load_seeds():
        result = bank.publish_question(envelope, source="seed")
        created += 1 if result["created"] else 0
        status = "published" if result["created"] else "exists   "
        print(f"{status} {envelope.id} ({path.name}) -> {result['id']}")
    print(f"bank: {bank.count_published()} published ({created} new)")


if __name__ == "__main__":
    main()
