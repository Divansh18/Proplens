from typing import Any, Literal

from pydantic import BaseModel, Field

PropertySource = Literal["darglobal", "wasalt"]


class Document(BaseModel):
    id: str
    source: PropertySource
    url: str
    title: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
