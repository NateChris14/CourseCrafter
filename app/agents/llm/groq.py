from openai import OpenAI
from .base import LLMClient
from app.logger import GLOBAL_LOGGER as logger
from app.settings import settings

# Import LangSmith for tracing
try:
    from langsmith.wrappers import wrap_openai
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    logger.warning("[GroqOpenAIClient] LangSmith not available - tracing disabled")

class GroqOpenAIClient(LLMClient):
    def __init__(self, *, api_key: str, base_url: str, model: str):
        client = OpenAI(
            api_key=api_key, 
            base_url=base_url,
            timeout=120.0  # Set timeout to 120 seconds like Ollama
        )
        
        # Wrap with LangSmith if tracing is enabled and available
        if (settings.LANGSMITH_TRACING and 
            LANGSMITH_AVAILABLE and 
            settings.LANGSMITH_API_KEY):
            self.client = wrap_openai(client)
            logger.info(f"[GroqOpenAIClient] Initialized with LangSmith tracing, model: {model}")
        else:
            self.client = client
            logger.info(f"[GroqOpenAIClient] Initialized without tracing, model: {model}")
            
        self.model = model

    def generate_text(self, *, system: str, user: str, temperature: float = 0.2) -> str:
        try:
            logger.debug(f"[GroqOpenAIClient] Generating text with model: {self.model}")
            resp = self.client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            result = resp.choices[0].message.content.strip()
            logger.debug(f"[GroqOpenAIClient] Generated {len(result)} characters")
            return result
        except Exception as e:
            logger.error(f"[GroqOpenAIClient] Error generating text: {str(e)}")
            raise