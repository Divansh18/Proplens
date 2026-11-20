import asyncio
from abc import ABC, abstractmethod
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.schemas.document import Document

USER_AGENT = "PropLens/1.0 (public property research; respectful crawler)"


class BaseScraper(ABC):
    def __init__(self, delay_s: float = 1.0, timeout_s: float = 15.0, retries: int = 2) -> None:
        self.delay_s = delay_s
        self.retries = retries
        self.client = httpx.AsyncClient(timeout=timeout_s, headers={"User-Agent": USER_AGENT})
        self._robots: dict[str, RobotFileParser] = {}

    async def close(self) -> None:
        await self.client.aclose()

    async def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            response = await self.client.get(f"{origin}/robots.txt")
            if response.status_code == 404:
                parser = RobotFileParser()
                parser.parse([])
            else:
                response.raise_for_status()
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
            self._robots[origin] = parser
        return self._robots[origin].can_fetch(USER_AGENT, url)

    async def fetch(self, url: str) -> str:
        if not await self._allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        for attempt in range(self.retries + 1):
            await asyncio.sleep(self.delay_s * (2**attempt))
            try:
                response = await self.client.get(url)
                response.raise_for_status()
                return response.text
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError):
                if attempt == self.retries:
                    raise
        raise RuntimeError("Fetch retries exhausted")

    @abstractmethod
    async def scrape(self) -> list[Document]: ...
