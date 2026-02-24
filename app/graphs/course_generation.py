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
from app.logger import GLOBAL_LOGGER as logger
from app.exceptions.custom_exception import DocumentPortalException


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
    logger.info(f"[load_state] Starting course generation for run_id={state['run_id']}, course_id={state['course_id']}")
    db = SessionLocal()
    try:
        run_id = _u(state["run_id"])
        course_id = _u(state["course_id"])
        overwrite = bool(state.get("overwrite", False))

        run = db.query(GenerationRun).filter(GenerationRun.id == run_id).first()
        if not run:
            logger.error(f"[load_state] Run not found: {run_id}")
            update_run(state["run_id"], status="failed", error="Run not found", finished=True)
            return state

        course = (
            db.query(Course)
            .filter(Course.id == course_id, Course.user_id == run.user_id)
            .first()
        )
        if not course:
            logger.error(f"[load_state] Course not found: {course_id}")
            update_run(state["run_id"], status="failed", error="course not found", finished=True)
            return state

        modules = (
            db.query(CourseModule)
            .filter(CourseModule.course_id == course.id)
            .order_by(CourseModule.week.asc())
            .all()
        )
        if not modules:
            logger.error(f"[load_state] No modules found for course: {course_id}")
            update_run(state["run_id"], status="failed", error="no modules found", finished=True)
            return state

        logger.info(f"[load_state] Found {len(modules)} modules for course {course_id}")

        all_weeks = [int(m.week) for m in modules]
        db_done = {int(m.week) for m in modules if m.content_md and m.content_md.strip()}
        logger.info(f"[load_state] Weeks with content: {db_done}")

        if overwrite:
            # Force rewrite everything.
            done_weeks: List[int] = []
            pending = all_weeks
            logger.info(f"[load_state] OVERWRITE MODE - resetting all {len(pending)} weeks")
        else:
            # Resume: trust checkpoint state if present, but never rewrite weeks that already have content.
            checkpoint_done = state.get("done_weeks") or []
            done_weeks = [w for w in checkpoint_done if w in all_weeks]
            pending = [w for w in all_weeks if (w not in done_weeks) and (w not in db_done)]
            logger.info(f"[load_state] RESUME MODE - checkpoint_done={checkpoint_done}, done_weeks={done_weeks}, pending={pending}")

        state["pending_weeks"] = pending
        state["done_weeks"] = done_weeks
        state["total"] = len(modules)

        logger.info(f"[load_state] Final state: {len(pending)} pending, {len(done_weeks)} done, total={len(modules)}")
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
    logger.debug(f"[_parse_media_suggestions] Media section found: {media_section is not None}")
    
    if not media_section:
        logger.debug("[_parse_media_suggestions] No media suggestions section found")
        return {"images": [], "videos": []}

    content = media_section.group(1)
    logger.debug(f"[_parse_media_suggestions] Media content: {content[:200]}...")

    # Parse image suggestions
    for match in re.finditer(r'-?\s*Image:\s*(.+?)\s*-\s*search\s*keywords?:\s*(.+?)(?:\n|$)', content, re.IGNORECASE):
        images.append({
            "description": match.group(1).strip(),
            "search_keywords": match.group(2).strip()
        })
        logger.debug(f"[_parse_media_suggestions] Found image: {match.group(1).strip()}")

    # Parse video suggestions (search keywords only)
    for match in re.finditer(r'-?\s*Video:\s*(.+?)\s*-\s*search\s*keywords?:\s*(.+?)(?:\n|$)', content, re.IGNORECASE):
        videos.append({
            "title": match.group(1).strip(),
            "search_keywords": match.group(2).strip()
        })
        logger.debug(f"[_parse_media_suggestions] Found video: {match.group(1).strip()}")

    logger.debug(f"[_parse_media_suggestions] Total parsed: {len(images)} images, {len(videos)} videos")
    return {"images": images, "videos": videos}


