# app/agents/workflow.py
import re
from pydantic import ValidationError

from app.agents.schemas import RoadmapOutline
from app.agents.llm.client import get_llm_client
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
    Extract the first complete top-level JSON object using brace counting.
    Returns the first balanced { ... } substring, or None if not found.
    """
    start = text.find("{")
    if start == -1:
        return None
    
    brace_count = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            brace_count += 1
        elif text[i] == "}":
            brace_count -= 1
            if brace_count == 0:
                return text[start:i + 1]
    
    return None


def _validate_outline(outline: RoadmapOutline, duration_weeks: int) -> None:
    if len(outline.weeks) != duration_weeks:
        raise ValueError(f"Expected {duration_weeks} weeks, got {len(outline.weeks)}")

    # Enforce week numbers 1..duration_weeks, strictly increasing, no duplicates
    nums = [w.week for w in outline.weeks]
    if nums != list(range(1, duration_weeks + 1)):
        raise ValueError(f"Week numbers must be exactly 1..{duration_weeks} in order, got {nums}")
    
    # Additional sanity checks
    for week in outline.weeks:
        if not week.title or not week.title.strip():
            raise ValueError(f"Week {week.week} title is empty")
        if len(week.outcomes) < 2 or len(week.outcomes) > 6:
            raise ValueError(f"Week {week.week} must have 2-6 outcomes, got {len(week.outcomes)}")
        for outcome in week.outcomes:
            if not outcome or not outcome.strip():
                raise ValueError(f"Week {week.week} has empty outcome")


def generate_roadmap_outline(field: str, level: str, weekly_hours: int, duration_weeks: int) -> RoadmapOutline:
    llm = get_llm_client()

    user_prompt = build_planner_prompt(field, level, weekly_hours, duration_weeks)

    last_err: Exception | None = None

    for attempt in range(1, 4):
        raw_text = llm.generate_text(system=SYSTEM_PLANNER, user=user_prompt, temperature=0.1)

        # 1) Try strict JSON validation
        try:
            outline = RoadmapOutline.model_validate_json(raw_text)
            _validate_outline(outline, duration_weeks)
            return outline
        except (ValidationError, ValueError) as e:
            last_err = e

        # 2) Try extracting embedded JSON object
        extracted_json = _extract_first_json_object(raw_text)
        if extracted_json:
            try:
                outline = RoadmapOutline.model_validate_json(extracted_json)
                _validate_outline(outline, duration_weeks)
                return outline
            except (ValidationError, ValueError) as e:
                last_err = e

        # 3) Build repair prompt with detailed error info
        error_text = str(last_err)
        invalid_json = extracted_json if extracted_json else raw_text
        
        user_prompt = f"""
{build_planner_prompt(field, level, weekly_hours, duration_weeks)}

PREVIOUS ATTEMPT FAILED:
Error: {error_text}

Invalid output:
{invalid_json}

Return ONLY corrected JSON, no extra keys, no markdown.
Must have exactly {duration_weeks} weeks with numbers 1..{duration_weeks}.
Each week needs 2-6 outcomes and non-empty title.
""".strip()

    raise RuntimeError(f"Planner output did not validate after retries. Last error: {last_err}")

