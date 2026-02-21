# app/courses/routes.py
import json
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc

from markdown_it import MarkdownIt
from markupsafe import Markup

from app.deps import get_db
from app.auth.deps import get_current_user
from app.db.models.user import User
from app.db.models.course import Course
from app.db.models.course_module import CourseModule
from app.db.models.generation_run import GenerationRun
from app.jobs.tasks import enqueue_job

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/courses")

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def list_courses(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):

    courses = (
        db.query(Course)
        .filter(Course.user_id == user.id)
        .order_by(desc(Course.updated_at)) # newest first
        .all()
    )

    return templates.TemplateResponse(
        "courses_list.html",
        {
            "request": request,
            "user": user,
            "courses": courses,
        },
    )


@router.get("/{course_id}", response_class=HTMLResponse)
def view_course(
    course_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.user_id == user.id)
        .first()
    )
    if not course:
        return RedirectResponse(url="/dashboard?error=course_not_found", status_code=303)

    modules = (
        db.query(CourseModule)
        .filter(CourseModule.course_id == course.id)
        .order_by(CourseModule.week.asc())
        .all()
    )

    md = MarkdownIt("js-default")  # disables raw HTML parsing vs commonmark [web:518]

    module_views = []
    for m in modules:
        content_html = None
        if m.content_md and m.content_md.strip():
            content_html = Markup(md.render(m.content_md))  # mark as safe for Jinja [web:722]

        module_views.append(
            {
                "week": m.week,
                "title": m.title,
                "outcomes": json.loads(m.outcomes_json),
                "content_md": m.content_md,
                "content_html": content_html,
            }
        )

    run_id = request.query_params.get("run")

    return templates.TemplateResponse(
        "course_view.html",
        {
            "request": request,
            "user": user,
            "course": course,
            "modules": module_views,
            "run_id": run_id,
        },
    )


@router.post("/{course_id}/generate")
def generate_course_modules(
    course_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.user_id == user.id)
        .first()
    )
    if not course:
        return RedirectResponse(url="/dashboard?error=course_not_found", status_code=303)

    run = GenerationRun(
        user_id=user.id,
        roadmap_id=course.roadmap_id,
        course_id=course.id,
        status="queued",
        progress=0,
        message="Queued module writing",
    )
    db.add(run)
    db.flush()

    task_id = enqueue_job(
        job_type="generate_course_modules",
        run_id=str(run.id),
        course_id=str(course.id),
    )
    run.celery_task_id = task_id  # legacy field
    db.commit()

    return RedirectResponse(url=f"/courses/{course.id}?run={run.id}", status_code=303)

@router.post("/{course_id}/delete")
def delete_course(
    course_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    course = (
        db.query(Course)
        .filter(Course.id == course_id, Course.user_id == user.id)
        .first()
    )
    if not course:
        return RedirectResponse(url="/courses?error=course_not_found", 
        status_code=303)

    db.delete(course)
    db.commit()

    return RedirectResponse(url="/courses?deleted=1", status_code=303)