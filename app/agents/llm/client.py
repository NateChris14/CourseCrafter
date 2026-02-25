import os
from app.settings import settings
from app.agents.llm.ollama import OllamaOpenAIClient
from app.agents.llm.groq import GroqOpenAIClient
from app.logger import GLOBAL_LOGGER as logger
from app.exceptions.custom_exception import DocumentPortalException

def get_llm_client():
    """Get configured LLM client based on provider settings.
    
    Returns:
        LLM client instance (Groq or Ollama)
        
    Raises:
        DocumentPortalException: If client initialization fails
    """
    try:
        if settings.LLM_PROVIDER == "groq":
            logger.debug("[get_llm_client] Using Groq provider")
            return GroqOpenAIClient(
                api_key=os.getenv("GROQ_API_KEY"),
                base_url=settings.GROQ_BASE_URL,
                model=settings.GROQ_MODEL,
            )
        logger.debug("[get_llm_client] Using Ollama provider")
        return OllamaOpenAIClient(
            base_url = settings.ollama_base_url,
            model = settings.ollama_model,
        )
    except Exception as e:
        logger.error(f"[get_llm_client] Failed to initialize LLM client: {str(e)}")
        raise DocumentPortalException("Failed to initialize LLM client", e)