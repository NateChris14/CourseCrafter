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

from app.settings import settings
from app.db.session import SessionLocal
from app.jobs.run_store import update_run
from app.logger import GLOBAL_LOGGER as logger
from app.exceptions.custom_exception import DocumentPortalException

from app.db.models.generation_run import GenerationRun
from app.db.models.roadmap import Roadmap
from app.db.models.course import Course
from app.db.models.course_module import CourseModule
from sqlalchemy.orm import joinedload

from app.agents.workflow import generate_roadmap_outline
from app.graphs.course_generation import build_course_generation_graph_builder

from dotenv import load_dotenv
load_dotenv()

PENDING_Q = "roadmap_generation_queue"
PROCESSING_Q = "roadmap_generation_processing"
MAX_RETRIES = 3


def _to_uuid(v: str | uuid.UUID | None) -> uuid.UUID | None:
    """Convert string or UUID to UUID object, handling None values."""
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return v
    return uuid.UUID(str(v))


def _ts() -> str:
    """Get current UTC timestamp as formatted string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# Use Redis pipeline for batch operations
redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def get_queue_status() -> Dict[str, Any]:
    """Get current queue status for display to users."""
    # Use Redis pipeline for batch operations
    with redis_client.pipeline() as pipe:
        pending = pipe.lrange(PENDING_Q, 0, -1)
        processing = pipe.lrange(PROCESSING_Q, 0, -1)
        results = pipe.execute()
    
    pending = results[0]
    processing = results[1]

    pending_tasks = []
    for item in pending:
        try:
            task = json.loads(item)
            pending_tasks.append({
                "task": task, 
                "run_status": "queued",
                "attempt": task.get("attempt", 0),
                "timestamp": task.get("timestamp"),
                "progress": 0,
                "message": "Waiting to start",
            })
        except json.JSONDecodeError:
            continue

    processing_tasks = []
    for item in processing:
        try:
            task = json.loads(item)
            processing_tasks.append({
                "task": task, 
                "run_status": "processing",
                "attempt": task.get("attempt", 0),
                "timestamp": task.get("timestamp"),
                "progress": 0,
                "message": "Processing...",
            })
        except json.JSONDecodeError:
            continue

    return {
        "pending_count": len(pending_tasks),
        "processing_count": len(processing_tasks),
        "pending": pending_tasks,
        "processing": processing_tasks,
    }


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
    """Enqueue a job for processing.
    
    Args:
        job_type: Type of job ('generate_roadmap_outline' or 'generate_course_modules')
        run_id: Generation run ID
        course_id: Optional course ID for module generation jobs
        overwrite: Whether to overwrite existing content
        
    Returns:
        Task ID for the enqueued job
    """
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
    """Convenience function to enqueue a roadmap generation job.
    
    Args:
        run_id: Generation run ID
        
    Returns:
        Task ID for the enqueued job
    """
    return enqueue_job(job_type="generate_roadmap_outline", run_id=run_id)


# -------------------------
# Queue management
# -------------------------
def clear_pending_queue() -> int:
    """Clear all pending jobs from the queue. Returns number of jobs removed."""
    count = 0
    while redis_client.lpop(PENDING_Q):
        count += 1
    return count


def stop_processing_job(run_id: str) -> bool:
    """Remove a specific job from the processing queue and mark it as failed."""
    # Find and remove from processing queue
    processing = redis_client.lrange(PROCESSING_Q, 0, -1)
    for item in processing:
        try:
            task = json.loads(item)
            if task.get("run_id") == run_id:
                redis_client.lrem(PROCESSING_Q, 1, item)
                # Mark run as failed
                update_run(run_id, status="failed", error="Cancelled by user", finished=True)
                return True
        except Exception:
            continue
    return False


def clear_processing_queue() -> int:
    """Clear all jobs from processing queue and mark them as failed. Returns number of jobs removed."""
    count = 0
    processing = redis_client.lrange(PROCESSING_Q, 0, -1)
    for item in processing:
        try:
            task = json.loads(item)
            run_id = task.get("run_id")
            if run_id:
                update_run(run_id, status="failed", error="Cancelled by user (queue cleared)", finished=True)
            redis_client.lrem(PROCESSING_Q, 1, item)
            count += 1
        except Exception:
            continue
    return count


def cancel_job_by_run_id(run_id: str) -> Dict[str, Any]:
    """Cancel a job by run_id - removes from pending or processing and marks as failed."""
    # Check pending queue
    pending = redis_client.lrange(PENDING_Q, 0, -1)
    for item in pending:
        try:
            task = json.loads(item)
            if task.get("run_id") == run_id:
                redis_client.lrem(PENDING_Q, 1, item)
                update_run(run_id, status="failed", error="Cancelled by user", finished=True)
                return {"ok": True, "removed_from": "pending"}
        except Exception:
            continue

    # Check processing queue
    if stop_processing_job(run_id):
        return {"ok": True, "removed_from": "processing"}

    # Job not found in queues, but mark as failed anyway
    update_run(run_id, status="failed", error="Cancelled by user", finished=True)
    return {"ok": True, "removed_from": "none", "note": "Job was not in queue"}


# -------------------------
# Job handlers (worker)
# -------------------------
def generate_roadmap_outline_sync(run_id: str) -> Dict[str, Any]:
    """Generate roadmap outline synchronously.
    
    Creates course structure with weekly modules based on roadmap requirements.
    Updates generation run status throughout the process.
    
    Args:
        run_id: Generation run ID
        
    Returns:
        Dict with success status and course_id if successful
        
    Raises:
        DocumentPortalException: If generation fails
    """
    run_uuid = _to_uuid(run_id)
    if run_uuid is None:
        return {"ok": False, "error": "invalid run_id"}

    db = SessionLocal()
    try:
        # Use eager loading to avoid N+1 problems
        run = db.query(GenerationRun).options(
            joinedload(GenerationRun.roadmap)
        ).filter(GenerationRun.id == run_uuid).first()
        
        if not run:
            return {"ok": False, "error": "run not found"}

        if run.status in ("succeeded", "failed"):
            return {"ok": True, "skipped": True, "status": run.status}
        if run.status == "running":
            return {"ok": True, "skipped": True, "status": "running"}

        # Batch all updates together to reduce database round trips
        run.status = "running"
        run.progress = 5
        run.message = "Starting outline generation"
        run.started_at = datetime.now(timezone.utc)
        
        # Check if roadmap exists in same query
        rm = run.roadmap  # Already loaded via eager loading
        if not rm:
            run.status = "failed"
            run.error = f"Roadmap not found for roadmap_id={run.roadmap_id}"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return {"ok": False, "error": "roadmap not found"}

        run.progress = 20
        run.message = "Planning roadmap outline (LLM)"
        db.commit()

        logger.info(f"[generate_roadmap_outline_sync] Starting LLM call for roadmap: {rm.title}")
        logger.info(f"[generate_roadmap_outline_sync] Field: {rm.field}, Level: {rm.level}, Weeks: {rm.duration_weeks}")
        
        outline_obj = generate_roadmap_outline(
            rm.field, rm.level, rm.weekly_hours, rm.duration_weeks
        )
        
        logger.info(f"[generate_roadmap_outline_sync] LLM call completed successfully")
        outline = outline_obj.model_dump()

        run.progress = 60
        run.message = "Creating course structure"
        db.commit()

        # Batch course and module creation
        course = Course(
            user_id=run.user_id,
            roadmap_id=rm.id,
            status="draft",
            title=f"{rm.title} (AI-generated)",
            description=f"{rm.duration_weeks}-week roadmap for {rm.field}, level {rm.level}.",
        )
        db.add(course)
        db.flush()  # Get course.id without committing

        # Batch insert all modules at once
        modules_data = []
        for w in outline["weeks"]:
            modules_data.append({
                "course_id": course.id,
                "week": int(w["week"]),
                "title": w["title"],
                "outcomes_json": json.dumps(w["outcomes"]),
                "content_md": None,
            })
        
        db.bulk_insert_mappings(CourseModule, modules_data)  # Bulk insert for performance
        run.course_id = course.id

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
        logger.error(f"[generate_roadmap_outline_sync] Error: {str(e)}")
        run = db.query(GenerationRun).filter(GenerationRun.id == run_uuid).first()
        if run:
            run.status = "failed"
            run.error = f"{type(e).__name__}: {e}"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        raise DocumentPortalException("Failed to generate roadmap outline", e)
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

    Compile+invoke inside the PostgresSaver context manager so the underlying
    connection stays open during execution. [web:904]
    """
    logger.debug(f"[generate_course_modules_langgraph] START run_id={run_id} course_id={course_id} overwrite={overwrite}")
    if _to_uuid(run_id) is None:
        return {"ok": False, "error": "invalid run_id"}
    if _to_uuid(course_id) is None:
        return {"ok": False, "error": "invalid course_id"}

    from langgraph.checkpoint.postgres import PostgresSaver

    builder = build_course_generation_graph_builder()

    thread_id = str(run_id)
    config = {"configurable": {"thread_id": thread_id}}

    logger.debug(f"[generate_course_modules_langgraph] thread_id={thread_id} config={config}")

    try:
        with PostgresSaver.from_conn_string(settings.langgraph_postgres_dsn) as checkpointer:
            checkpointer.setup()

            # Check if there's existing checkpoint state
            existing_state = checkpointer.get(config)
            logger.debug(f"[generate_course_modules_langgraph] existing checkpoint state: {existing_state}")

            graph = builder.compile(checkpointer=checkpointer)

            logger.debug(f"[generate_course_modules_langgraph] invoking graph with initial state...")
            graph.invoke(
                {
                    "run_id": str(run_id),
                    "course_id": str(course_id),
                    "overwrite": bool(overwrite),
                    "pending_weeks": [],
                    "done_weeks": [],
                    "total": 0,
                },
                config=config,
            )

        logger.debug("[generate_course_modules_langgraph] END")
        return {"ok": True}
    except Exception as e:
        logger.error(f"[generate_course_modules_langgraph] Error: {str(e)}")
        raise DocumentPortalException("Failed to generate course modules", e)


