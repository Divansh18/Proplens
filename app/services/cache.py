from collections import OrderedDict
from collections.abc import Callable
from time import monotonic

from app.retrieval.filters import QueryFilters
from app.schemas.chat import ChatResponse

CacheKey = tuple[str, QueryFilters]


class ResponseCache:
    def __init__(
        self,
        max_entries: int = 200,
        ttl_s: float = 3600,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.max_entries = max_entries
        self.ttl_s = ttl_s
        self.clock = clock
        self._entries: OrderedDict[CacheKey, tuple[float, ChatResponse]] = OrderedDict()

    def get(self, key: CacheKey) -> ChatResponse | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, response = entry
        if expires_at <= self.clock():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return response.model_copy(deep=True)

    def set(self, key: CacheKey, response: ChatResponse) -> None:
        self._entries[key] = (self.clock() + self.ttl_s, response.model_copy(deep=True))
        self._entries.move_to_end(key)
        if len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
