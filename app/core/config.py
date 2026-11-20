from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    data_dir: Path = PROJECT_ROOT / "data"
    log_level: str = "INFO"
    request_timeout_s: float = 30.0
    max_history_messages: int = 6
    top_k: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
