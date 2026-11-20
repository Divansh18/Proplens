import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any

from app.core.config import Settings
from app.core.errors import PropLensError
from app.llm.base import LLMClient, LLMMessage
from app.retrieval.base import Retriever, SearchResult
from app.retrieval.filters import QueryFilters, extract_filters, is_list_query, matches_filters
from app.schemas.chat import ChatRequest, ChatResponse, Source
from app.schemas.document import Document
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
    "the numbered context markers [1], [2], and so on. Cite each bullet only with the "
    "one or two sources that support it; never use more than two citations per bullet. "
    "Never add a Citations: or Sources: list in the reply; the UI shows sources. "
    "For example: '- D-Villas is in Dubai [1]' and "
    "'- Urban Oasis is on Dubai Canal [2]'. Do not cite unrelated sources or a number "
    "that is not in the context. For list questions, include every matching project in "
    "the context."
)
ARABIC = re.compile(r"[\u0600-\u06ff]")
OFF_TOPIC = re.compile(
    r"\b(weather|forecast|temperature|sports|recipe|joke|movie)\b|الطقس|الجو", re.I
)
FOLLOW_UP = re.compile(r"^(what about|how about|and |those|these|any )", re.I)
QUOTED_NAME = re.compile(r'["“]([^"”]{3,80})["”]')
PRICE = re.compile(r"\b([A-Z]{3})\s+(\d[\d,]*(?:\.\d+)?)\b")
HEARTBEAT_INTERVAL_S = 15
logger = logging.getLogger(__name__)


def _no_match(arabic: bool, filters: QueryFilters | None = None) -> str:
    if filters and filters.strict and filters.property_type:
        place = f" in {filters.city}" if filters.city else ""
        source = f" on {filters.source.title()}" if filters.source else ""
        if arabic:
            return (
                f"لا أجد إعلانات {filters.property_type} مطابقة{place}{source} في البيانات الحالية."
            )
        return (
            f"I couldn't find matching {filters.property_type} listings{place}{source} "
            "in the current data."
        )
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
    if re.search(r"(?:I (?:don't|do not) have (?:that )?information|لا أملك معلومات)", reply, re.I):
        return []
    cited = {int(number) for number in re.findall(r"\[(\d+)\]", _normalize_citations(reply))}
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


def _clean_reply(reply: str) -> str:
    lines = _normalize_citations(reply).rstrip().splitlines()
    while lines and re.match(r"^\s*(?:Citations|Sources):", lines[-1], re.I):
        lines.pop()

    def keep_two(match: re.Match[str]) -> str:
        return "".join(re.findall(r"\[\d+\]", match.group())[:2])

    return "\n".join(re.sub(r"(?:\[\d+\][ \t]*){3,}", keep_two, line) for line in lines).rstrip()


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
    changed_type = bool(
        current.property_type
        and previous.property_type
        and current.property_type != previous.property_type
    )
    return replace(
        current,
        city=current.city or previous.city,
        bedrooms=(
            current.bedrooms
            if current.bedrooms is not None
            else None
            if changed_type
            else previous.bedrooms
        ),
        property_type=current.property_type or previous.property_type,
        purpose=current.purpose or previous.purpose,
        max_price=current.max_price if current.max_price is not None else previous.max_price,
        source=current.source or previous.source,
        price_sort=current.price_sort or previous.price_sort,
        strict=True,
    )


@dataclass
class ChatPlan:
    response: ChatResponse | None
    results: list[SearchResult]
    filters: QueryFilters
    cache_key: CacheKey | None
    messages: list[LLMMessage]
    arabic: bool


def _project_list(results: list[SearchResult], city: str | None) -> str:
    projects = [
        (
            index,
            _project_name(result.document),
            str(result.document.metadata.get("city", "")),
        )
        for index, result in enumerate(results, start=1)
        if result.document.source == "darglobal"
        and result.document.metadata.get("type") == "project"
    ]
    portfolios = [
        (index, result.document.metadata["projects"])
        for index, result in enumerate(results, start=1)
        if isinstance(result.document.metadata.get("projects"), list)
    ]
    if city is None and portfolios:
        index, portfolio = portfolios[0]
        lines = [
            f"- {project['name']} — {project.get('location', 'location not stated')} [{index}]"
            for project in portfolio
            if isinstance(project, dict) and project.get("name")
        ]
        return "\n".join(["DarGlobal projects:", *lines])
    ignored = {"the", "by", "at", "in", "of", "dar", "global", "darglobal", "dubai", "jeddah"}

    def tokens(value: str) -> set[str]:
        return {word for word in re.findall(r"[a-z0-9]+", value.casefold()) if word not in ignored}

    direct_names = [(tokens(title), location.casefold()) for _, title, location in projects]
    for index, portfolio in portfolios:
        for project in portfolio:
            if not isinstance(project, dict):
                continue
            name = str(project.get("name", "")).strip()
            location = str(project.get("location", ""))
            if not name or (city and location.casefold() != city.casefold()):
                continue
            name_tokens = tokens(name)
            if not any(
                location.casefold() == known_location
                and len(name_tokens & known) >= min(2, len(name_tokens))
                for known, known_location in direct_names
            ):
                projects.append((index, name, location))
                direct_names.append((name_tokens, location.casefold()))
    heading = f"DarGlobal projects in {city}:" if city else "DarGlobal projects:"
    return "\n".join([heading, *(f"- {title} [{index}]" for index, title, _ in projects)])


