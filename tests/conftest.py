from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm_client, get_retriever
from app.llm.base import LLMMessage
from app.main import create_app
from app.schemas.document import Document


class FakeRetriever:
    def search(self, query: str, k: int) -> list[Document]:
        return []


class FakeLLMClient:
    async def complete(self, messages: list[LLMMessage]) -> str:
        return "Fake answer"


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_retriever] = FakeRetriever
    app.dependency_overrides[get_llm_client] = FakeLLMClient
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
