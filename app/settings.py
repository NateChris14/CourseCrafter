# app/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://coursecrafter:coursecrafter@db:5432/coursecrafter"
    redis_url: str = "redis://redis:6379/0"
    session_secret: str = "dev-secret-key-local-only"

    session_absolute_days: int = 7
    session_idle_minutes: int = 60

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "llama3.1"

    LLM_PROVIDER: str = "groq"
    GROQ_API_KEY: str
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    @property
    def langgraph_postgres_dsn(self) -> str:
        # PostgresSaver wants a DB-API style DSN like postgresql://..., not SQLAlchemy's postgresql+psycopg://... [web:1142]
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)  # [web:1144]

settings = Settings()
