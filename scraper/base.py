import asyncio
import gzip
from abc import ABC, abstractmethod
from time import monotonic
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.schemas.document import Document

USER_AGENT = "PropLensBot/0.1 (technical assignment)"


class SiteBlockedError(Exception):
    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"{url}: {reason}")


def is_challenge(response: httpx.Response) -> bool:
    if response.headers.get("cf-mitigated") == "challenge":
        return True
    body = response.content[:8000].decode("utf-8", errors="ignore").lower()
    return (
        "_incapsula_resource" in body
        or "just a moment..." in body
        and "challenges.cloudflare.com" in body
    )


class BaseScraper(ABC):
    def __init__(self, delay_s: float = 1.25, timeout_s: float = 20.0, retries: int = 3) -> None:
        self.delay_s = delay_s
        self.retries = min(retries, 3)
        self.client = httpx.AsyncClient(
            timeout=timeout_s,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        self._robots: dict[str, RobotFileParser] = {}
        self._last_request = 0.0
        self.pages_fetched = 0
        self.records_skipped = 0
        self.errors: list[str] = []
        self.blocked_reason: str | None = None

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, url: str) -> httpx.Response:
        for attempt in range(self.retries + 1):
            wait_s = self.delay_s - (monotonic() - self._last_request)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            self._last_request = monotonic()
            try:
                response = await self.client.get(url)
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == self.retries:
                    raise
            else:
                if response.status_code in (403, 429) or is_challenge(response):
                    raise SiteBlockedError(url, f"HTTP {response.status_code} or bot challenge")
                if response.status_code < 500:
                    response.raise_for_status()
                    return response
                if attempt == self.retries:
                    response.raise_for_status()
            await asyncio.sleep(2**attempt)
        raise RuntimeError("Request retries exhausted")

    async def _robots_for(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            robots_url = f"{origin}/robots.txt"
            try:
                response = await self._request(robots_url)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                parser = RobotFileParser()
                parser.parse([])
            else:
                if "html" in response.headers.get("content-type", "").lower():
                    raise SiteBlockedError(robots_url, "robots.txt returned HTML, not robots rules")
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
            self._robots[origin] = parser
        return self._robots[origin]

    async def sitemap_urls(self, url: str) -> list[str]:
        parser = await self._robots_for(url)
        return parser.site_maps() or []

    async def fetch(self, url: str) -> str:
        parser = await self._robots_for(url)
        if not parser.can_fetch(USER_AGENT, url):
            raise PermissionError(f"robots.txt disallows {url}")
        response = await self._request(url)
        self.pages_fetched += 1
        content = response.content
        if content.startswith(b"\x1f\x8b"):
            content = gzip.decompress(content)
        return content.decode(response.encoding or "utf-8", errors="replace")

    @abstractmethod
    async def scrape(self) -> list[Document]: ...
