from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.llm.base import LLMClient
from app.llm.openrouter import OpenRouterClient
from app.retrieval.base import Retriever
from app.retrieval.bm25 import BM25Retriever
from app.services.chat_service import ChatService


def get_retriever() -> Retriever:
    return BM25Retriever()


def get_llm_client(settings: Annotated[Settings, Depends(get_settings)]) -> LLMClient:
    return OpenRouterClient(settings)


def get_chat_service(
    retriever: Annotated[Retriever, Depends(get_retriever)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
) -> ChatService:
    return ChatService(retriever, llm_client)
