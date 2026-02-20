# app/jobs/tasks.py
"""
Simple Redis-based (reliable) task queue for roadmap generation.

Queue pattern:
- Producer LPUSH -> PENDING_Q
- Worker BRPOPLPUSH pending -> processing (atomic, reliable)
- ACK via LREM on processing
- Retry by moving back to pending with attempt increment
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any

import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.settings import settings
from app.db.models.generation_run import GenerationRun
from app.db.models.roadmap import Roadmap
from app.agents.workflow import generate_roadmap_outline

PENDING_Q = "roadmap_generation_queue"
PROCESSING_Q = "roadmap_generation_processing"
MAX_RETRIES = 3

redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def queue_roadmap_generation(run_id: str) -> str:
    """Queue a roadmap generation task and return task_id."""
    task_id = str(uuid.uuid4())
    task_data = {
        "task_id": task_id,
        "run_id": run_id,
        "attempt": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    redis_client.lpush(PENDING_Q, json.dumps(task_data))
    return task_id


def update_run(
    run_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    error: str | None = None,
    result_json: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> None:
    """Best-effort DB update helper."""
    db = SessionLocal()
    try:
        run = db.query(GenerationRun).filter(GenerationRun.id == run_id).first()
        if not run:
            return

        now = datetime.now(timezone.utc)
        if status is not None:
            run.status = status
        if progress is not None:
            run.progress = progress
        if message is not None:
            run.message = message
        if error is not None:
            run.error = error
        if result_json is not None:
            run.result_json = result_json
        if started:
            run.started_at = now
        if finished:
            run.finished_at = now

        db.commit()
    finally:
        db.close()


def generate_roadmap_outline_sync(run_id: str) -> Dict[str, Any]:
    """
    Runs inside worker process.
    Generates a validated RoadmapOutline via Ollama and stores it in generation_runs.result_json.
    """
    db = SessionLocal()
    try:
        run = db.query(GenerationRun).filter(GenerationRun.id == run_id).first()
        if not run:
            return {"ok": False, "error": "run not found"}

        # Idempotency guards
        if run.status in ("succeeded", "failed"):
            return {"ok": True, "skipped": True, "status": run.status}
        if run.status == "running":
            return {"ok": True, "skipped": True, "status": "running"}

        run.status = "running"
        run.progress = 5
        run.message = "Starting generation"
        run.started_at = datetime.now(timezone.utc)
        db.commit()

        rm = db.query(Roadmap).filter(Roadmap.id == run.roadmap_id).first()
        if not rm:
            run.status = "failed"
            run.error = f"Roadmap not found for roadmap_id={run.roadmap_id}"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return {"ok": False, "error": "roadmap not found"}

        # Planner step (LLM)
        run.progress = 20
        run.message = "Planning roadmap outline (LLM)"
        db.commit()

        outline_obj = generate_roadmap_outline(
            rm.field,
            rm.level,
            rm.weekly_hours,
            rm.duration_weeks,
        )
        outline = outline_obj.model_dump()

        run.progress = 85
        run.message = "Saving outline"
        run.result_json = json.dumps(outline)
        db.commit()

        run.status = "succeeded"
        run.progress = 100
        run.message = "Done"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()

        return {"ok": True}

    except Exception as e:
        # Mark failed
        run = db.query(GenerationRun).filter(GenerationRun.id == run_id).first()
        if run:
            run.status = "failed"
            run.error = f"{type(e).__name__}: {e}"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        raise
    finally:
        db.close()


def process_roadmap_generation_queue():
    """Reliable queue consumer: pending -> processing -> ack with retries."""
    while True:
        task_raw = None
        try:
            task_raw = redis_client.brpoplpush(PENDING_Q, PROCESSING_Q, timeout=30)
            if not task_raw:
                continue

            task = json.loads(task_raw)
            run_id = task.get("run_id")
            if not run_id:
                redis_client.lrem(PROCESSING_Q, 1, task_raw)
                continue

            generate_roadmap_outline_sync(run_id)

            # ACK only after successful processing
            redis_client.lrem(PROCESSING_Q, 1, task_raw)

        except Exception as e:
            print(f"Error processing task: {e}")

            if not task_raw:
                continue

            # If task is not valid JSON, drop it from processing to avoid poison pill blocking
            try:
                task = json.loads(task_raw)
            except Exception:
                redis_client.lrem(PROCESSING_Q, 1, task_raw)
                continue

            run_id = task.get("run_id")
            attempt = int(task.get("attempt", 0)) + 1
            task["attempt"] = attempt

            if run_id:
                update_run(
                    run_id,
                    status="running",
                    message=f"Retry {attempt}/{MAX_RETRIES} after error: {type(e).__name__}: {e}",
                )

            if attempt <= MAX_RETRIES:
                redis_client.lrem(PROCESSING_Q, 1, task_raw)
                redis_client.lpush(PENDING_Q, json.dumps(task))
            else:
                if run_id:
                    update_run(
                        run_id,
                        status="failed",
                        error=f"Retries exhausted: {type(e).__name__}: {e}",
                        finished=True,
                    )
                redis_client.lrem(PROCESSING_Q, 1, task_raw)
