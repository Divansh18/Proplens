import json
from pathlib import Path

import pytest

from app.retrieval.base import SearchResult
from app.retrieval.bm25 import BM25Retriever, tokenize
from app.retrieval.chunking import chunk_document, chunk_documents
from app.retrieval.filters import extract_filters
from app.retrieval.load import load_documents
from app.schemas.document import Document
from app.services.chat_service import _city_project_results


def document(id: str, source: str, text: str, metadata: dict[str, object]) -> Document:
    return Document(
        id=id,
        source=source,
        url=f"https://example.com/{id}",
        title=id,
        text=text,
        metadata=metadata,
    )


def test_chunking_keeps_source_and_sentence_overlap() -> None:
    sentences = [
        f"Sentence {index} describes a Dubai property with a garden and pool."
        for index in range(25)
    ]
    parent = document("long", "darglobal", " ".join(sentences), {"type": "portfolio"})

    chunks = chunk_document(parent)

    assert len(chunks) > 1
    assert all(chunk.url == parent.url and chunk.source == parent.source for chunk in chunks)
    assert [chunk.metadata["chunk_index"] for chunk in chunks] == list(range(len(chunks)))
    assert all(len(chunk.text) <= 900 for chunk in chunks)
    assert any(sentence in chunks[0].text and sentence in chunks[1].text for sentence in sentences)
    assert len(chunk_document(document("short", "wasalt", "Short listing.", {}))) == 1


def test_tokenizer_keeps_numbers_and_removes_punctuation_and_stopwords() -> None:
    assert tokenize("A 3-bedroom apartment in Riyadh, SAR 500,000!") == [
        "3",
        "bedroom",
        "apartment",
        "riyadh",
        "sar",
        "500",
        "000",
    ]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "3 bed apartment in Riyadh",
            {"city": "Riyadh", "bedrooms": 3, "property_type": "apartment"},
        ),
        ("3-bedroom villa in Jeddah", {"city": "Jeddah", "bedrooms": 3, "property_type": "villa"}),
        ("3BR villa for rent", {"bedrooms": 3, "purpose": "rent"}),
        ("Apartments for sale under 1M", {"purpose": "sale", "max_price": 1_000_000.0}),
        ("below 500,000", {"max_price": 500_000.0}),
        ("most expensive penthouse on Wasalt", {"source": "wasalt", "price_sort": "desc"}),
        ("cheapest DarGlobal villa in Dubai", {"source": "darglobal", "price_sort": "asc"}),
        (
            "studio rental in Al Kharj",
            {"city": "Al Kharj", "property_type": "studio", "purpose": "rent"},
        ),
    ],
)
def test_filter_extraction(query: str, expected: dict[str, object]) -> None:
    filters = extract_filters(query, frozenset({"Riyadh", "Jeddah", "Dubai", "Al Kharj"}))
    for key, value in expected.items():
        assert getattr(filters, key) == value


def test_retriever_filters_sorts_and_restricts_source() -> None:
    documents = [
        document(
            "expensive",
            "wasalt",
            "3 bedroom apartment for sale in Jeddah.",
            {
                "city": "Jeddah",
                "bedrooms": "3",
                "property_type": "Apartment",
                "purpose": "sale",
                "price": "SAR 500000",
                "type": "listing",
            },
        ),
        document(
            "cheap",
            "wasalt",
            "3 bedroom apartment for sale in Jeddah.",
            {
                "city": "Jeddah",
                "bedrooms": "3",
                "property_type": "Apartment",
                "purpose": "sale",
                "price": "SAR 400000",
                "type": "listing",
            },
        ),
        document(
            "villa",
            "wasalt",
            "Villa for rent in Riyadh.",
            {
                "city": "Riyadh",
                "property_type": "Villa",
                "purpose": "rent",
                "price": "SAR 100000",
                "type": "listing",
            },
        ),
        document(
            "portfolio",
            "darglobal",
            "DarGlobal project in Dubai: DG1 tower.",
            {"type": "portfolio"},
        ),
    ]
    retriever = BM25Retriever(chunk_documents(documents))
    query = "Cheapest 3-bedroom apartment in Jeddah on Wasalt"
    results = retriever.search(query, 5, extract_filters(query, retriever.known_cities))

    assert [result.document.id for result in results[:2]] == ["cheap:chunk:0", "expensive:chunk:0"]
    assert all(result.score > 0 and result.document.source == "wasalt" for result in results)
    assert retriever.search("DarGlobal project in Dubai", 2)[0].document.source == "darglobal"
    assert retriever.search("quasar", 5) == []


def test_data_loader_continues_when_a_source_file_is_missing(tmp_path: Path) -> None:
    record = document("one", "darglobal", "A project in Dubai.", {"type": "project"})
    (tmp_path / "darglobal.json").write_text(json.dumps([record.model_dump(mode="json")]))

    documents, counts = load_documents(tmp_path)

    assert documents == [record]
    assert counts == {"darglobal": 1, "wasalt": 0}


def test_city_project_context_excludes_other_cities() -> None:
    portfolio = document(
        "portfolio",
        "darglobal",
        "Dubai tower and Ras Al Khaimah residence.",
        {
            "type": "portfolio",
            "projects": [
                {"name": "Dubai Tower", "location": "Dubai", "description": "In Dubai."},
                {
                    "name": "Coastal Residence",
                    "location": "Ras Al Khaimah",
                    "description": "By the sea.",
                },
            ],
        },
    )
    result = SearchResult(portfolio, 1.0)

    prepared = _city_project_results([result, result], "Dubai", "Dubai projects")

    assert len(prepared) == 1
    assert "Dubai Tower" in prepared[0].document.text
    assert "Coastal Residence" not in prepared[0].document.text
