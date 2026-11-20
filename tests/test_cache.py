from app.retrieval.filters import QueryFilters
from app.schemas.chat import ChatResponse
from app.services.cache import ResponseCache


def test_cache_expires_and_evicts_least_recently_used() -> None:
    current = [0.0]
    cache = ResponseCache(max_entries=2, ttl_s=3600, clock=lambda: current[0])
    filters = QueryFilters()
    first = ("first", filters)
    second = ("second", filters)
    third = ("third", filters)
    response = ChatResponse(reply="answer", sources=[])

    cache.set(first, response)
    cache.set(second, response)
    assert cache.get(first) == response
    cache.set(third, response)
    assert cache.get(second) is None
    assert cache.get(first) == response
    current[0] = 3600
    assert cache.get(first) is None
