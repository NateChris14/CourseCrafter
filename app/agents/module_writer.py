from app.agents.llm.client import get_llm_client
from app.logger import GLOBAL_LOGGER as logger
from app.exceptions.custom_exception import DocumentPortalException
from app.settings import settings

# Import LangSmith for tracing
try:
    from langsmith import traceable
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    logger.warning("[module_writer] LangSmith not available - tracing disabled")

SYSTEM_MODULE_WRITER = """You are an expert course author.
Write clear, structured Markdown only.
No JSON. No code fences unless showing actual code examples.
Output must contain exactly these H2 headings in order:
## Overview
## Key concepts
## Worked example
## Practice exercises
## Common mistakes
## Suggested resources
## Media suggestions
No other top-level headings (# or ##) allowed.

In the "Media suggestions" section, suggest 2-3 relevant images and 1-2 videos that would enhance understanding.
Use this format ONLY:
- Image: [brief description] - search keywords: [relevant search terms]
- Video: [video title] - search keywords: [topic keywords]

IMPORTANT: Never include URLs or YouTube links. Only provide search keywords that users can search for.
"""

def build_module_prompt(field: str, level: str, week: int, title: str,
outcomes: list[str]) -> str:
    """Build the module writing prompt for LLM content generation.
    
    Args:
        field: Subject area/field of study
        level: Learner level
        week: Week number
        title: Module title
        outcomes: List of learning outcomes
        
    Returns:
        Formatted prompt string for the LLM
    """
    
    outcomes_text = "\n".join([f"- {o}" for o in outcomes])
    
    # Determine if field requires Python code in worked example
    programming_keywords = ["python", "ml", "machine learning", "data", "pandas", "numpy", "deep learning", "nlp"]
    is_programming_field = any(keyword in field.lower() for keyword in programming_keywords)
    
    worked_example_guidance = "Worked example (with Python code)" if is_programming_field else "Worked example (code OR step-by-step walkthrough)"
    
    return f"""
Course topic: {field}
Learner level: {level}

Week {week} title: {title}
Outcomes:
{outcomes_text}

Write a markdown lesson with these EXACT headings (use H2 ## format):
## Overview
## Key concepts
## {worked_example_guidance}
## Practice exercises (exactly 3 numbered items)
## Common mistakes
## Suggested resources
## Media suggestions

Requirements:
- Output must be Markdown only
- Use exactly these 7 headings in this order
- No additional top-level headings
- Practice exercises section must have exactly 3 numbered items
- Media suggestions must include 2-3 image suggestions and 1-2 video suggestions
- Keep content practical and concise
""".strip()

def validate_module_markdown(md: str) -> None:
    """Validate markdown structure and content requirements."""
    required_headings = [
        "## Overview",
        "## Key concepts", 
        "## Worked example",
        "## Practice exercises",
        "## Common mistakes",
        "## Suggested resources",
        "## Media suggestions"
    ]
    
    lines = md.split('\n')
    found_headings = []
    practice_exercises_content = []
    in_practice_section = False
    
    for line in lines:
        line = line.strip()
        if line.startswith('## '):
            heading = line.lower()  # Normalize to lowercase for comparison
            found_headings.append(heading)
            in_practice_section = (heading == "## practice exercises")
        elif in_practice_section and line and (line[0].isdigit() or line.startswith('-')):
            practice_exercises_content.append(line)
    
    # Normalize required headings to lowercase for comparison
    normalized_required = [h.lower() for h in required_headings]
    
    # Check all required headings exist (case-insensitive and flexible matching)
    missing = []
    for required in normalized_required:
        # Check if any found heading contains the required heading as a base
        found = any(required in found_heading for found_heading in found_headings)
        if not found:
            # Show original case for missing headings
            original_missing = [h for h in required_headings if h.lower() == required]
            missing.extend(original_missing)
    
    # Only flag extra headings that don't match any required pattern
    extra = []
    for found_heading in found_headings:
        matches_any = any(required in found_heading for required in normalized_required)
        if not matches_any:
            extra.append(found_heading)
    
    if missing or extra:
        error_msg = "Invalid headings structure"
        if missing:
            error_msg += f". Missing: {set(missing)}"
        if extra:
            error_msg += f". Extra: {extra}"
        raise ValueError(error_msg)
    
    # Check practice exercises has exactly 3 numbered items
    numbered_items = [line for line in practice_exercises_content if line and line[0].isdigit()]
    if len(numbered_items) != 3:
        raise ValueError(f"Practice exercises must have exactly 3 numbered items, found {len(numbered_items)}")

# Apply LangSmith tracing if available and enabled
def _trace_module_writer(func):
    if (LANGSMITH_AVAILABLE and 
        settings.LANGSMITH_TRACING and 
        settings.LANGSMITH_API_KEY):
        return traceable(func)
    return func

@_trace_module_writer
def write_module_markdown(field: str, level: str, week: int, title: str,
outcomes: list[str]) -> str:
    """Generate markdown content for a course module using LLM.
    
    Creates structured markdown with required sections and validates output.
    Includes automatic repair retry if validation fails.
    
    Args:
        field: Subject area/field of study
        level: Learner level
        week: Week number
        title: Module title
        outcomes: List of learning outcomes
        
    Returns:
        Validated markdown content string
        
    Raises:
        DocumentPortalException: If generation fails after repair retry
    """
    
    llm = get_llm_client()
    prompt = build_module_prompt(field, level, week, title, outcomes)
    
    logger.info(f"[write_module_markdown] Generating content for week {week}: {title}")
    
    try:
        # First attempt
        markdown = llm.generate_text(system=SYSTEM_MODULE_WRITER, user=prompt, temperature=0.2).strip()
        
        # Validate and repair if needed
        try:
            validate_module_markdown(markdown)
            logger.info(f"[write_module_markdown] Week {week} generated successfully")
            return markdown
        except ValueError as e:
            logger.warning(f"[write_module_markdown] Week {week} validation failed, attempting repair: {str(e)}")
            # One repair retry
            repair_prompt = f"""
{prompt}

PREVIOUS ATTEMPT FAILED:
Error: {e}

Invalid markdown:
{markdown}

Return corrected markdown only. Fix the structure errors while preserving content quality.
""".strip()
            
            repaired_markdown = llm.generate_text(system=SYSTEM_MODULE_WRITER, user=repair_prompt, temperature=0.1).strip()
            
            # Final validation
            try:
                validate_module_markdown(repaired_markdown)
                logger.info(f"[write_module_markdown] Week {week} repaired successfully")
                return repaired_markdown
            except ValueError as final_e:
                logger.error(f"[write_module_markdown] Week {week} repair failed: {str(final_e)}")
                raise DocumentPortalException(f"Module markdown validation failed after repair for week {week}", final_e)
    except Exception as e:
        logger.error(f"[write_module_markdown] Failed to generate week {week}: {str(e)}")
        raise DocumentPortalException(f"Failed to generate module markdown for week {week}", e)