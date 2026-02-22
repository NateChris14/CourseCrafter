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
import traceback
from datetime import datetime, timezone
from typing import Dict, Any

import redis

from app.settings import settings
from app.db.session import SessionLocal
from app.jobs.run_store import update_run

from app.db.models.generation_run import GenerationRun
from app.db.models.roadmap import Roadmap
from app.db.models.course import Course
from app.db.models.course_module import CourseModule

from app.agents.workflow import generate_roadmap_outline

# IMPORTANT: builder-only graph (no PostgresSaver context manager inside the graph module)
from app.graphs.course_generation import build_course_generation_graph_builder
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection

PENDING_Q = "roadmap_generation_queue"
PROCESSING_Q = "roadmap_generation_processing"
MAX_RETRIES = 3


def _to_uuid(v: str | uuid.UUID | None) -> uuid.UUID | None:
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return v
    return uuid.UUID(str(v))


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


# -------------------------
# Queue API (producer)
# -------------------------
def enqueue_job(
    *,
    job_type: str,
    run_id: str,
    course_id: str | None = None,
    overwrite: bool = False,
) -> str:
    task_id = str(uuid.uuid4())
    task_data = {
        "task_id": task_id,
        "type": job_type,  # "generate_roadmap_outline" | "generate_course_modules"
        "run_id": run_id,
        "course_id": course_id,
        "overwrite": bool(overwrite),
        "attempt": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    redis_client.lpush(PENDING_Q, json.dumps(task_data))
    return task_id


def queue_roadmap_generation(run_id: str) -> str:
    return enqueue_job(job_type="generate_roadmap_outline", run_id=run_id)


# -------------------------
# Job handlers (worker)
# -------------------------
def generate_roadmap_outline_sync(run_id: str) -> Dict[str, Any]:
    run_uuid = _to_uuid(run_id)
    if run_uuid is None:
        return {"ok": False, "error": "invalid run_id"}

    db = SessionLocal()
    try:
        run = db.query(GenerationRun).filter(GenerationRun.id == run_uuid).first()
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
        run = db.query(GenerationRun).filter(GenerationRun.id == run_uuid).first()
        if run:
            run.status = "failed"
            run.error = f"{type(e).__name__}: {e}"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        raise
    finally:
        db.close()


def generate_course_modules_langgraph(
    run_id: str,
    course_id: str,
    *,
    overwrite: bool,
) -> Dict[str, Any]:
    """
    Run (or resume) course module generation via LangGraph + Postgres checkpoints.

    Key point: compile + invoke inside the same PostgresSaver context so the
    underlying psycopg connection isn't closed early. [web:1272][web:895]
    """
    if _to_uuid(run_id) is None:
        return {"ok": False, "error": "invalid run_id"}
    if _to_uuid(course_id) is None:
        return {"ok": False, "error": "invalid course_id"}

    builder = build_course_generation_graph_builder()

    # Use PostgresSaver with a persistent connection 
    # Create connection manually and pass it to PostgresSaver
    conn = Connection.connect(settings.langgraph_postgres_dsn)
    checkpointer = PostgresSaver(conn=conn)
    try:
        checkpointer.setup()
        graph = builder.compile(checkpointer=checkpointer)
        graph.invoke(
            {
                "run_id": run_id,
                "course_id": course_id,
                "overwrite": bool(overwrite),
                "pending_weeks": [],
                "done_weeks": [],
                "total": 0,
            },
            config={"configurable": {"thread_id": run_id}},
        )
    finally:
        conn.close()

    return {"ok": True}


# -------------------------
# Worker loop (consumer)
# -------------------------
def process_roadmap_generation_queue():
    print(f"[{_ts()}] [worker] Starting loop. pending={PENDING_Q} processing={PROCESSING_Q}")

    while True:
        task_raw = None
        try:
            task_raw = redis_client.brpoplpush(PENDING_Q, PROCESSING_Q, timeout=30)
            if not task_raw:
                print(f"[{_ts()}] [worker] idle (no jobs)")
                continue

            task = json.loads(task_raw)
            job_type = task.get("type", "generate_roadmap_outline")
            run_id = task.get("run_id")
            course_id = task.get("course_id")
            overwrite = bool(task.get("overwrite", False))

            if not run_id:
                redis_client.lrem(PROCESSING_Q, 1, task_raw)
                continue

            print(
                f"[{_ts()}] [worker] task={task.get('task_id')} type={job_type} run_id={run_id} "
                f"course_id={course_id} overwrite={overwrite} attempt={task.get('attempt')}"
            )

            update_run(run_id, status="running", progress=1, message="Worker picked up job", started=True)

            if job_type == "generate_roadmap_outline":
                print(f"[{_ts()}] [worker] Starting roadmap outline generation")
                generate_roadmap_outline_sync(run_id)

            elif job_type == "generate_course_modules":
                if not course_id:
                    update_run(run_id, status="failed", error="course_id missing in job payload", finished=True)
                else:
                    print(f"[{_ts()}] [worker] Starting course modules generation (LangGraph)")
                    generate_course_modules_langgraph(run_id, course_id, overwrite=overwrite)

            else:
                update_run(run_id, status="failed", error=f"Unknown job type: {job_type}", finished=True)

            redis_client.lrem(PROCESSING_Q, 1, task_raw)

        except Exception as e:
            print(f"[{_ts()}] [worker] Error processing task (full traceback below):")
            traceback.print_exc()

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
