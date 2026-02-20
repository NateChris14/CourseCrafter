import httpx
from app.settings import settings
from app.agents.llm.base import LLMClient

class OllamaOpenAIClient(LLMClient):
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate_text(self, * , system: str, user: str, temperature: float = 0.2) -> str:
        # Ollama OpenAI-compatible endpoint
        # POST {base_url}/chat/completions with OpenAI message format

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature
        }

        headers = {
            "Content-Type": "application/json",
            #OpenAI-compatible clients require an api key field; Ollama ignores it
            "Authorization": "Bearer ollama",
        }

        with httpx.Client(timeout=120) as client:
            r = client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        
        return data["choices"][0]["message"]["content"]

