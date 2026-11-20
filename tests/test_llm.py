import json

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import LLMError
from app.llm.openrouter import OpenRouterClient


@pytest.mark.asyncio
async def test_openrouter_uses_headers_and_fallback_model() -> None:
    models: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["HTTP-Referer"] == "http://localhost:8000"
        assert request.headers["X-Title"] == "PropLens"
        payload = json.loads(request.content)
        assert payload["temperature"] == 0.2
        assert payload["max_tokens"] == 600
        assert payload["reasoning"] == {"enabled": False}
        models.append(payload["model"])
        if len(models) == 1:
            return httpx.Response(404)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Grounded answer [1]"}}]}
        )

    settings = Settings(
        openrouter_api_key="test-key",
        openrouter_model="primary:free",
        openrouter_fallback_models="fallback:free",
    )
    client = OpenRouterClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        answer = await client.complete([{"role": "user", "content": "Hello"}])
        second_answer = await client.complete([{"role": "user", "content": "Hello again"}])
    finally:
        await client.aclose()

    assert answer == "Grounded answer [1]"
    assert second_answer == answer
    assert models == ["primary:free", "fallback:free", "fallback:free"]


@pytest.mark.asyncio
async def test_openrouter_failure_raises_safe_error() -> None:
    settings = Settings(openrouter_api_key="test-key", openrouter_model="primary:free")
    client = OpenRouterClient(
        settings,
        httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(401))),
    )
    try:
        with pytest.raises(LLMError):
            await client.complete([{"role": "user", "content": "Hello"}])
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_openrouter_retries_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    async def no_sleep(_seconds: float) -> None:
        return None

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Done"}}]})

    monkeypatch.setattr("app.llm.openrouter.asyncio.sleep", no_sleep)
    settings = Settings(openrouter_api_key="test-key", openrouter_model="primary:free")
    client = OpenRouterClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        assert await client.complete([{"role": "user", "content": "Hello"}]) == "Done"
    finally:
        await client.aclose()
    assert attempts == 3