def _project_name(document: Document) -> str:
    name = str(document.metadata.get("name") or document.title).strip()
    seo = re.match(r"^Apartments in ([^,]+), .+? - ([^-]+?) by DarGlobal$", name, re.I)
    if seo:
        return f"{seo.group(2).strip()}, {seo.group(1).strip()}"
    name = re.sub(r"\s+[|-]\s+DarGlobal$", "", name, flags=re.I)
    return name.split(" | ", 1)[0].strip()


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
        plan = self._prepare(request)
        if plan.response is not None:
            return plan.response
        answer = _clean_reply(await self.llm_client.complete(plan.messages))
        answer = _exact_prices(answer, plan.results)
        answer = append_listing_details(answer, plan.results, plan.filters, plan.arabic)
        return self._finish(answer, plan)

    def _finish(self, answer: str, plan: ChatPlan) -> ChatResponse:
        response = ChatResponse(reply=answer, sources=_source_list(plan.results, answer))
        if plan.cache_key is not None:
            self.cache.set(plan.cache_key, response)
        return response

    def _prepare(self, request: ChatRequest) -> ChatPlan:
        arabic = bool(ARABIC.search(request.message))
        empty = ChatPlan(None, [], QueryFilters(), None, [], arabic)
        if OFF_TOPIC.search(request.message):
            empty.response = ChatResponse(reply=_off_topic(arabic), sources=[])
            return empty

        filters = extract_filters(request.message, self.retriever.known_cities)
        filters = _follow_up_filters(filters, request, self.retriever)
        cache_key: CacheKey | None = None
        if not request.history:
            normalized = re.sub(r"[^\w\s]", " ", request.message.casefold())
            cache_key = (" ".join(normalized.split()), filters)
            cached = self.cache.get(cache_key)
            if cached is not None:
                empty.response = cached
                return empty
        query = request.message
        if filters.city and filters.city.casefold() not in query.casefold():
            query += f" {filters.city}"
        if filters.strict and filters.property_type:
            query += f" {filters.property_type}"
        limit = max(self.settings.top_k, 10) if is_list_query(query) else self.settings.top_k
        if filters.price_sort:
            limit = max(limit, 3)
        results = self.retriever.search(query, limit, filters)
        if filters.strict:
            results = [result for result in results if matches_filters(result.document, filters)]
        results = _city_project_results(results, filters.city, query)
        plan = ChatPlan(None, results, filters, cache_key, [], arabic)
        if not results:
            plan.response = ChatResponse(reply=_no_match(arabic, filters), sources=[])
            return plan

        quoted = QUOTED_NAME.findall(request.message)
        if quoted and not any(
            phrase.casefold() in result.document.text.casefold()
            for phrase in quoted
            for result in results
        ):
            plan.response = ChatResponse(reply=_unknown_name(quoted[0], arabic), sources=[])
            return plan

        if all(
            result.document.source == "wasalt" and result.document.metadata.get("type") == "listing"
            for result in results
        ):
            answer = append_listing_details("", results, filters, arabic, show_all=True)
            plan.response = self._finish(answer, plan)
            return plan

        if (
            is_list_query(request.message)
            and all(result.document.source == "darglobal" for result in results)
            and any(result.document.metadata.get("type") == "project" for result in results)
        ):
            plan.response = self._finish(_project_list(results, filters.city), plan)
            return plan

        history = request.history[-self.settings.max_history_messages :]
        plan.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": "Context:\n" + _context(results)},
            *({"role": item.role, "content": item.content} for item in history),
            {"role": "user", "content": request.message},
        ]
        return plan

    async def stream(self, request: ChatRequest) -> AsyncIterator[dict[str, Any] | None]:
        try:
            plan = self._prepare(request)
        except PropLensError as exc:
            yield {"type": "error", "message": exc.public_message}
            yield {"type": "done"}
            return
        except Exception:
            logger.exception("Failed to prepare chat stream")
            yield {"type": "error", "message": "An unexpected error occurred."}
            yield {"type": "done"}
            return
        if plan.response is not None:
            yield {"type": "token", "text": plan.response.reply}
            yield {"type": "sources", "sources": [s.model_dump() for s in plan.response.sources]}
            yield {"type": "done"}
            return

        chunks: list[str] = []
        iterator = self.llm_client.stream(plan.messages)
        try:
            while True:
                next_token = asyncio.create_task(anext(iterator))
                try:
                    while not next_token.done():
                        done, _ = await asyncio.wait({next_token}, timeout=HEARTBEAT_INTERVAL_S)
                        if not done and not chunks:
                            yield None
                    token = next_token.result()
                except StopAsyncIteration:
                    break
                finally:
                    if not next_token.done():
                        next_token.cancel()
                        with suppress(asyncio.CancelledError):
                            await next_token
                chunks.append(token)
                yield {"type": "token", "text": token}
        except PropLensError as exc:
            yield {"type": "error", "message": exc.public_message}
            yield {"type": "done"}
            return
        except Exception:
            logger.exception("Chat stream failed")
            yield {"type": "error", "message": "The assistant is temporarily unavailable."}
            yield {"type": "done"}
            return
        finally:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()

        answer = "".join(chunks)
        if not answer:
            yield {"type": "error", "message": "The assistant is temporarily unavailable."}
            yield {"type": "done"}
            return
        # The browser cleans streamed display text; cache the same final reply.
        cleaned = _clean_reply(answer)
        completed = append_listing_details(cleaned, plan.results, plan.filters, plan.arabic)
        if completed.startswith(cleaned) and len(completed) > len(cleaned):
            suffix = completed[len(cleaned) :]
            yield {"type": "token", "text": suffix}
        response = self._finish(completed, plan)
        yield {"type": "sources", "sources": [s.model_dump() for s in response.sources]}
        yield {"type": "done"}
