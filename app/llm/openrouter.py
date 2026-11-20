from app.core.config import Settings
from app.core.errors import LLMError
from app.llm.base import LLMClient, LLMMessage


class OpenRouterClient(LLMClient):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete(self, messages: list[LLMMessage]) -> str:
        # TODO (step 3): call OpenRouter chat completions with async httpx.
        raise LLMError()
