from fastapi.testclient import TestClient

from app.api.deps import get_chat_service
from app.core.errors import LLMError
from app.schemas.chat import ChatRequest, ChatResponse


def test_chat_returns_response_schema(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "Where are the projects?", "history": []})

    assert response.status_code == 200
    assert response.json() == {
        "reply": "PropLens is being set up. Property answers will be available soon.",
        "sources": [],
    }


def test_empty_message_returns_consistent_error(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": ""})

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "message": "Invalid request data."}
    }


def test_service_error_returns_consistent_error(client: TestClient) -> None:
    class FailingChatService:
        async def reply(self, request: ChatRequest) -> ChatResponse:
            raise LLMError("private upstream detail")

    client.app.dependency_overrides[get_chat_service] = FailingChatService
    response = client.post("/api/chat", json={"message": "Where are the projects?"})

    assert response.status_code == 502
    assert response.json() == {
        "error": {"code": "llm_error", "message": "The assistant is temporarily unavailable."}
    }
