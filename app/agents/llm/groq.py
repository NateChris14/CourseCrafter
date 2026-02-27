from openai import OpenAI
from .base import LLMClient
from app.logger import GLOBAL_LOGGER as logger

class GroqOpenAIClient(LLMClient):
    def __init__(self, *, api_key: str, base_url: str, model: str):
        self.client = OpenAI(
            api_key=api_key, 
            base_url=base_url,
            timeout=120.0  # Set timeout to 120 seconds like Ollama
        )
        self.model = model
        logger.info(f"[GroqOpenAIClient] Initialized with model: {model}")

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