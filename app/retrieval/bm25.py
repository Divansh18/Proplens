import re

from rank_bm25 import BM25Okapi

from app.retrieval.base import Retriever, SearchResult
from app.retrieval.filters import (
    QueryFilters,
    is_list_query,
    matches_filters,
    mentioned_source,
    numeric_price,
)
from app.schemas.document import Document

STOPWORDS = frozenset(
    "a an and are as at be by can do for from have has in is it me of on or our the their "
    "to us what which with would you your about tell please there this that".split()
)
WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [word for word in WORD.findall(text.lower()) if word not in STOPWORDS]


class BM25Retriever(Retriever):
    def __init__(self, chunks: list[Document]) -> None:
        self.chunks = chunks
        self._index = BM25Okapi([tokenize(chunk.text) for chunk in chunks]) if chunks else None
        if self._index is not None:
            # BM25Okapi can assign zero or negative IDF in small, repetitive corpora.
            self._index.idf = {term: max(idf, 0.01) for term, idf in self._index.idf.items()}
        cities: set[str] = set()
        for chunk in chunks:
            city = chunk.metadata.get("city")
            if isinstance(city, str) and city.strip():
                cities.add(city.strip())
            for project in chunk.metadata.get("projects", []):
                location = project.get("location") if isinstance(project, dict) else None
                if isinstance(location, str) and location.strip():
                    cities.add(location.strip())
        self._known_cities = frozenset(cities)

    @property
    def known_cities(self) -> frozenset[str]:
        return self._known_cities

    def search(self, query: str, k: int, filters: QueryFilters | None = None) -> list[SearchResult]:
        if self._index is None or k < 1:
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scores = self._index.get_scores(query_tokens)
        source = mentioned_source(query) or (filters.source if filters else None)
        candidates = [
            index
            for index, chunk in enumerate(self.chunks)
            if source is None or chunk.source == source
        ]
        if filters:
            filtered = [
                index for index in candidates if matches_filters(self.chunks[index], filters)
            ]
            if filtered or filters.strict:
                candidates = filtered
        ranked = [index for index in candidates if scores[index] > 0]
        if filters and filters.price_sort:
            priced = [
                index
                for index in ranked
                if self.chunks[index].metadata.get("type") == "listing"
                and numeric_price(self.chunks[index].metadata.get("price")) is not None
            ]
            if priced:
                ranked = sorted(
                    priced,
                    key=lambda index: numeric_price(self.chunks[index].metadata["price"]) or 0,
                    reverse=filters.price_sort == "desc",
                )
            else:
                ranked.sort(key=lambda index: scores[index], reverse=True)
        else:
            ranked.sort(key=lambda index: scores[index], reverse=True)
        if is_list_query(query):
            seen_urls: set[str] = set()
            unique: list[int] = []
            for index in ranked:
                url = self.chunks[index].url
                if url not in seen_urls:
                    seen_urls.add(url)
                    unique.append(index)
            ranked = unique
        return [SearchResult(self.chunks[index], float(scores[index])) for index in ranked[:k]]
