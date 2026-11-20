from app.llm.base import LLMClient
from app.retrieval.base import Retriever
from app.schemas.chat import ChatRequest, ChatResponse


class ChatService:
    def __init__(self, retriever: Retriever, llm_client: LLMClient) -> None:
        self.retriever = retriever
        self.llm_client = llm_client

    async def reply(self, request: ChatRequest) -> ChatResponse:
        # TODO (step 3): retrieve documents, build a grounded prompt, and call the LLM.
        return ChatResponse(
            reply="PropLens is being set up. Property answers will be available soon.",
            sources=[],
        )
