from fastapi.testclient import TestClient

from app.api.deps import get_llm_client, get_retriever
from app.core.errors import LLMError
from app.llm.base import LLMMessage
from app.retrieval.base import SearchResult
from app.retrieval.filters import QueryFilters
from app.schemas.document import Document
from app.services.chat_service import _exact_prices


def test_chat_returns_response_schema(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "Where are the projects?", "history": []})

    assert response.status_code == 200
    assert response.json() == {
        "reply": "DarGlobal has a residential project in Dubai. [1]",
        "sources": [
            {
                "title": "Dubai project",
                "url": "https://example.com/dar-project",
                "source": "darglobal",
            }
        ],
    }


def test_chat_normalizes_model_citation_brackets(client: TestClient) -> None:
    class BracketLLM:
        async def complete(self, messages: list[LLMMessage]) -> str:
            return "Dubai project 【1】"

    client.app.dependency_overrides[get_llm_client] = BracketLLM
    response = client.post("/api/chat", json={"message": "Where is the Dubai project?"})

    assert response.status_code == 200
    assert response.json()["reply"] == "Dubai project [1]"
    assert len(response.json()["sources"]) == 1


def test_price_output_keeps_snapshot_format() -> None:
    priced = Document(
        id="priced",
        source="wasalt",
        url="https://example.com/priced",
        title="Apartment",
        text="Apartment in Jeddah. SAR 320000.",
        metadata={"price": "SAR 320000"},
    )
    assert _exact_prices("The price is SAR 320,000 [1].", [SearchResult(priced, 1.0)]) == (
        "The price is SAR 320000 [1]."
    )


def test_empty_message_returns_consistent_error(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": ""})

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "message": "Invalid request data."}
    }


def test_llm_error_returns_consistent_error(client: TestClient) -> None:
    class FailingLLM:
        async def complete(self, messages: list[LLMMessage]) -> str:
            raise LLMError("private upstream detail")

    client.app.dependency_overrides[get_llm_client] = FailingLLM
    response = client.post("/api/chat", json={"message": "Where are the projects?"})

    assert response.status_code == 502
    assert response.json() == {
        "error": {"code": "llm_error", "message": "The assistant is temporarily unavailable."}
    }


def test_empty_retrieval_skips_llm(client: TestClient) -> None:
    class EmptyRetriever:
        @property
        def known_cities(self) -> frozenset[str]:
            return frozenset()

        def search(
            self, query: str, k: int, filters: QueryFilters | None = None
        ) -> list[SearchResult]:
            return []

    class UnexpectedLLM:
        async def complete(self, messages: list[LLMMessage]) -> str:
            raise AssertionError("LLM should not be called")

    client.app.dependency_overrides[get_retriever] = EmptyRetriever
    client.app.dependency_overrides[get_llm_client] = UnexpectedLLM
    response = client.post("/api/chat", json={"message": "Tell me about a villa"})

    assert response.status_code == 200
    assert "couldn't find matching" in response.json()["reply"]
    assert response.json()["sources"] == []


def test_off_topic_question_skips_llm(client: TestClient) -> None:
    class UnexpectedLLM:
        async def complete(self, messages: list[LLMMessage]) -> str:
            raise AssertionError("LLM should not be called")

    client.app.dependency_overrides[get_llm_client] = UnexpectedLLM
    response = client.post("/api/chat", json={"message": "What's the weather today?"})

    assert response.status_code == 200
    assert "only help with DarGlobal and Wasalt" in response.json()["reply"]
    assert response.json()["sources"] == []


def test_unknown_named_project_skips_llm(client: TestClient) -> None:
    class UnexpectedLLM:
        async def complete(self, messages: list[LLMMessage]) -> str:
            raise AssertionError("LLM should not be called")

    client.app.dependency_overrides[get_llm_client] = UnexpectedLLM
    response = client.post(
        "/api/chat",
        json={"message": 'What is the payment plan for "Moon Tower"?'},
    )

    assert response.status_code == 200
    assert "don't have information about Moon Tower" in response.json()["reply"]
    assert response.json()["sources"] == []
