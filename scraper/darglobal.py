import logging
import re
from typing import Any
from urllib.parse import urlsplit
from xml.etree.ElementTree import ParseError

import httpx
from bs4 import BeautifulSoup

from app.schemas.document import Document
from scraper.base import BaseScraper, SiteBlockedError
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


def parse_project_page(html: str) -> dict[str, Any]:
    if "_Incapsula_Resource" in html or "challenges.cloudflare.com" in html:
        return {}
    soup = BeautifulSoup(html, "lxml")
    objects = structured_objects(soup)
    heading = soup.find("h1")
    name = clean_text(heading.get_text(" ", strip=True)) if heading else ""
    name = name or first_string(objects, "name", "title") or meta_content(soup, "og:title")
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
    }


def build_project_document(fields: dict[str, Any], url: str) -> Document | None:
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
    metadata = {"type": "project"}
    metadata.update({key: value for key, value in fields.items() if value})
    return Document(
        id=stable_id("darglobal", url),
        source="darglobal",
        url=canonical_url(url),
        title=name,
        text=" ".join(sentences),
        metadata=metadata,
    )


def parse_company_page(html: str, url: str) -> Document | None:
    if "_Incapsula_Resource" in html or "challenges.cloudflare.com" in html:
        return None
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup
    heading = main.find("h1")
    title = clean_text(heading.get_text(" ", strip=True)) if heading else "DarGlobal"
    description = meta_content(soup, "description")
    if not description:
        paragraphs = [clean_text(p.get_text(" ", strip=True)) for p in main.find_all("p")[:4]]
        description = " ".join(part for part in paragraphs if part)[:1200]
    if not description:
        return None
    return Document(
        id=stable_id("darglobal", url),
        source="darglobal",
        url=canonical_url(url),
        title=title,
        text=f"DarGlobal company overview. {description}",
        metadata={"type": "company"},
    )


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
        unique = dedupe_documents(documents)
        self.records_skipped += len(documents) - len(unique)
        return unique
