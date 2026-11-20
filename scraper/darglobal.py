import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from xml.etree.ElementTree import ParseError

import httpx
from bs4 import BeautifulSoup

from app.schemas.document import Document
from scraper.base import BaseScraper, SiteBlockedError
from scraper.official import (
    COMPANY_URL,
    PORTFOLIO_URL,
    build_company_document,
    build_portfolio_document,
    parse_issuer_announcement,
)
from scraper.parsing import (
    canonical_url,
    clean_text,
    dedupe_documents,
    first_match,
    first_string,
    meta_content,
    parse_sitemap,
    stable_id,
    structured_objects,
)

logger = logging.getLogger(__name__)
BASE_URL = "https://www.darglobal.co.uk"
COMPANY_PATHS = ("/about", "/")
EXCLUDED_PREFIXES = (
    "/about",
    "/press",
    "/contact",
    "/investor",
    "/career",
    "/partner",
    "/projects/properties",
    "/ar/",
)


def _list_field(value: Any) -> list[str]:
    if isinstance(value, str):
        return [clean_text(part) for part in re.split(r"[,;]", value) if clean_text(part)]
    if isinstance(value, list):
        return [clean_text(item) for item in value if isinstance(item, str) and clean_text(item)]
    return []


def visible_main_text(soup: BeautifulSoup, max_chars: int = 4000) -> str:
    content = BeautifulSoup(str(soup), "lxml")
    for tag in content.select("nav, footer, header, script, style, noscript, form, aside"):
        tag.decompose()
    main = content.find("main") or content.find("article") or content.body or content
    return clean_text(main.get_text(" ", strip=True))[:max_chars].rstrip()


