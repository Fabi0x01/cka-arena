"""CLI benchmark & offline evaluation runner: python -m app.pipeline eval."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

from app import db, doctor as doc_mod, events, llm_client, scenario_engine
from app.models import DIFFICULTIES, DOMAINS
from app.pipeline.orchestrator import GenerateRequest, GenerationPipeline


async def _run_eval(count: int, difficulties: list[str], publish: bool) -> dict:
    db.init_db()
    client = llm_client.LLMClient()
    broker = events.EventBroker()
    engine = scenario_engine.ScenarioEngine()
    doctor = doc_mod.ClusterDoctor()
    pipeline = GenerationPipeline(client, broker, engine, doctor)

    results: list[dict] = []
    started = time.monotonic()
    for idx in range(count):
        diff = difficulties[idx % len(difficulties)]
        domain = DOMAINS[idx % len(DOMAINS)]
        slot_start = time.monotonic()
        req = GenerateRequest(domains=[domain], difficulty=diff, count=1)
        job_id = await pipeline.start(req)
        while pipeline.active_job_id == job_id:
            await asyncio.sleep(0.5)
        snap = pipeline.snapshot() or {}
        lat = round(time.monotonic() - slot_start, 2)
        pub_ids = snap.get("published") or []
        sc_meta = next(iter((snap.get("scenarios") or {}).values()), {})
        q_score = sc_meta.get("quality_score")
        entry = {
            "slot": idx + 1,
            "domain": domain,
            "difficulty": diff,
            "published": len(pub_ids) > 0,
            "question_id": pub_ids[0] if pub_ids else None,
            "quality_score": q_score,
            "attempts": sc_meta.get("attempts"),
            "latency_s": lat,
            "error": None if pub_ids else sc_meta.get("detail") or snap.get("error"),
        }
        if not publish and pub_ids:
            # Clean up benchmark item if --no-publish passed
            from app import bank

            bank.delete_question(pub_ids[0])
        results.append(entry)

    await client.aclose()
    pub_count = sum(1 for r in results if r["published"])
    scores = [float(r["quality_score"]) for r in results if r["quality_score"] is not None]
    lats = [float(r["latency_s"]) for r in results]
    return {
        "total": len(results),
        "published": pub_count,
        "publish_rate_pct": round(100.0 * pub_count / max(1, len(results)), 1),
        "avg_quality_score": round(statistics.mean(scores), 1) if scores else None,
        "median_latency_s": round(statistics.median(lats), 2) if lats else None,
        "elapsed_s": round(time.monotonic() - started, 2),
        "items": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ev = sub.add_parser("eval", help="Run generation benchmark across specified difficulties")
    ev.add_argument("--count", type=int, default=3)
    ev.add_argument(
        "--difficulties",
        type=str,
        default="exam_standard,killer_hardcore,boss_fight",
        help="Comma-separated difficulties",
    )
    ev.add_argument("--no-publish", action="store_true", help="Delete benchmark questions after run")
    args = parser.parse_args(argv)
    if args.cmd == "eval":
        diffs = [d.strip() for d in args.difficulties.split(",") if d.strip() in DIFFICULTIES]
        if not diffs:
            diffs = ["exam_standard", "killer_hardcore", "boss_fight"]
        summary = asyncio.run(_run_eval(max(1, args.count), diffs, publish=not args.no_publish))
        print(json.dumps(summary, indent=2))
        return 0 if summary["published"] > 0 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
