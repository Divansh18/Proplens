import asyncio
import json
import re
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.api.deps import get_llm_client, get_retriever
from app.core.errors import LLMError
from app.llm.base import LLMMessage
from app.retrieval.base import SearchResult
from app.retrieval.filters import QueryFilters
from app.schemas.document import Document


def events(response_text: str) -> list[dict[str, object]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response_text.splitlines()
        if line.startswith("data: ")
    ]


def test_stream_event_order_and_cache(client: TestClient) -> None:
    calls = 0

    class StreamingLLM:
        async def stream(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
            nonlocal calls
            calls += 1
            yield "A Dubai "
            yield "project [1]"

    client.app.dependency_overrides[get_llm_client] = StreamingLLM
    first = client.post("/api/chat/stream", json={"message": "Where are the projects?"})
    second = client.post("/api/chat/stream", json={"message": "Where are the projects?"})
    first_events = events(first.text)
    second_events = events(second.text)

    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    assert first.headers["cache-control"] == "no-cache"
    assert first.headers["x-accel-buffering"] == "no"
    assert [event["type"] for event in first_events] == ["token", "token", "sources", "done"]
    assert [event["type"] for event in second_events] == ["token", "sources", "done"]
    assert second_events[0]["text"] == "A Dubai project [1]"
    assert first_events[2]["sources"][0]["source"] == "darglobal"
    assert calls == 1


def test_stream_deterministic_answer_skips_llm(client: TestClient) -> None:
    class UnexpectedLLM:
        async def stream(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
            raise AssertionError("Off-topic response should not call the model")
            yield ""  # pragma: no cover

    client.app.dependency_overrides[get_llm_client] = UnexpectedLLM
    response = client.post("/api/chat/stream", json={"message": "What's the weather today?"})
    data = events(response.text)
    assert [event["type"] for event in data] == ["token", "sources", "done"]
    assert "only help" in data[0]["text"]
    assert data[1]["sources"] == []


def test_stream_midstream_error_has_no_sources_or_cache(client: TestClient) -> None:
    calls = 0

    class BrokenLLM:
        async def stream(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
            nonlocal calls
            calls += 1
            yield "Partial"
            raise LLMError("private upstream detail")

    client.app.dependency_overrides[get_llm_client] = BrokenLLM
    for _ in range(2):
        response = client.post("/api/chat/stream", json={"message": "Where are the projects?"})
        data = events(response.text)
        assert [event["type"] for event in data] == ["token", "error", "done"]
        assert data[1]["message"] == "The assistant is temporarily unavailable."
    assert calls == 2


def test_stream_heartbeats_before_first_token(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.services.chat_service.HEARTBEAT_INTERVAL_S", 0.001)

    class SlowLLM:
        async def stream(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
            await asyncio.sleep(0.01)
            yield "Dubai [1]"

    client.app.dependency_overrides[get_llm_client] = SlowLLM
    response = client.post("/api/chat/stream", json={"message": "Where are the projects?"})
    assert ": ping\n\n" in response.text
    assert response.text.index(": ping") < response.text.index('"type": "token"')


def test_follow_up_villas_never_repeats_apartment_details(client: TestClient) -> None:
    villas = [
        Document(
            id=f"villa-{index}",
            source="wasalt",
            url=f"https://wasalt.sa/en/property/villa-{index}",
            title=f"Villa {index}",
            text=f"Villa in Jeddah, SAR {index}000000",
            metadata={
                "type": "listing",
                "city": "Jeddah",
                "district": "Al Rawdah",
                "property_type": "villa",
                "price": f"SAR {index}000000",
                "area_sqm": "300",
                "bedrooms": "3",
            },
        )
        for index in range(1, 3)
    ]

    class VillaRetriever:
        @property
        def known_cities(self) -> frozenset[str]:
            return frozenset({"Jeddah"})

        def search(
            self, query: str, k: int, filters: QueryFilters | None = None
        ) -> list[SearchResult]:
            assert filters is not None
            assert filters.city == "Jeddah"
            assert filters.property_type == "villa"
            return [SearchResult(doc, 2.0) for doc in villas]

    class UnexpectedLLM:
        async def complete(self, messages: list[LLMMessage]) -> str:
            raise AssertionError("Listing answer should be deterministic")

    client.app.dependency_overrides[get_retriever] = VillaRetriever
    client.app.dependency_overrides[get_llm_client] = UnexpectedLLM
    payload = {
        "message": "What about villas?",
        "history": [
            {"role": "user", "content": "Show apartments in Jeddah on Wasalt"},
            {
                "role": "assistant",
                "content": "Apartment 1\n\nWasalt listing details:\n- Apartment 1",
            },
        ],
    }
    for path in ("/api/chat", "/api/chat/stream"):
        response = client.post(path, json=payload)
        reply = (
            response.json()["reply"] if path == "/api/chat" else events(response.text)[0]["text"]
        )
        assert reply.count("Wasalt listing details:") == 1
        assert "Apartment" not in reply
        assert "Villa 1" in reply and "Villa 2" in reply
        assert len(re.findall(r"\[\d+\]", reply)) == 2


def test_no_information_reply_has_no_sources(client: TestClient) -> None:
    class UnknownLLM:
        async def complete(self, messages: list[LLMMessage]) -> str:
            return "I don't have that information in the context. [1]"

    client.app.dependency_overrides[get_llm_client] = UnknownLLM
    response = client.post("/api/chat", json={"message": "When does the project open?"})
    assert response.json()["sources"] == []


def test_dubai_project_list_includes_distinct_projects(client: TestClient) -> None:
    from pathlib import Path

    from app.retrieval.bm25 import BM25Retriever
    from app.retrieval.chunking import chunk_documents

    records = json.loads((Path(__file__).resolve().parents[1] / "data/darglobal.json").read_text())
    documents = [Document.model_validate(record) for record in records]
    retriever = BM25Retriever(chunk_documents(documents))

    class UnexpectedLLM:
        async def complete(self, messages: list[LLMMessage]) -> str:
            raise AssertionError("Project list should include each retrieved page directly")

    client.app.dependency_overrides[get_retriever] = lambda: retriever
    client.app.dependency_overrides[get_llm_client] = UnexpectedLLM
    response = client.post(
        "/api/chat", json={"message": "What projects does DarGlobal have in Dubai?"}
    )
    reply = response.json()["reply"]
    assert "D-Villas" in reply
    assert "Urban Oasis" in reply
    assert "W Residences" in reply
    assert "The Astera" not in reply
    bullets = [line for line in reply.splitlines() if line.startswith("- ")]
    assert len(bullets) == len(response.json()["sources"]) == 6
    assert all(len(re.findall(r"\[\d+\]", line)) == 1 for line in bullets)


def test_stream_no_information_has_no_sources(client: TestClient) -> None:
    class UnknownLLM:
        async def stream(self, messages: list[LLMMessage]) -> AsyncIterator[str]:
            yield "I don't have that information in the context. [1]"

    client.app.dependency_overrides[get_llm_client] = UnknownLLM
    response = client.post("/api/chat/stream", json={"message": "When does the project open?"})
    data = events(response.text)
    assert [event["type"] for event in data] == ["token", "sources", "done"]
    assert data[1]["sources"] == []


def test_list_all_uses_complete_portfolio(client: TestClient) -> None:
    from pathlib import Path

    from app.retrieval.bm25 import BM25Retriever
    from app.retrieval.chunking import chunk_documents

    records = json.loads((Path(__file__).resolve().parents[1] / "data/darglobal.json").read_text())
    documents = [Document.model_validate(record) for record in records]
    client.app.dependency_overrides[get_retriever] = lambda: BM25Retriever(
        chunk_documents(documents)
    )
    response = client.post("/api/chat", json={"message": "List all DarGlobal projects"})
    reply = response.json()["reply"]
    assert len([line for line in reply.splitlines() if line.startswith("- ")]) == 20
    assert "D-Villas" in reply
    assert "Trump Tower — Dubai" in reply
    assert "Amaya — Jeddah" in reply
