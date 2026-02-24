## Routes for the application
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.models.user import User
from app.db.models.course import Course
from app.db.models.roadmap import Roadmap
from app.auth.deps import get_current_user
from app.deps import get_db

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Get user's recent courses (limit to 5)
    courses = (
        db.query(Course)
        .filter(Course.user_id == user.id)
        .order_by(desc(Course.updated_at))
        .limit(5)
        .all()
    )
    
    # Get user's recent roadmaps (limit to 5)
    roadmaps = (
        db.query(Roadmap)
        .filter(Roadmap.user_id == user.id)
        .order_by(desc(Roadmap.created_at))
        .limit(5)
        .all()
    )
    
    return templates.TemplateResponse(
        "dashboard.html", 
        {
            "request": request, 
            "user": user,
            "courses": courses,
            "roadmaps": roadmaps
        }
    )