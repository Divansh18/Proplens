from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_model: str = "nvidia/nemotron-3.5-lightning:free"
    openrouter_fallback_models: str = (
        "baidu/ernie-5.5-flash-preview:free,"
        "nvidia/nemotron-3-ultra-550b-a55b:free,"
        "google/gemma-4-31b-it:free,"
        "google/gemma-4-26b-a4b-it:free"
    )
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_http_referer: str = "http://localhost:8000"
    data_dir: Path = PROJECT_ROOT / "data"
    log_level: str = "INFO"
    request_timeout_s: float = 30.0
    max_history_messages: int = 6
    top_k: int = 5

    @property
    def fallback_models(self) -> list[str]:
        return [
            model.strip() for model in self.openrouter_fallback_models.split(",") if model.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
