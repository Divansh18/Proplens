from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.document import PropertySource

MessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: MessageText
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class Source(BaseModel):
    title: str
    url: str
    source: PropertySource


class ChatResponse(BaseModel):
    reply: str
    sources: list[Source]
