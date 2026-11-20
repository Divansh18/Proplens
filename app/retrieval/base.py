from dataclasses import dataclass
from typing import Protocol

from app.retrieval.filters import QueryFilters
from app.schemas.document import Document


@dataclass(frozen=True)
class SearchResult:
    document: Document
    score: float


class Retriever(Protocol):
    @property
    def known_cities(self) -> frozenset[str]: ...

    def search(
        self, query: str, k: int, filters: QueryFilters | None = None
    ) -> list[SearchResult]: ...
