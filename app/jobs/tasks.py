# app/jobs/tasks.py
"""
Redis-based (reliable) task queue for generation.

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
from app.db.models.course import Course
from app.db.models.course_module import CourseModule
from app.agents.workflow import generate_roadmap_outline
from app.agents.module_writer import write_module_markdown

PENDING_Q = "roadmap_generation_queue"
PROCESSING_Q = "roadmap_generation_processing"
MAX_RETRIES = 3

redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# -------------------------
# Queue API (producer)
# -------------------------
def enqueue_job(*, job_type: str, run_id: str, course_id: str | None = None) -> str:
    """Enqueue a job into Redis and return task_id."""
    task_id = str(uuid.uuid4())
    task_data = {
        "task_id": task_id,
        "type": job_type,  # "generate_roadmap_outline" | "generate_course_modules"
        "run_id": run_id,
        "course_id": course_id,
        "attempt": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    redis_client.lpush(PENDING_Q, json.dumps(task_data))
    return task_id


def queue_roadmap_generation(run_id: str) -> str:
    """Backward compatible wrapper."""
    return enqueue_job(job_type="generate_roadmap_outline", run_id=run_id)


# -------------------------
# DB helper
# -------------------------
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


# -------------------------
# Job handlers (worker)
# -------------------------
def generate_roadmap_outline_sync(run_id: str) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        run = db.query(GenerationRun).filter(GenerationRun.id == run_id).first()
        if not run:
            return {"ok": False, "error": "run not found"}

        if run.status in ("succeeded", "failed"):
            return {"ok": True, "skipped": True, "status": run.status}
        if run.status == "running":
            return {"ok": True, "skipped": True, "status": "running"}

        run.status = "running"
        run.progress = 5
        run.message = "Starting outline generation"
        run.started_at = datetime.now(timezone.utc)
        db.commit()

        rm = db.query(Roadmap).filter(Roadmap.id == run.roadmap_id).first()
        if not rm:
            run.status = "failed"
            run.error = f"Roadmap not found for roadmap_id={run.roadmap_id}"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return {"ok": False, "error": "roadmap not found"}

        run.progress = 20
        run.message = "Planning roadmap outline (LLM)"
        db.commit()

        outline_obj = generate_roadmap_outline(
            rm.field, rm.level, rm.weekly_hours, rm.duration_weeks
        )
        outline = outline_obj.model_dump()

        run.progress = 60
        run.message = "Creating course structure"
        db.commit()

        course = Course(
            user_id=run.user_id,
            roadmap_id=rm.id,
            status="draft",
            title=f"{rm.title} (AI-generated)",
            description=f"{rm.duration_weeks}-week roadmap for {rm.field}, level {rm.level}.",
        )
        db.add(course)
        db.flush()

        run.course_id = course.id

        for w in outline["weeks"]:
            db.add(
                CourseModule(
                    course_id=course.id,
                    week=int(w["week"]),
                    title=w["title"],
                    outcomes_json=json.dumps(w["outcomes"]),
                    content_md=None,
                )
            )

        run.progress = 85
        run.message = "Saving outline + course structure"
        run.result_json = json.dumps(outline)
        db.commit()

        run.status = "succeeded"
        run.progress = 100
        run.message = "Done"
        run.finished_at = datetime.now(timezone.utc)
        course.status = "ready"
        db.commit()

        return {"ok": True, "course_id": str(course.id)}

    except Exception as e:
        run = db.query(GenerationRun).filter(GenerationRun.id == run_id).first()
        if run:
            run.status = "failed"
            run.error = f"{type(e).__name__}: {e}"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        raise
    finally:
        db.close()


def generate_course_modules_sync(run_id: str, course_id: str) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        run = db.query(GenerationRun).filter(GenerationRun.id == run_id).first()
        if not run:
            return {"ok": False, "error": "run not found"}

        course = (
            db.query(Course)
            .filter(Course.id == course_id, Course.user_id == run.user_id)
            .first()
        )
        if not course:
            update_run(run_id, status="failed", error="course not found", finished=True)
            return {"ok": False, "error": "course not found"}

        rm = db.query(Roadmap).filter(Roadmap.id == course.roadmap_id).first()
        if not rm:
            update_run(run_id, status="failed", error="roadmap not found for course", finished=True)
            return {"ok": False, "error": "roadmap not found"}

        modules = (
            db.query(CourseModule)
            .filter(CourseModule.course_id == course.id)
            .order_by(CourseModule.week.asc())
            .all()
        )
        if not modules:
            update_run(run_id, status="failed", error="No modules found", finished=True)
            return {"ok": False, "error": "no modules found"}

        run.course_id = course.id
        db.commit()

        update_run(
            run_id,
            status="running",
            progress=5,
            message="Generating module content (Markdown)",
            started=True,
        )

        total = len(modules)
        for i, m in enumerate(modules, start=1):
            if m.content_md and m.content_md.strip():
                continue

            outcomes = json.loads(m.outcomes_json)

            update_run(
                run_id,
                progress=int(5 + (i - 1) * (90 / total)),
                message=f"Writing week {m.week}/{total}: {m.title}",
            )

            md = write_module_markdown(
                field=rm.field,
                level=rm.level,
                week=m.week,
                title=m.title,
                outcomes=outcomes,
            )
            m.content_md = md
            db.commit()

        course.status = "ready"
        db.commit()

        update_run(
            run_id,
            status="succeeded",
            progress=100,
            message="Course content ready",
            finished=True,
        )
        return {"ok": True}

    except Exception as e:
        update_run(run_id, status="failed", error=f"{type(e).__name__}: {e}", finished=True)
        raise
    finally:
        db.close()


# -------------------------
# Worker loop (consumer)
# -------------------------
def process_roadmap_generation_queue():
    """Reliable queue consumer: pending -> processing -> ack with retries."""
    while True:
        task_raw = None
        try:
            task_raw = redis_client.brpoplpush(PENDING_Q, PROCESSING_Q, timeout=30)
            if not task_raw:
                continue

            task = json.loads(task_raw)
            job_type = task.get("type", "generate_roadmap_outline")
            run_id = task.get("run_id")
            course_id = task.get("course_id")

            if not run_id:
                redis_client.lrem(PROCESSING_Q, 1, task_raw)
                continue

            if job_type == "generate_roadmap_outline":
                generate_roadmap_outline_sync(run_id)
            elif job_type == "generate_course_modules":
                if not course_id:
                    update_run(run_id, status="failed", error="course_id missing in job payload", finished=True)
                else:
                    generate_course_modules_sync(run_id, course_id)
            else:
                update_run(run_id, status="failed", error=f"Unknown job type: {job_type}", finished=True)

            redis_client.lrem(PROCESSING_Q, 1, task_raw)

        except Exception as e:
            print(f"Error processing task: {e}")

            if not task_raw:
                continue

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
