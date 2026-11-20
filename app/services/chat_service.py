import re
from dataclasses import replace

from app.core.config import Settings
from app.llm.base import LLMClient, LLMMessage
from app.retrieval.base import Retriever, SearchResult
from app.retrieval.filters import QueryFilters, extract_filters
from app.schemas.chat import ChatRequest, ChatResponse, Source
from app.services.cache import CacheKey, ResponseCache
from app.services.listing_answer import append_listing_details

SYSTEM_PROMPT = (
    "You are PropLens, an assistant for DarGlobal and Wasalt property information. "
    "Answer ONLY from the provided context. If the answer is not in the context, say you "
    "do not have that information and suggest what the user could ask instead. Never invent "
    "prices, availability, payment plans, or dates. Quote prices exactly as written, with "
    "their currency. Be concise; use short bullet lists when comparing listings. "
    "For Wasalt listings, include the title, city, district, exact price, area, bedrooms, "
    "and listing URL. If comparing lowest or highest prices, show the next two options too. "
    "Say 'not provided' for missing fields. Treat areas marked unverified as reported values. "
    "Reply in the same language as the user (English or Arabic). Cite factual claims with "
    "the numbered "
    "context markers [1], [2], and so on. Do not cite a number that is not in the context."
)
ARABIC = re.compile(r"[\u0600-\u06ff]")
OFF_TOPIC = re.compile(
    r"\b(weather|forecast|temperature|sports|recipe|joke|movie)\b|الطقس|الجو", re.I
)
FOLLOW_UP = re.compile(r"^(what about|how about|and |those|these|any )", re.I)
QUOTED_NAME = re.compile(r'["“]([^"”]{3,80})["”]')
PRICE = re.compile(r"\b([A-Z]{3})\s+(\d[\d,]*(?:\.\d+)?)\b")


def _no_match(arabic: bool) -> str:
    if arabic:
        return (
            "لا أجد معلومات مطابقة في بيانات دار جلوبال وواصلت. "
            "جرّب السؤال عن مشروع أو مدينة أو نوع عقار محدد."
        )
    return (
        "I couldn't find matching DarGlobal or Wasalt information. "
        "Try asking about a specific project, city, or property type."
    )


def _unknown_name(name: str, arabic: bool) -> str:
    if arabic:
        return f"لا أملك معلومات عن {name} في البيانات الحالية. جرّب السؤال عن مشروع معروف."
    return (
        f"I don't have information about {name} in the current data. "
        "Try asking about a known project."
    )


def _off_topic(arabic: bool) -> str:
    if arabic:
        return "أساعد فقط في الأسئلة العقارية عن دار جلوبال وواصلت. اسألني عن مشروع أو عقار لديهما."
    return (
        "I can only help with DarGlobal and Wasalt property questions. "
        "Ask me about a project or listing."
    )


def _source_list(results: list[SearchResult], reply: str) -> list[Source]:
    cited = {int(number) for number in re.findall(r"\[(\d+)\]", reply)}
    selected = [result for index, result in enumerate(results, start=1) if index in cited]
    if not selected:
        selected = results[:3]
    sources: list[Source] = []
    seen: set[str] = set()
    for result in selected:
        document = result.document
        if document.url in seen:
            continue
        seen.add(document.url)
        sources.append(Source(title=document.title, url=document.url, source=document.source))
    return sources


def _normalize_citations(reply: str) -> str:
    return re.sub(r"[【［](\d+)[】］]", r"[\1]", reply)


def _exact_prices(reply: str, results: list[SearchResult]) -> str:
    originals: dict[tuple[str, str], str] = {}
    for result in results:
        price = str(result.document.metadata.get("price", ""))
        match = PRICE.search(price)
        if match:
            originals[(match.group(1), match.group(2).replace(",", ""))] = match.group(0)

    def replace_price(match: re.Match[str]) -> str:
        key = (match.group(1), match.group(2).replace(",", ""))
        return originals.get(key, match.group(0))

    return PRICE.sub(replace_price, reply)


def _context(results: list[SearchResult]) -> str:
    return "\n\n".join(
        f"[{index}] Source: {result.document.source}\n"
        f"Title: {result.document.title}\n"
        f"URL: {result.document.url}\n"
        f"Text: {result.document.text}"
        for index, result in enumerate(results, start=1)
    )


