import re

from app.schemas.document import Document

SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str, target_chars: int) -> list[str]:
    parts: list[str] = []
    for sentence in SENTENCE_BREAK.split(" ".join(text.split())):
        if len(sentence) <= target_chars:
            parts.append(sentence)
            continue
        words = sentence.split()
        current: list[str] = []
        for word in words:
            if current and len(" ".join((*current, word))) > target_chars:
                parts.append(" ".join(current))
                current = []
            current.append(word)
        if current:
            parts.append(" ".join(current))
    return [part for part in parts if part]


def chunk_document(
    document: Document, target_chars: int = 800, overlap_chars: int = 100
) -> list[Document]:
    sentences = _sentences(document.text, target_chars)
    if not sentences:
        return []
    chunks: list[Document] = []
    start = 0
    while start < len(sentences):
        end = start
        length = 0
        while end < len(sentences):
            next_length = length + len(sentences[end]) + (1 if length else 0)
            if end > start and next_length > target_chars:
                break
            length = next_length
            end += 1
        chunks.append(
            document.model_copy(
                update={
                    "id": f"{document.id}:chunk:{len(chunks)}",
                    "text": " ".join(sentences[start:end]),
                    "metadata": {**document.metadata, "chunk_index": len(chunks)},
                }
            )
        )
        if end == len(sentences):
            break
        next_start = end
        overlap = 0
        while next_start > start + 1 and overlap < overlap_chars:
            next_start -= 1
            overlap += len(sentences[next_start]) + 1
        start = next_start
    return chunks


def chunk_documents(documents: list[Document]) -> list[Document]:
    return [chunk for document in documents for chunk in chunk_document(document)]
