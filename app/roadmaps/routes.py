# Roadmap pages
import uuid
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth.deps import get_current_user
from app.db.models.user import User
from app.db.models.roadmap import Roadmap

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/roadmaps")

@router.get("", response_class=HTMLResponse)
def list_roadmaps(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = (
        db.query(Roadmap)
        .filter(Roadmap.user_id == user.id)
        .order_by(Roadmap.created_at.desc())
        .all()
    )
    return templates.TemplateResponse("roadmaps_list.html", {"request": request,
    "user": user, "roadmaps": items})

@router.get("/new", response_class=HTMLResponse)
def new_roadmap_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse("roadmap_new.html", {"request": request, "user": user})

@router.post("")
def create_roadmap(
    title: str = Form(...),
    field: str = Form(...),
    level: str = Form("beginner"),
    weekly_hours: int = Form(8),
    duration_weeks: int = Form(16),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    ):
    
    rm = Roadmap(
        user_id=user.id,
        title=title.strip(),
        field=field.strip(),
        level=level.strip(),
        weekly_hours=weekly_hours,
        duration_weeks=duration_weeks,
    )
    db.add(rm)
    db.commit()
    return RedirectResponse(url=f"/roadmaps/{rm.id}", status_code=303)

@router.get("/{roadmap_id}", response_class=HTMLResponse)
def roadmap_detail(roadmap_id: uuid.UUID, request: Request, db: Session = 
Depends(get_db), user: User = Depends(get_current_user)):
    rm = db.query(Roadmap).filter(Roadmap.id == roadmap_id, 
    Roadmap.user_id == user.id).first()
    if not rm:
        return RedirectResponse(url="/roadmaps?error=not_found",
        status_code=303)
    return templates.TemplateResponse("roadmap_detail.html",
    {"request": request, "user": user, "roadmap": rm})