import asyncio
import logging

import httpx

from app.core.config import Settings
from app.core.errors import LLMBusyError, LLMError
from app.llm.base import LLMClient, LLMMessage

logger = logging.getLogger(__name__)


class OpenRouterClient(LLMClient):
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=settings.request_timeout_s)
        self._unavailable_models: set[str] = set()

    async def aclose(self) -> None:
        await self.client.aclose()

    async def complete(self, messages: list[LLMMessage]) -> str:
        api_key = self.settings.openrouter_api_key.get_secret_value()
        if not api_key:
            raise LLMError()
        models = list(
            dict.fromkeys([self.settings.openrouter_model, *self.settings.fallback_models])
        )
        url = f"{self.settings.openrouter_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.settings.openrouter_http_referer,
            "X-Title": "PropLens",
        }
        busy_failure = False
        other_failure = False
        for model in models:
            if model in self._unavailable_models:
                continue
            for attempt in range(3):
                try:
                    response = await self.client.post(
                        url,
                        headers=headers,
                        json={
                            "model": model,
                            "messages": messages,
                            "temperature": 0.2,
                            "max_tokens": 600,
                            "reasoning": {"enabled": False},
                        },
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    other_failure = True
                    logger.warning(
                        "OpenRouter request failed model=%s attempt=%d error=%s",
                        model,
                        attempt + 1,
                        type(exc).__name__,
                    )
                    if attempt < 2:
                        await asyncio.sleep(2**attempt)
                        continue
                    break
                if response.status_code == 429 or response.status_code >= 500:
                    busy_failure = True
                    logger.warning(
                        "OpenRouter retryable response model=%s status=%d attempt=%d",
                        model,
                        response.status_code,
                        attempt + 1,
                    )
                    if attempt < 2:
                        await asyncio.sleep(2**attempt)
                        continue
                    break
                if response.is_error:
                    logger.warning(
                        "OpenRouter rejected model=%s status=%d", model, response.status_code
                    )
                    if response.status_code == 404:
                        self._unavailable_models.add(model)
                    else:
                        other_failure = True
                    break
                try:
                    content = response.json()["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError):
                    other_failure = True
                    logger.warning("OpenRouter returned an invalid response for model=%s", model)
                    break
                if isinstance(content, str) and content.strip():
                    logger.info("OpenRouter completed model=%s", model)
                    return content.strip()
                logger.warning("OpenRouter returned an empty response for model=%s", model)
                other_failure = True
                break
        if busy_failure and not other_failure:
            raise LLMBusyError()
        raise LLMError()
