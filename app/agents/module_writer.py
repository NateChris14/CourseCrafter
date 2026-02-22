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
No other top-level headings (# or ##) allowed.
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

Requirements:
- Output must be Markdown only
- Use exactly these 6 headings in this order
- No additional top-level headings
- Practice exercises section must have exactly 3 numbered items
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
        "## Suggested resources"
    ]
    
    lines = md.split('\n')
    found_headings = []
    practice_exercises_content = []
    in_practice_section = False
    
    for line in lines:
        line = line.strip()
        if line.startswith('## '):
            heading = line
            found_headings.append(heading)
            in_practice_section = (heading == "## Practice exercises")
        elif in_practice_section and line and (line[0].isdigit() or line.startswith('-')):
            practice_exercises_content.append(line)
    
    # Check all required headings exist in order
    if found_headings != required_headings:
        missing = set(required_headings) - set(found_headings)
        extra = set(found_headings) - set(required_headings)
        error_msg = "Invalid headings structure"
        if missing:
            error_msg += f". Missing: {missing}"
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