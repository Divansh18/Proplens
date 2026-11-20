import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_llm_client, get_retriever
from app.llm.base import LLMMessage
from app.retrieval.base import SearchResult
from app.retrieval.bm25 import BM25Retriever
from app.retrieval.chunking import chunk_documents
from app.retrieval.filters import QueryFilters
from app.schemas.document import Document


def listing(kind: str, number: int, price: int, city: str = "Jeddah") -> Document:
    return Document(
        id=f"{kind}-{number}",
        source="wasalt",
        url=f"https://wasalt.sa/en/property/{kind}-{number}",
        title=f"{kind.title()} {number}",
        text=f"{kind.title()} for sale in {city}. Price SAR {price}.",
        metadata={
            "type": "listing",
            "city": city,
            "district": "Al Rawdah",
            "property_type": kind.title(),
            "purpose": "sale",
            "price": f"SAR {price}",
            "area_sqm": "300",
            "bedrooms": str(number + 3),
        },
    )


def test_cheapest_apartment_follow_up_returns_only_jeddah_villas(client: TestClient) -> None:
    documents = [
        listing("villa", 1, 650000),
        listing("villa", 2, 450000),
        listing("villa", 3, 550000),
        listing("villa", 4, 750000),
        listing("apartment", 1, 100000),
        listing("land", 1, 90000),
        listing("villa", 5, 150000, city="Riyadh"),
    ]
    retriever = BM25Retriever(chunk_documents(documents))
    client.app.dependency_overrides[get_retriever] = lambda: retriever
    payload = {
        "message": "What about villas?",
        "history": [
            {
                "role": "user",
                "content": "Cheapest 3-bedroom apartment for sale in Jeddah on Wasalt",
            },
            {"role": "assistant", "content": "Apartment listing details"},
        ],
    }
    by_url = {document.url: document for document in documents}
    for path in ("/api/chat", "/api/chat/stream"):
        response = client.post(path, json=payload)
        assert response.status_code == 200
        if path.endswith("stream"):
            event_data = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            reply = event_data[0]["text"]
            sources = event_data[1]["sources"]
        else:
            reply = response.json()["reply"]
            sources = response.json()["sources"]
        assert "Lowest-priced options" in reply
        assert [by_url[source["url"]].metadata["price"] for source in sources] == [
            "SAR 450000",
            "SAR 550000",
            "SAR 650000",
        ]
        assert all(
            by_url[source["url"]].metadata["property_type"] == "Villa"
            and by_url[source["url"]].metadata["city"] == "Jeddah"
            for source in sources
        )
        assert "Apartment" not in reply and "Land" not in reply


def test_no_matching_follow_up_does_not_show_other_types(client: TestClient) -> None:
    documents = [listing("apartment", 1, 100000), listing("land", 1, 90000)]
    client.app.dependency_overrides[get_retriever] = lambda: BM25Retriever(
        chunk_documents(documents)
    )
    response = client.post(
        "/api/chat",
        json={
            "message": "What about villas?",
            "history": [
                {"role": "user", "content": "Cheapest 3-bedroom apartment in Jeddah on Wasalt"}
            ],
        },
    )
    assert response.status_code == 200
    assert "couldn't find matching" in response.json()["reply"]
    assert "villa" in response.json()["reply"]
    assert "Jeddah" in response.json()["reply"]
    assert response.json()["sources"] == []


def test_trailing_citation_list_and_extra_markers_are_removed(client: TestClient) -> None:
    documents = [
        Document(
            id=f"project-{number}",
            source="darglobal",
            url=f"https://example.com/project-{number}",
            title=f"Project {number}",
            text="Trump Tower Jeddah is a project in Jeddah.",
            metadata={"type": "project"},
        )
        for number in range(1, 5)
    ]

    class FourResults:
        @property
        def known_cities(self) -> frozenset[str]:
            return frozenset({"Jeddah"})

        def search(
            self, query: str, k: int, filters: QueryFilters | None = None
        ) -> list[SearchResult]:
            return [SearchResult(document, 1.0) for document in documents]

    class ExcessiveCitations:
        async def complete(self, messages: list[LLMMessage]) -> str:
            assert "Never add a Citations: or Sources: list" in messages[0]["content"]
            return (
                "- Trump Tower Jeddah is in Jeddah [1][2][4]\n"
                "- The project has homes [1] [2] [4]\n"
                "Citations: [1] URL and project description, [2] other details"
            )

    client.app.dependency_overrides[get_retriever] = FourResults
    client.app.dependency_overrides[get_llm_client] = ExcessiveCitations
    response = client.post("/api/chat", json={"message": "Tell me about Trump Tower Jeddah"})
    reply = response.json()["reply"]
    assert "Citations:" not in reply
    assert "Sources:" not in reply
    assert "[4]" not in reply
    assert all(len(re.findall(r"\[\d+\]", line)) <= 2 for line in reply.splitlines())
    assert len(response.json()["sources"]) == 2


def test_project_list_uses_clean_names(client: TestClient) -> None:
    records = json.loads((Path(__file__).resolve().parents[1] / "data/darglobal.json").read_text())
    retriever = BM25Retriever(chunk_documents([Document.model_validate(x) for x in records]))
    client.app.dependency_overrides[get_retriever] = lambda: retriever
    response = client.post(
        "/api/chat", json={"message": "What projects does DarGlobal have in Dubai?"}
    )
    reply = response.json()["reply"]
    assert "DG1, Business Bay" in reply
    assert "Apartments in Business Bay, Dubai for Sale" not in reply
    assert "D-Villas |" not in reply
