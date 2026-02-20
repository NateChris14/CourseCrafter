## Application settings configuration

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str
    redis_url: str
    session_secret: str

    session_absolute_days: int = 7
    session_idle_minutes: int = 60

settings = Settings()
