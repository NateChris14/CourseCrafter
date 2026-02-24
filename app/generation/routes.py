# app/generation/routes.py
import uuid
import gzip

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth.deps import get_current_user
from app.db.models.user import User
from app.db.models.roadmap import Roadmap
from app.db.models.course import Course
from app.db.models.generation_run import GenerationRun
from app.jobs.tasks import enqueue_job, get_queue_status, clear_pending_queue, clear_processing_queue, cancel_job_by_run_id, queue_roadmap_generation
from app.logger import GLOBAL_LOGGER as logger
from app.exceptions.custom_exception import DocumentPortalException

router = APIRouter(prefix="/generation")


@router.post("/roadmaps/{roadmap_id}/generate")
def start_generation(
    roadmap_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    logger.info(f"[start_generation] Starting generation for roadmap_id: {roadmap_id}, user_id: {user.id}")
    
    rm = (
        db.query(Roadmap)
        .filter(Roadmap.id == roadmap_id, Roadmap.user_id == user.id)
        .first()
    )
    if not rm:
        logger.warning(f"[start_generation] Roadmap not found: {roadmap_id}")
        return RedirectResponse(url="/roadmaps?error=not_found", status_code=303)

    logger.info(f"[start_generation] Found roadmap: {rm.title}")

    run = GenerationRun(
        user_id=user.id,
        roadmap_id=rm.id,
        status="queued",
        progress=0,
        message="Queued",
    )
    db.add(run)
    db.flush()  # ensures run.id exists without committing yet
    logger.info(f"[start_generation] Created generation run: {run.id}")

    # Queue task using Redis queue
    task_id = queue_roadmap_generation(str(run.id))
    run.celery_task_id = task_id  # legacy field; rename later if you want
    logger.info(f"[start_generation] Queued task: {task_id}")

    db.commit()
    logger.info(f"[start_generation] Database committed, redirecting to: /roadmaps/{rm.id}?run={run.id}")

    return RedirectResponse(url=f"/roadmaps/{rm.id}?run={run.id}", status_code=303)


@router.post("/courses/{course_id}/generate")
def start_course_modules_generation(
    course_id: uuid.UUID,
    request: Request,
    overwrite: str | None = Form(None),  # checkbox sends "1" usually
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.user_id == user.id)
        .first()
    )
    if not course:
        return RedirectResponse(url="/courses?error=not_found", status_code=303)

    run = GenerationRun(
        user_id=user.id,
        roadmap_id=course.roadmap_id,
        course_id=course.id,
        status="queued",
        progress=0,
        message="Queued",
    )
    db.add(run)
    db.flush()

    task_id = enqueue_job(
        job_type="generate_course_modules",
        run_id=str(run.id),
        course_id=str(course.id),
        overwrite=bool(overwrite),
    )
    run.celery_task_id = task_id  # legacy field

    db.commit()

    return RedirectResponse(url=f"/courses/{course.id}?run={run.id}", status_code=303)


def compress_response(data: dict) -> JSONResponse:
    """Compress JSON response with gzip for better performance."""
    import json
    from fastapi import Response
    
    json_data = json.dumps(data)
    compressed = gzip.compress(json_data.encode('utf-8'))
    
    return Response(
        content=compressed,
        media_type="application/json",
        headers={"Content-Encoding": "gzip"}
    )


@router.get("/runs/{run_id}")
def get_run_status(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    run = (
        db.query(GenerationRun)
        .filter(GenerationRun.id == run_id, GenerationRun.user_id == user.id)
        .first()
    )
    if not run:
        return JSONResponse({"error": "not_found"}, status_code=404)

    return compress_response({
        "id": str(run.id),
        "status": run.status,
        "progress": run.progress,
        "message": run.message,
        "error": run.error,
        "course_id": str(run.course_id) if run.course_id else None,
        "result_json": run.result_json if run.status == "succeeded" else None,
    })


@router.get("/runs")
def get_user_active_runs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get all active (non-completed) generation runs for the current user."""
    runs = (
        db.query(GenerationRun)
        .filter(
            GenerationRun.user_id == user.id,
            GenerationRun.status.in_(["queued", "processing"])
        )
        .order_by(GenerationRun.created_at.desc())
        .all()
    )
    
    return compress_response([
        {
            "id": str(run.id),
            "status": run.status,
            "progress": run.progress,
            "message": run.message,
            "course_id": str(run.course_id) if run.course_id else None,
            "roadmap_id": str(run.roadmap_id) if run.roadmap_id else None,
            "created_at": run.created_at.isoformat() if run.created_at else None,
        }
        for run in runs
    ])


@router.get("/queue/status")
def queue_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get current queue status (pending and processing jobs)."""
    status = get_queue_status()

    # Enrich with run details from DB
    for task_list in [status.get("pending", []), status.get("processing", [])]:
        for task in task_list:
            run_id = task.get("run_id")
            if run_id:
                run = db.query(GenerationRun).filter(
                    GenerationRun.id == uuid.UUID(str(run_id)),
                    GenerationRun.user_id == user.id
                ).first()
                if run:
                    task["run_status"] = run.status
                    task["progress"] = run.progress
                    task["message"] = run.message

    return compress_response(status)


@router.post("/queue/clear-pending")
def clear_pending(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Clear all pending jobs from the queue."""
    count = clear_pending_queue()
    return compress_response({"ok": True, "cleared": count})


@router.post("/queue/clear-processing")
def clear_processing(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Clear all processing jobs and mark them as failed."""
    count = clear_processing_queue()
    return compress_response({
        "ok": True,
        "cleared": count
    })


@router.post("/queue/clear-all")
def clear_all(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Clear both pending and processing queues."""
    pending_count = clear_pending_queue()
    processing_count = clear_processing_queue()
    return compress_response({
        "ok": True,
        "cleared_pending": pending_count,
        "cleared_processing": processing_count,
        "total": pending_count + processing_count
    })


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cancel a specific run by removing it from queue and marking as failed."""
    # Verify user owns this run
    run = db.query(GenerationRun).filter(
        GenerationRun.id == run_id,
        GenerationRun.user_id == user.id
    ).first()
    if not run:
        return compress_response({"error": "not_found"}, status_code=404)

    result = cancel_job_by_run_id(str(run_id))
    return compress_response(result)