def _city_project_results(
    results: list[SearchResult], city: str | None, query: str
) -> list[SearchResult]:
    if city is None:
        return results
    prepared: list[SearchResult] = []
    seen_portfolios: set[str] = set()
    for result in results:
        document = result.document
        projects = document.metadata.get("projects")
        if not isinstance(projects, list):
            prepared.append(result)
            continue
        if document.url in seen_portfolios:
            continue
        seen_portfolios.add(document.url)
        matching = [
            project
            for project in projects
            if isinstance(project, dict)
            and str(project.get("location", "")).casefold() == city.casefold()
        ]
        if not matching:
            continue
        normalized_query = re.sub(r"\W+", " ", query).casefold()
        named = [
            project
            for project in matching
            if re.sub(r"\W+", " ", str(project.get("name", ""))).casefold() in normalized_query
        ]
        if named:
            matching = named
        text = "\n".join(
            f"{project['name']} in {project['location']}. {project.get('description', '')} "
            f"Status: {project.get('status', 'not stated')}."
            for project in matching
        )
        prepared.append(SearchResult(document.model_copy(update={"text": text}), result.score))
    if any(result.document.metadata.get("projects") for result in prepared):
        prepared = [
            result
            for result in prepared
            if result.document.metadata.get("type") != "company"
            or "project" not in query.casefold()
        ]
    return prepared


def _follow_up_filters(
    current: QueryFilters, request: ChatRequest, retriever: Retriever
) -> QueryFilters:
    if not FOLLOW_UP.search(request.message.strip()):
        return current
    prior_user = next(
        (item.content for item in reversed(request.history) if item.role == "user"), ""
    )
    if not prior_user:
        return current
    previous = extract_filters(prior_user, retriever.known_cities)
    return replace(
        current,
        city=current.city or previous.city,
        bedrooms=current.bedrooms if current.bedrooms is not None else previous.bedrooms,
        property_type=current.property_type or previous.property_type,
        purpose=current.purpose or previous.purpose,
        max_price=current.max_price if current.max_price is not None else previous.max_price,
        source=current.source or previous.source,
    )


class ChatService:
    def __init__(
        self,
        retriever: Retriever,
        llm_client: LLMClient,
        settings: Settings,
        cache: ResponseCache,
    ) -> None:
        self.retriever = retriever
        self.llm_client = llm_client
        self.settings = settings
        self.cache = cache

    async def reply(self, request: ChatRequest) -> ChatResponse:
        arabic = bool(ARABIC.search(request.message))
        if OFF_TOPIC.search(request.message):
            return ChatResponse(reply=_off_topic(arabic), sources=[])

        filters = extract_filters(request.message, self.retriever.known_cities)
        filters = _follow_up_filters(filters, request, self.retriever)
        cache_key: CacheKey | None = None
        if not request.history:
            normalized = re.sub(r"[^\w\s]", " ", request.message.casefold())
            cache_key = (" ".join(normalized.split()), filters)
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        query = request.message
        if filters.city and filters.city.casefold() not in query.casefold():
            query += f" {filters.city}"
        limit = max(self.settings.top_k, 3) if filters.price_sort else self.settings.top_k
        results = self.retriever.search(query, limit, filters)
        results = _city_project_results(results, filters.city, query)
        if not results:
            return ChatResponse(reply=_no_match(arabic), sources=[])

        quoted = QUOTED_NAME.findall(request.message)
        if quoted and not any(
            phrase.casefold() in result.document.text.casefold()
            for phrase in quoted
            for result in results
        ):
            return ChatResponse(reply=_unknown_name(quoted[0], arabic), sources=[])

        if filters.price_sort and all(
            result.document.source == "wasalt" and result.document.metadata.get("type") == "listing"
            for result in results
        ):
            answer = append_listing_details("", results, filters, arabic)
            response = ChatResponse(reply=answer, sources=_source_list(results, answer))
            if cache_key is not None:
                self.cache.set(cache_key, response)
            return response

        history = request.history[-self.settings.max_history_messages :]
        messages: list[LLMMessage] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": "Context:\n" + _context(results)},
            *({"role": item.role, "content": item.content} for item in history),
            {"role": "user", "content": request.message},
        ]
        answer = _normalize_citations(await self.llm_client.complete(messages))
        answer = _exact_prices(answer, results)
        answer = append_listing_details(answer, results, filters, arabic)
        response = ChatResponse(reply=answer, sources=_source_list(results, answer))
        if cache_key is not None:
            self.cache.set(cache_key, response)
        return response
