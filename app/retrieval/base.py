from typing import Protocol

from app.schemas.document import Document


class Retriever(Protocol):
    def search(self, query: str, k: int) -> list[Document]: ...
