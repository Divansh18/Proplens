from collections.abc import AsyncIterator
from typing import Protocol, TypedDict


class LLMMessage(TypedDict):
    role: str
    content: str


class LLMClient(Protocol):
    async def complete(self, messages: list[LLMMessage]) -> str: ...

    def stream(self, messages: list[LLMMessage]) -> AsyncIterator[str]: ...
