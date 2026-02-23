# app/graphs/course_generation.py
from __future__ import annotations

import json
import uuid
from typing import TypedDict, List

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from app.db.session import SessionLocal
from app.jobs.run_store import update_run
from app.db.models.generation_run import GenerationRun
from app.db.models.course import Course
from app.db.models.course_module import CourseModule
from app.db.models.roadmap import Roadmap
from app.agents.module_writer import write_module_markdown


class GenState(TypedDict):
    run_id: str
    course_id: str
    overwrite: bool
    pending_weeks: List[int]
    done_weeks: List[int]
    total: int


def _u(s: str) -> uuid.UUID:
    return uuid.UUID(str(s))


def load_state(state: GenState, config: RunnableConfig) -> GenState:
    db = SessionLocal()
    try:
        run_id = _u(state["run_id"])
        course_id = _u(state["course_id"])
        overwrite = bool(state.get("overwrite", False))

        run = db.query(GenerationRun).filter(GenerationRun.id == run_id).first()
        if not run:
            update_run(state["run_id"], status="failed", error="Run not found", finished=True)
            return state

        course = (
            db.query(Course)
            .filter(Course.id == course_id, Course.user_id == run.user_id)
            .first()
        )
        if not course:
            update_run(state["run_id"], status="failed", error="course not found", finished=True)
            return state

        modules = (
            db.query(CourseModule)
            .filter(CourseModule.course_id == course.id)
            .order_by(CourseModule.week.asc())
            .all()
        )
        if not modules:
            update_run(state["run_id"], status="failed", error="no modules found", finished=True)
            return state

        all_weeks = [int(m.week) for m in modules]
        db_done = {int(m.week) for m in modules if m.content_md and m.content_md.strip()}

        print(f"[DEBUG load_state] run_id={run_id} overwrite={overwrite}")
        print(f"[DEBUG load_state] all_weeks={all_weeks}")
        print(f"[DEBUG load_state] db_done={db_done}")
        print(f"[DEBUG load_state] incoming state done_weeks={state.get('done_weeks')}")
        print(f"[DEBUG load_state] incoming state pending_weeks={state.get('pending_weeks')}")

        if overwrite:
            # Force rewrite everything.
            done_weeks: List[int] = []
            pending = all_weeks
            print(f"[DEBUG load_state] OVERWRITE MODE - resetting all weeks")
        else:
            # Resume: trust checkpoint state if present, but never rewrite weeks that already have content.
            checkpoint_done = state.get("done_weeks") or []
            done_weeks = [w for w in checkpoint_done if w in all_weeks]
            pending = [w for w in all_weeks if (w not in done_weeks) and (w not in db_done)]
            print(f"[DEBUG load_state] RESUME MODE - checkpoint_done={checkpoint_done}")
            print(f"[DEBUG load_state] RESUME MODE - computed done_weeks={done_weeks}")
            print(f"[DEBUG load_state] RESUME MODE - computed pending={pending}")

        state["pending_weeks"] = pending
        state["done_weeks"] = done_weeks
        state["total"] = len(modules)

        print(f"[DEBUG load_state] FINAL state done_weeks={done_weeks} pending_weeks={pending}")

        update_run(state["run_id"], status="running", progress=1, message="LangGraph: initialized", started=True)
        return state
    finally:
        db.close()


def _parse_media_suggestions(md: str) -> dict:
    """Parse media suggestions from markdown content."""
    import re
    images = []
    videos = []

    # Find Media suggestions section
    media_section = re.search(r'##\s*Media\s+suggestions(.*?)($|##)', md, re.DOTALL | re.IGNORECASE)
    if not media_section:
        return {"images": [], "videos": []}

    content = media_section.group(1)

    # Parse image suggestions
    for match in re.finditer(r'-?\s*Image:\s*(.+?)\s*-\s*search\s*keywords?:\s*(.+?)(?:\n|$)', content, re.IGNORECASE):
        images.append({
            "description": match.group(1).strip(),
            "search_keywords": match.group(2).strip()
        })

    # Parse video suggestions
    for match in re.finditer(r'-?\s*Video:\s*(.+?)\s*-\s*(?:search:\s*(.+?)|youtube:\s*(https?://\S+))(?:\n|$)', content, re.IGNORECASE):
        video = {"title": match.group(1).strip()}
        if match.group(2):
            video["search_keywords"] = match.group(2).strip()
        if match.group(3):
            video["youtube_url"] = match.group(3).strip()
        videos.append(video)

    return {"images": images, "videos": videos}


