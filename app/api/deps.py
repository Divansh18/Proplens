from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.llm.base import LLMClient
from app.retrieval.base import Retriever
from app.services.cache import ResponseCache
from app.services.chat_service import ChatService


def get_retriever(request: Request) -> Retriever:
    return request.app.state.retriever


def get_llm_client(request: Request) -> LLMClient:
    return request.app.state.llm_client


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_response_cache(request: Request) -> ResponseCache:
    return request.app.state.response_cache


def get_chat_service(
    retriever: Annotated[Retriever, Depends(get_retriever)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    cache: Annotated[ResponseCache, Depends(get_response_cache)],
) -> ChatService:
    return ChatService(retriever, llm_client, settings, cache)