def original_page_url(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    canonical = soup.find("link", rel="canonical")
    url = clean_text(canonical.get("href")) if canonical else ""
    url = url or meta_content(soup, "og:url")
    if url.startswith("/"):
        url = urljoin("https://darglobal.co.uk", url)
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or parts.netloc.lower() not in {
        "darglobal.co.uk",
        "www.darglobal.co.uk",
    }:
        return None
    return canonical_url(url)


def parse_project_page(html: str) -> dict[str, Any]:
    if "_Incapsula_Resource" in html or "challenges.cloudflare.com" in html:
        return {}
    soup = BeautifulSoup(html, "lxml")
    objects = structured_objects(soup)
    heading = soup.find("h1")
    name = meta_content(soup, "og:title") or (
        clean_text(heading.get_text(" ", strip=True)) if heading else ""
    )
    name = name or first_string(objects, "name", "title")
    if not name and soup.title:
        name = clean_text(soup.title.get_text(" ", strip=True))
    name = re.sub(r"\s*\|\s*DarGlobal.*$", "", name, flags=re.IGNORECASE)
    if not name:
        return {}

    address = next((obj for obj in objects if "addressLocality" in obj), {})
    offers = next((obj for obj in objects if "price" in obj), {})
    price = clean_text(offers.get("price"))
    currency = clean_text(offers.get("priceCurrency"))
    starting_price = f"{currency} {price}".strip() if price else ""
    amenities = [
        clean_text(obj.get("name"))
        for obj in objects
        if obj.get("@type") == "LocationFeatureSpecification" and obj.get("name")
    ]
    main = soup.find("main") or soup
    page_text = clean_text(main.get_text(" ", strip=True))
    description = first_string(objects, "description") or meta_content(soup, "description")
    if not description:
        paragraph = main.find("p")
        description = clean_text(paragraph.get_text(" ", strip=True)) if paragraph else ""
    bedrooms = first_string(objects, "numberOfBedrooms", "bedrooms") or first_match(
        r"(\d+(?:\s*[-–]\s*\d+)?)\s*(?:bedrooms?|beds?)", page_text
    )
    property_types = []
    for obj in objects:
        property_types = _list_field(obj.get("propertyTypes") or obj.get("propertyType"))
        if property_types:
            break
    payment_plan = first_string(objects, "paymentPlan") or first_match(
        r"payment plan\s*[:\-]\s*([^.;]{5,100})", page_text
    )
    status = first_string(objects, "status", "availability")
    return {
        "name": name,
        "city": clean_text(address.get("addressLocality")),
        "country": clean_text(address.get("addressCountry")),
        "description": description,
        "property_types": property_types,
        "bedrooms": bedrooms,
        "starting_price": starting_price,
        "payment_plan": payment_plan,
        "amenities": amenities,
        "status": status,
        "visible_text": visible_main_text(soup),
    }


def build_project_document(
    fields: dict[str, Any], url: str, max_chars: int | None = None
) -> Document | None:
    name = clean_text(fields.get("name"))
    if not name:
        return None
    location = ", ".join(
        part for part in (clean_text(fields.get("city")), clean_text(fields.get("country"))) if part
    )
    sentences = [f"DarGlobal project {name}" + (f" in {location}." if location else ".")]
    for key, label in (
        ("description", ""),
        ("property_types", "Property types"),
        ("bedrooms", "Bedrooms"),
        ("starting_price", "Starting price"),
        ("payment_plan", "Payment plan"),
        ("amenities", "Amenities"),
        ("status", "Status"),
    ):
        value = fields.get(key)
        text = ", ".join(value) if isinstance(value, list) else clean_text(value)
        if text:
            sentences.append(f"{label}: {text}." if label else f"{text.rstrip('.')}.")
    visible = clean_text(fields.get("visible_text"))
    if visible and visible not in clean_text(fields.get("description")):
        sentences.append(visible)
    metadata = {"type": "project"}
    metadata.update(
        {key: value for key, value in fields.items() if value and key != "visible_text"}
    )
    text = " ".join(sentences)
    return Document(
        id=stable_id("darglobal", url),
        source="darglobal",
        url=canonical_url(url),
        title=name,
        text=text[:max_chars].rstrip() if max_chars else text,
        metadata=metadata,
    )


def parse_general_page(html: str, url: str, kind: str) -> Document | None:
    if "_Incapsula_Resource" in html or "challenges.cloudflare.com" in html:
        return None
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup
    heading = main.find("h1")
    title = meta_content(soup, "og:title") or (
        clean_text(heading.get_text(" ", strip=True)) if heading else ""
    )
    title = title or (clean_text(soup.title.get_text(" ", strip=True)) if soup.title else "")
    description = meta_content(soup, "description")
    visible = visible_main_text(soup)
    if not title or not description and not visible:
        return None
    text = " ".join(part for part in (description, visible) if part)[:4000].rstrip()
    return Document(
        id=stable_id("darglobal", url),
        source="darglobal",
        url=canonical_url(url),
        title=title,
        text=f"DarGlobal {kind}. {text}"[:4000].rstrip(),
        metadata={"type": kind},
    )


def parse_company_page(html: str, url: str) -> Document | None:
    return parse_general_page(html, url, "company")


def parse_collection_page(html: str, url: str) -> Document | None:
    return parse_general_page(html, url, "collection")


def import_saved_html(directory: Path, limit: int = 150) -> tuple[list[Document], int, list[str]]:
    documents: list[Document] = []
    errors: list[str] = []
    skipped = 0
    files = sorted(path for path in directory.iterdir() if path.suffix.lower() in {".html", ".htm"})
    for path in files[:limit]:
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
            url = original_page_url(html)
            if not url:
                skipped += 1
                errors.append(f"{path.name}: missing official canonical or og:url")
                continue
            page_path = urlsplit(url).path.rstrip("/")
            if page_path in {"", "/about"}:
                document = parse_company_page(html, url)
            elif page_path == "/projects" or page_path.startswith("/projects/"):
                document = parse_collection_page(html, url)
            else:
                document = build_project_document(parse_project_page(html), url, max_chars=4000)
            if document:
                document.metadata["data_source"] = "browser_saved_html"
                documents.append(document)
            else:
                skipped += 1
                errors.append(f"{path.name}: no usable page content")
        except (OSError, ValueError) as exc:
            skipped += 1
            errors.append(f"{path.name}: {exc}")
    unique = dedupe_documents(documents)
    skipped += len(documents) - len(unique)
    return unique, skipped, errors


def _is_project_url(url: str) -> bool:
    parts = urlsplit(url)
    if parts.netloc not in {"www.darglobal.co.uk", "darglobal.co.uk"}:
        return False
    path = parts.path.rstrip("/")
    return bool(path) and not any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


class DarGlobalScraper(BaseScraper):
    def __init__(self, limit: int = 100) -> None:
        super().__init__()
        self.limit = limit

    async def _discover_project_urls(self) -> list[str]:
        sitemap_urls = await self.sitemap_urls(BASE_URL)
        if not sitemap_urls:
            sitemap_urls = [f"{BASE_URL}/sitemap.xml"]
        project_urls: list[str] = []
        seen_sitemaps: set[str] = set()
        while sitemap_urls and len(seen_sitemaps) < 8:
            sitemap_url = sitemap_urls.pop(0)
            if sitemap_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap_url)
            try:
                urls, children = parse_sitemap(await self.fetch(sitemap_url))
            except SiteBlockedError:
                raise
            except (OSError, ValueError, PermissionError, httpx.HTTPError, ParseError) as exc:
                self.errors.append(f"{sitemap_url}: {exc}")
                continue
            project_urls.extend(url for url in urls if _is_project_url(url))
            sitemap_urls.extend(children)
        return list(dict.fromkeys(project_urls))[: self.limit]

    async def scrape(self) -> list[Document]:
        documents: list[Document] = []
        try:
            for url in await self._discover_project_urls():
                try:
                    fields = parse_project_page(await self.fetch(url))
                    document = build_project_document(fields, url)
                    if document:
                        documents.append(document)
                    else:
                        self.records_skipped += 1
                except SiteBlockedError:
                    raise
                except (OSError, ValueError, PermissionError, httpx.HTTPError) as exc:
                    self.errors.append(f"{url}: {exc}")
            for path in COMPANY_PATHS:
                url = f"{BASE_URL}{path}"
                try:
                    document = parse_company_page(await self.fetch(url), url)
                    if document:
                        documents.append(document)
                    else:
                        self.records_skipped += 1
                except SiteBlockedError:
                    raise
                except (OSError, ValueError, PermissionError, httpx.HTTPError) as exc:
                    self.errors.append(f"{url}: {exc}")
        except SiteBlockedError as exc:
            self.blocked_reason = str(exc)
            logger.warning("DarGlobal blocked the crawler: %s", exc)
        for url, builder in (
            (PORTFOLIO_URL, build_portfolio_document),
            (COMPANY_URL, build_company_document),
        ):
            try:
                parsed = parse_issuer_announcement(await self.fetch(url))
                document = builder(parsed, url)
                if document:
                    documents.append(document)
                else:
                    self.records_skipped += 1
            except SiteBlockedError as exc:
                self.blocked_reason = f"{self.blocked_reason or ''}; {exc}".strip("; ")
                logger.warning("Official issuer source blocked the crawler: %s", exc)
                break
            except (OSError, ValueError, PermissionError, httpx.HTTPError) as exc:
                self.errors.append(f"{url}: {exc}")
        unique = dedupe_documents(documents)
        self.records_skipped += len(documents) - len(unique)
        return unique