# -------------------------
# Worker loop (consumer)
# -------------------------
def process_roadmap_generation_queue():
    """Worker loop that processes jobs from the Redis queue.
    
    Continuously polls for jobs, processes them based on type,
    and handles retries on failure. Runs indefinitely.
    
    Job types:
    - generate_roadmap_outline: Creates course structure
    - generate_course_modules: Generates detailed module content
    """
    logger.info(f"[worker] Starting loop. pending={PENDING_Q} processing={PROCESSING_Q}")

    while True:
        task_raw = None  # Initialize before try block
        try:
            task_raw = redis_client.brpoplpush(PENDING_Q, PROCESSING_Q, timeout=30)
            if not task_raw:
                logger.debug(f"[worker] idle (no jobs)")
                continue

            task = json.loads(task_raw)
            job_type = task.get("type", "generate_roadmap_outline")
            run_id = task.get("run_id")
            course_id = task.get("course_id")
            overwrite = bool(task.get("overwrite", False))

            if not run_id:
                redis_client.lrem(PROCESSING_Q, 1, task_raw)
                continue

            logger.info(
                f"[worker] task={task.get('task_id')} type={job_type} run_id={run_id} "
                f"course_id={course_id} overwrite={overwrite} attempt={task.get('attempt')}"
            )

            update_run(run_id, status="running", progress=1, message="Worker picked up job", started=True)

            if job_type == "generate_roadmap_outline":
                generate_roadmap_outline_sync(run_id)

            elif job_type == "generate_course_modules":
                if not course_id:
                    update_run(run_id, status="failed", error="course_id missing in job payload", finished=True)
                else:
                    generate_course_modules_langgraph(run_id, course_id, overwrite=overwrite)

            else:
                update_run(run_id, status="failed", error=f"Unknown job type: {job_type}", finished=True)

            redis_client.lrem(PROCESSING_Q, 1, task_raw)

        except Exception as e:
            logger.error(f"[worker] Error processing task: {str(e)}")
            
            # If we have a task_raw, remove it from processing queue
            if task_raw:
                try:
                    task = json.loads(task_raw)
                    run_id = task.get("run_id")
                    attempt = int(task.get("attempt", 0)) + 1
                    task["attempt"] = attempt

                    logger.warning(f"[worker] Retrying task. run_id={run_id} attempt={attempt}/{MAX_RETRIES} error={type(e).__name__}: {e}")

                    if run_id:
                        update_run(
                            run_id,
                            status="running",
                            progress=1,  # Reset progress on retry
                            message=f"Retry {attempt}/{MAX_RETRIES} after error: {type(e).__name__}",
                        )

                    if attempt <= MAX_RETRIES:
                        redis_client.lrem(PROCESSING_Q, 1, task_raw)
                        redis_client.lpush(PENDING_Q, json.dumps(task))
                    else:
                        # Max retries exceeded, mark as failed
                        redis_client.lrem(PROCESSING_Q, 1, task_raw)
                        update_run(run_id, status="failed", error=f"Max retries ({MAX_RETRIES}) exceeded", finished=True)
                except json.JSONDecodeError:
                    redis_client.lrem(PROCESSING_Q, 1, task_raw)
            else:
                logger.error(f"[worker] Max retries exceeded for unknown task")