def write_one_week(state: GenState, config: RunnableConfig) -> GenState:
    print(f"[DEBUG write_one_week] START done_weeks={state.get('done_weeks')} pending_weeks={state.get('pending_weeks')}")
    if not state.get("pending_weeks"):
        print(f"[DEBUG write_one_week] No pending weeks, returning")
        return state

    week = int(state["pending_weeks"][0])
    print(f"[DEBUG write_one_week] Processing week={week}")

    db = SessionLocal()
    try:
        run_id = _u(state["run_id"])
        course_id = _u(state["course_id"])

        run = db.query(GenerationRun).filter(GenerationRun.id == run_id).first()
        course = db.query(Course).filter(Course.id == course_id).first()
        if not run or not course:
            update_run(state["run_id"], status="failed", error="run/course missing during generation", finished=True)
            state["pending_weeks"] = []
            return state

        rm = db.query(Roadmap).filter(Roadmap.id == course.roadmap_id).first()
        module = (
            db.query(CourseModule)
            .filter(CourseModule.course_id == course.id, CourseModule.week == week)
            .first()
        )
        if not rm or not module:
            update_run(state["run_id"], status="failed", error=f"missing roadmap/module for week {week}", finished=True)
            state["pending_weeks"] = []
            return state

        outcomes = json.loads(module.outcomes_json) if module.outcomes_json else []

        done = len(state.get("done_weeks") or [])
        total_to_do = max(done + len(state["pending_weeks"]), 1)
        current_progress = int(5 + (done / total_to_do) * 90)

        # Update progress before LLM call (shows activity)
        update_run(
            state["run_id"],
            progress=current_progress,
            message=f"Generating content for week {week} (this may take 30-60s)...",
        )
        print(f"[DEBUG write_one_week] Calling LLM for week={week}, progress={current_progress}%")

        md = write_module_markdown(
            field=rm.field,
            level=rm.level,
            week=int(module.week),
            title=module.title,
            outcomes=outcomes,
        )

        # Parse and save media suggestions
        media_suggestions = _parse_media_suggestions(md)
        module.media_suggestions_json = json.dumps(media_suggestions) if media_suggestions["images"] or media_suggestions["videos"] else None
        module.content_md = md
        db.commit()

        print(f"[DEBUG write_one_week] Saved media suggestions: {len(media_suggestions['images'])} images, {len(media_suggestions['videos'])} videos")

        state["done_weeks"] = (state.get("done_weeks") or []) + [week]
        state["pending_weeks"] = state["pending_weeks"][1:]
        print(f"[DEBUG write_one_week] END done_weeks={state.get('done_weeks')} pending_weeks={state.get('pending_weeks')}")
        return state
    finally:
        db.close()


def finish(state: GenState, config: RunnableConfig) -> GenState:
    update_run(
        state["run_id"],
        status="succeeded",
        progress=100,
        message=f"Done! (weeks_written={len(state.get('done_weeks') or [])})",
        finished=True,
    )
    return state


def should_continue(state: GenState) -> str:
    has_pending = bool(state.get("pending_weeks"))
    result = "write_one_week" if has_pending else "finish"
    print(f"[DEBUG should_continue] pending_weeks={state.get('pending_weeks')} has_pending={has_pending} -> {result}")
    return result


def build_course_generation_graph_builder() -> StateGraph:
    builder = StateGraph(GenState)
    builder.add_node("load_state", load_state)
    builder.add_node("write_one_week", write_one_week)
    builder.add_node("finish", finish)

    builder.add_edge(START, "load_state")
    builder.add_conditional_edges("load_state", should_continue)
    builder.add_conditional_edges("write_one_week", should_continue)
    builder.add_edge("finish", END)

    return builder
