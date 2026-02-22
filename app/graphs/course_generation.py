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

        pending: List[int] = []
        for m in modules:
            has_content = bool(m.content_md and m.content_md.strip())
            if has_content and not state["overwrite"]:
                continue
            pending.append(int(m.week))

        state["pending_weeks"] = pending
        state["done_weeks"] = state.get("done_weeks") or []
        state["total"] = len(modules)

        update_run(state["run_id"], status="running", progress=1, message="LangGraph: initialized", started=True)
        return state
    finally:
        db.close()


def write_one_week(state: GenState, config: RunnableConfig) -> GenState:
    if not state["pending_weeks"]:
        return state

    week = state["pending_weeks"][0]
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
        update_run(
            state["run_id"],
            progress=int(5 + (done / total_to_do) * 90),
            message=f"Writing week {week}/{state['total']}",
        )

        md = write_module_markdown(
            field=rm.field,
            level=rm.level,
            week=int(module.week),
            title=module.title,
            outcomes=outcomes,
        )
        module.content_md = md
        db.commit()

        state["done_weeks"] = (state.get("done_weeks") or []) + [week]
        state["pending_weeks"] = state["pending_weeks"][1:]
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
    return "write_one_week" if state.get("pending_weeks") else "finish"


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
