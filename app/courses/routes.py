import json
import stat
import uuid
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.deps import get_db
from app.auth.deps import get_current_user
from app.db.models.user import User
from app.db.models.course import Course
from app.db.models.course_module import CourseModule

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/courses")

@router.get("/{course_id}", response_class=HTMLResponse)
def view_course(course_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
user: User = Depends(get_current_user)):
    course = db.query(Course).filter(Course.id == course_id, Course.user_id == user.id).first()
    if not course:
        return RedirectResponse(url="/dashboard?error=course_not_found",
        status_code=303)
    
    modules = (
        db.query(CourseModule)
        .filter(CourseModule.course_id == course.id)
        .order_by(CourseModule.week.asc())
        .all()
    )

    # decode outcomes_json for template
    module_views = []
    for m in modules:
        module_views.append({
            "week": m.week,
            "title": m.title,
            "outcomes": json.loads(m.outcomes_json),
            "content_md": m.content_md,

        })

    return templates.TemplateResponse(
        "course_view.html",
        {"request": request, "user": user, "course": course, "modules": module_views},
        
    )