def write_one_week(state: GenState, config: RunnableConfig) -> GenState:
    logger.info(f"[write_one_week] Starting week generation. Pending weeks: {state.get('pending_weeks')}")
    if not state.get("pending_weeks"):
        logger.info("[write_one_week] No pending weeks, returning")
        return state

    week = int(state["pending_weeks"][0])
    logger.info(f"[write_one_week] Processing week {week}")

    db = SessionLocal()
    try:
        run_id = _u(state["run_id"])
        course_id = _u(state["course_id"])

        run = db.query(GenerationRun).filter(GenerationRun.id == run_id).first()
        course = db.query(Course).filter(Course.id == course_id).first()
        if not run or not course:
            logger.error(f"[write_one_week] Missing run or course for week {week}")
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
            logger.error(f"[write_one_week] Missing roadmap/module for week {week}")
            update_run(state["run_id"], status="failed", error=f"missing roadmap/module for week {week}", finished=True)
            state["pending_weeks"] = []
            return state

        outcomes = json.loads(module.outcomes_json) if module.outcomes_json else []
        logger.info(f"[write_one_week] Week {week} has {len(outcomes)} outcomes")

        # Calculate progress based on current week number to ensure it mirrors the week
        current_week = week
        total_weeks = state.get('total', 1)
        # Map week number to progress percentage (week 1 = ~10%, week 6 = ~60%, etc.)
        progress_percentage = int((current_week / total_weeks) * 85) + 5  # 5-90% range, leaving room for finalization
        update_run(
            state["run_id"],
            progress=progress_percentage,
            message=f"Writing week {week}/{state.get('total', 0)}",
        )

        logger.info(f"[write_one_week] Calling module writer for week {week}")
        md = write_module_markdown(
            field=rm.field,
            level=rm.level,
            week=int(module.week),
            title=module.title,
            outcomes=outcomes,
        )
        logger.info(f"[write_one_week] Generated markdown for week {week}, length: {len(md)} chars")

        # Parse and save media suggestions
        media_suggestions = _parse_media_suggestions(md)
        logger.info(f"[write_one_week] Week {week} media suggestions: {len(media_suggestions['images'])} images, {len(media_suggestions['videos'])} videos")
        if media_suggestions["images"] or media_suggestions["videos"]:
            module.media_suggestions_json = json.dumps(media_suggestions)
            logger.info(f"[write_one_week] Week {week} saved media suggestions to database")
        else:
            module.media_suggestions_json = None
            logger.info(f"[write_one_week] Week {week} no media suggestions found")
        module.content_md = md
        db.commit()
        logger.info(f"[write_one_week] Week {week} content saved to database")

        state["done_weeks"] = (state.get("done_weeks") or []) + [week]
        state["pending_weeks"] = state["pending_weeks"][1:]
        logger.info(f"[write_one_week] Week {week} completed. Remaining: {state['pending_weeks']}")
        return state
    except Exception as e:
        logger.error(f"[write_one_week] Error processing week {week}: {str(e)}")
        raise DocumentPortalException(f"Failed to process week {week}", e)
    finally:
        db.close()


def finish(state: GenState, config: RunnableConfig) -> GenState:
    weeks_written = len(state.get('done_weeks') or [])
    logger.info(f"[finish] Course generation completed. Total weeks written: {weeks_written}")
    update_run(
        state["run_id"],
        status="succeeded",
        progress=100,
        message=f"Done! (weeks_written={weeks_written})",
        finished=True,
    )
    logger.info(f"[finish] Generation run {state['run_id']} marked as succeeded")
    return state


def should_continue(state: GenState) -> str:
    has_pending = bool(state.get("pending_weeks"))
    result = "write_one_week" if has_pending else "finish"
    logger.debug(f"[should_continue] pending_weeks={state.get('pending_weeks')} -> {result}")
    return result


def build_course_generation_graph_builder() -> StateGraph:
    logger.info("[build_course_generation_graph_builder] Building course generation graph")
    builder = StateGraph(GenState)
    builder.add_node("load_state", load_state)
    builder.add_node("write_one_week", write_one_week)
    builder.add_node("finish", finish)

    builder.add_edge(START, "load_state")
    builder.add_conditional_edges("load_state", should_continue)
    builder.add_conditional_edges("write_one_week", should_continue)
    builder.add_edge("finish", END)

    logger.info("[build_course_generation_graph_builder] Graph built with nodes: load_state, write_one_week, finish")
    return builder
