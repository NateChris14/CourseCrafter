# app/agents/workflow.py
import re
from pydantic import ValidationError

from app.agents.schemas import RoadmapOutline
from app.agents.llm.ollama import OllamaOpenAIClient
from app.settings import settings


SYSTEM_PLANNER = """You are a curriculum planner.

You must return ONLY valid JSON (no markdown, no code fences, no commentary).
The JSON must match the given schema exactly.
"""


def build_planner_prompt(field: str, level: str, weekly_hours: int, duration_weeks: int) -> str:
    return f"""
Create a {duration_weeks}-week learning roadmap for: {field}
Learner level: {level}
Time budget: {weekly_hours} hours/week

Output must be STRICT JSON matching this schema:
{{
  "weeks": [
    {{"week": 1, "title": "string", "outcomes": ["string", "string"]}}
  ]
}}

Rules:
- "weeks" must contain exactly {duration_weeks} items.
- Each week.week must be 1..{duration_weeks} with no duplicates, in increasing order.
- outcomes: 2-6 items per week, each short and specific.
- Titles must be concise.
""".strip()


def _extract_first_json_object(text: str) -> str | None:
    """
    Extract the first top-level JSON object from a string.
    This handles cases where the model wraps JSON with extra text.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start:end + 1].strip()

    # quick sanity: must start/end like an object
    if not (candidate.startswith("{") and candidate.endswith("}")):
        return None
    return candidate


def _validate_outline(outline: RoadmapOutline, duration_weeks: int) -> None:
    if len(outline.weeks) != duration_weeks:
        raise ValueError(f"Expected {duration_weeks} weeks, got {len(outline.weeks)}")

    # Enforce week numbers 1..duration_weeks, strictly increasing, no duplicates
    nums = [w.week for w in outline.weeks]
    if nums != list(range(1, duration_weeks + 1)):
        raise ValueError(f"Week numbers must be exactly 1..{duration_weeks} in order, got {nums}")


def generate_roadmap_outline(field: str, level: str, weekly_hours: int, duration_weeks: int) -> RoadmapOutline:
    llm = OllamaOpenAIClient(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
    )

    user_prompt = build_planner_prompt(field, level, weekly_hours, duration_weeks)

    last_err: Exception | None = None

    for attempt in range(1, 4):
        text = llm.generate_text(system=SYSTEM_PLANNER, user=user_prompt, temperature=0.2)

        # 1) Try strict JSON validation
        try:
            outline = RoadmapOutline.model_validate_json(text)
            _validate_outline(outline, duration_weeks)
            return outline
        except (ValidationError, ValueError) as e:
            last_err = e

        # 2) Try extracting embedded JSON object
        extracted = _extract_first_json_object(text)
        if extracted:
            try:
                outline = RoadmapOutline.model_validate_json(extracted)
                _validate_outline(outline, duration_weeks)
                return outline
            except (ValidationError, ValueError) as e:
                last_err = e

        # 3) Repair instruction and retry
        user_prompt = (
            user_prompt
            + "\n\nYour previous response was invalid."
            + "\nReturn ONLY JSON. No markdown. No extra keys."
            + f"\nMake weeks exactly {duration_weeks} items with week numbers 1..{duration_weeks}."
        )

    raise RuntimeError(f"Planner output did not validate after retries. Last error: {last_err}")

