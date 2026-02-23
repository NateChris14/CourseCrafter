from app.agents.llm.client import get_llm_client

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

In the "Media suggestions" section, suggest 2-3 relevant images and 1-2 YouTube videos that would enhance understanding.
Use this format:
- Image: [brief description] - search keywords: [relevant search terms]
- Video: [video title] - search: [topic keywords] OR YouTube URL if known
"""

def build_module_prompt(field: str, level: str, week: int, title: str,
outcomes: list[str]) -> str:
    
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
    
    # Check all required headings exist (case-insensitive)
    missing = set(normalized_required) - set(found_headings)
    extra = set(found_headings) - set(normalized_required)
    
    if missing or extra:
        error_msg = "Invalid headings structure"
        if missing:
            # Show original case for missing headings
            original_missing = [h for h in required_headings if h.lower() in missing]
            error_msg += f". Missing: {set(original_missing)}"
        if extra:
            error_msg += f". Extra: {extra}"
        raise ValueError(error_msg)
    
    # Check practice exercises has exactly 3 numbered items
    numbered_items = [line for line in practice_exercises_content if line and line[0].isdigit()]
    if len(numbered_items) != 3:
        raise ValueError(f"Practice exercises must have exactly 3 numbered items, found {len(numbered_items)}")

def write_module_markdown(field: str, level: str, week: int, title: str,
outcomes: list[str]) -> str:
    
    llm = get_llm_client()
    prompt = build_module_prompt(field, level, week, title, outcomes)
    
    # First attempt
    markdown = llm.generate_text(system=SYSTEM_MODULE_WRITER, user=prompt, temperature=0.2).strip()
    
    # Validate and repair if needed
    try:
        validate_module_markdown(markdown)
        return markdown
    except ValueError as e:
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
            return repaired_markdown
        except ValueError as final_e:
            raise RuntimeError(f"Module markdown validation failed after repair: {final_e}")