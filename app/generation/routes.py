import uuid
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth.deps import get_current_user
from app.db.models.user import User
from app.db.models.roadmap import Roadmap
from app.db.models.generation_run import GenerationRun
from app.jobs.tasks import generate_roadmap_outline

router = APIRouter()

@router.post("/roadmaps/{roadmap_id}/generate")
def start_generation(roadmap_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
user: User = Depends(get_current_user)):
    
    rm = db.query(Roadmap).filter(Roadmap.id == roadmap_id, Roadmap.user_id == 
    user.id).first()

    if not rm:
        return RedirectResponse(url="/roadmaps?error=not_found",
        status_code=303)

    run = GenerationRun(
        user_id=user.id,
        roadmap_id=rm.id,
        status="queued",
        progress=0,
        message="Queued"
    )

    db.add(run)
    db.commit()

    task = generate_roadmap_outline.delay(str(run.id))
    run.celery_task_id = task.id
    db.commit()

    return RedirectResponse(url=f"/roadmaps/{rm.id}?run={run.id}",
    status_code=303)

@router.get("/runs/{run_id}")
def get_run_status(run_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = db.query(GenerationRun).filter(GenerationRun.id == run_id, GenerationRun.user_id == user.id).first()
    if not run:
        return JSONResponse({"error": "not_found"}, status_code=404)

    return {
        "id": str(run.id),
        "status": run.status,
        "progress": run.progress,
        "message": run.message,
        "error": run.error,
        "result_json": run.result_json if run.status == "succeeded" else None,
    }