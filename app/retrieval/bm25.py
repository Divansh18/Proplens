from app.core.errors import DataNotLoadedError
from app.retrieval.base import Retriever
from app.schemas.document import Document


class BM25Retriever(Retriever):
    def search(self, query: str, k: int) -> list[Document]:
        # TODO (step 3): index committed JSON documents and rank results with rank_bm25.
        raise DataNotLoadedError()
