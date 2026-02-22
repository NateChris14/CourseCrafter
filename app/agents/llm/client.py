from app.settings import settings
from app.agents.llm.ollama import OllamaOpenAIClient
from app.agents.llm.groq import GroqOpenAIClient

def get_llm_client():
    if settings.LLM_PROVIDER == "groq":
        return GroqOpenAIClient(
            api_key=os.getenv("GROQ_API_KEY"),
            base_url=settings.GROQ_BASE_URL,
            model=settings.GROQ_MODEL,
        )

    return OllamaOpenAIClient(
        base_url = settings.ollama_base_url,
        model = settings.ollama_model,
    )