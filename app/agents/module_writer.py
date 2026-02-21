from app.agents.llm.ollama import OllamaOpenAIClient
from app.settings import settings

SYSTEM_MODULE_WRITER = """You are an expert course author.
Write clear, structured Markdown.
No JSON. No code fences unless you are showing code examples.
"""

def build_module_prompt(field: str, level: str, week: int, title: str,
outcomes: list[str]) -> str:
    
    outcomes_text = "\n".join([f"- {o}" for o in outcomes])
    return f"""
    Course topic: {field}
    Learner level: {level}

    Week {week} title: {title}
    Outcomes:
    {outcomes_text}

    Write a markdown lesson with these sections (use these exact headings):
    ## Overview
    ## Key concepts
    ## Worked example (with Python code)
    ## Practice exercises (3)
    ## Common mistakes
    ## Suggested resources

    Keep it practical and concise.
    """.strip()

def write_module_markdown(field: str, level: str, week: int, title: str,
outcomes: list[str]) -> str:
    
    llm = OllamaOpenAIClient(base_url=settings.ollama_base_url,
    model=settings.ollama_model)
    prompt = build_module_prompt(field, level, week, title, outcomes)
    return llm.generate_text(system=SYSTEM_MODULE_WRITER, user=prompt,
    temperature=0.3).strip()