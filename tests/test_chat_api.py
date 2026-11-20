from fastapi.testclient import TestClient

from app.api.deps import get_llm_client, get_retriever
from app.core.errors import LLMBusyError, LLMError
from app.llm.base import LLMMessage
from app.retrieval.base import SearchResult
from app.retrieval.filters import QueryFilters
from app.schemas.document import Document
from app.services.chat_service import _exact_prices
from app.services.listing_answer import append_listing_details


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


def test_busy_llm_returns_friendly_503(client: TestClient) -> None:
    class BusyLLM:
        async def complete(self, messages: list[LLMMessage]) -> str:
            raise LLMBusyError()

    client.app.dependency_overrides[get_llm_client] = BusyLLM
    response = client.post("/api/chat", json={"message": "Where are the projects?"})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "llm_busy",
            "message": "The AI model is busy, please try again in a minute.",
        }
    }


def test_cheapest_listing_includes_fields_and_next_two(client: TestClient) -> None:
    prices = ("SAR 320000", "SAR 340000", "SAR 345000")
    listings = [
        Document(
            id=f"listing-{index}",
            source="wasalt",
            url=f"https://wasalt.sa/en/property/sale/listing-{index}",
            title=f"Apartment option {index}",
            text=f"Apartment for sale in Jeddah. Price: {price}.",
            metadata={
                "type": "listing",
                "city": "Jeddah",
                "district": f"District {index}",
                "price": price,
                "area_sqm": "2919.75" if index == 1 else "120",
                "area_unverified": index == 1,
                "bedrooms": "3",
            },
        )
        for index, price in enumerate(prices, start=1)
    ]

    class ListingRetriever:
        @property
        def known_cities(self) -> frozenset[str]:
            return frozenset({"Jeddah"})

        def search(
            self, query: str, k: int, filters: QueryFilters | None = None
        ) -> list[SearchResult]:
            return [
                SearchResult(document, 3.0 / index) for index, document in enumerate(listings, 1)
            ]

    class ListingLLM:
        async def complete(self, messages: list[LLMMessage]) -> str:
            raise AssertionError("Structured price comparisons should skip the LLM")

    client.app.dependency_overrides[get_retriever] = ListingRetriever
    client.app.dependency_overrides[get_llm_client] = ListingLLM
    response = client.post(
        "/api/chat", json={"message": "Cheapest 3-bedroom apartment in Jeddah on Wasalt"}
    )

    assert response.status_code == 200
    body = response.json()
    assert "SAR 320000" in body["reply"]
    assert "SAR 320,000" not in body["reply"]
    assert "Lowest-priced options (including the next two)" in body["reply"]
    for index, price in enumerate(prices, start=1):
        assert f"Apartment option {index}" in body["reply"]
        assert f"District {index}" in body["reply"]
        assert price in body["reply"]
        assert f"https://wasalt.sa/en/property/sale/listing-{index}" in body["reply"]
    assert "City: Jeddah" in body["reply"]
    assert "Bedrooms: 3" in body["reply"]
    assert "2919.75 sqm (reported by Wasalt; unverified)" in body["reply"]
    assert len(body["sources"]) == 3


def test_listing_details_keep_arabic_labels() -> None:
    listing = Document(
        id="arabic-listing",
        source="wasalt",
        url="https://wasalt.sa/en/property/sale/example",
        title="Apartment in Jeddah",
        text="Apartment in Jeddah.",
        metadata={
            "type": "listing",
            "city": "Jeddah",
            "district": "Al Thagur",
            "price": "SAR 320000",
            "area_sqm": "2919.75",
            "area_unverified": True,
            "bedrooms": "3",
        },
    )
    reply = append_listing_details(
        "", [SearchResult(listing, 1.0)], QueryFilters(price_sort="asc"), arabic=True
    )

    assert "أقل الأسعار" in reply
    assert "السعر: SAR 320000" in reply
    assert "المساحة: 2919.75 sqm (كما ورد في Wasalt؛ غير مؤكد)" in reply
    assert "رابط الإعلان: https://wasalt.sa/en/property/sale/example" in reply


def test_identical_no_history_questions_share_cached_answer(client: TestClient) -> None:
    calls = 0

    class CountingLLM:
        async def complete(self, messages: list[LLMMessage]) -> str:
            nonlocal calls
            calls += 1
            return "Dubai project [1]"

    client.app.dependency_overrides[get_llm_client] = CountingLLM
    first = client.post("/api/chat", json={"message": "Where are the projects?"})
    second = client.post("/api/chat", json={"message": "WHERE are the projects!"})
    follow_up = client.post(
        "/api/chat",
        json={"message": "Where are the projects?", "history": [{"role": "user", "content": "Hi"}]},
    )

    assert first.status_code == second.status_code == follow_up.status_code == 200
    assert first.json() == second.json()
    assert calls == 2


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
