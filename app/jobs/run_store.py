import uuid
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.db.models.generation_run import GenerationRun


def _to_uuid(v: str | uuid.UUID | None) -> uuid.UUID | None:
    """Convert string or UUID to UUID object, handling None values."""
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return v
    return uuid.UUID(str(v))


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
    """Update generation run status and metadata.
    
    Args:
        run_id: Generation run ID
        status: New status value
        progress: Progress percentage (0-100)
        message: Status message
        error: Error message if failed
        result_json: JSON result data
        started: Set started_at timestamp if True
        finished: Set finished_at timestamp if True
    """
    run_uuid = _to_uuid(run_id)
    if run_uuid is None:
        return

    db = SessionLocal()
    try:
        run = db.query(GenerationRun).filter(GenerationRun.id == run_uuid).first()
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
        if started and run.started_at is None:
            run.started_at = now
        if finished:
            run.finished_at = now

        db.commit()
    finally:
        db.close()
