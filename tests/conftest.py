from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm_client, get_retriever
from app.core.config import Settings
from app.llm.base import LLMMessage
from app.main import create_app
from app.retrieval.base import SearchResult
from app.retrieval.filters import QueryFilters
from app.schemas.document import Document

FAKE_DOCUMENT = Document(
    id="darglobal-test",
    source="darglobal",
    url="https://example.com/dar-project",
    title="Dubai project",
    text="DarGlobal has a residential project in Dubai.",
    metadata={"type": "project"},
)


class FakeRetriever:
    @property
    def known_cities(self) -> frozenset[str]:
        return frozenset({"Dubai"})

    def search(self, query: str, k: int, filters: QueryFilters | None = None) -> list[SearchResult]:
        return [SearchResult(FAKE_DOCUMENT, 2.0)]


class FakeLLMClient:
    async def complete(self, messages: list[LLMMessage]) -> str:
        return "DarGlobal has a residential project in Dubai. [1]"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    (tmp_path / "darglobal.json").write_text(f"[{FAKE_DOCUMENT.model_dump_json()}]")
    app = create_app(Settings(data_dir=tmp_path))
    app.dependency_overrides[get_retriever] = FakeRetriever
    app.dependency_overrides[get_llm_client] = FakeLLMClient
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
