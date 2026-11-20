import logging
import re
from typing import Any
from urllib.parse import unquote, urlsplit
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
    next_data,
    parse_sitemap,
    stable_id,
    structured_objects,
)

logger = logging.getLogger(__name__)
BASE_URL = "https://wasalt.sa"
LISTING_PATH = re.compile(r"^/en/property/(sale|rent)/([^/]+)$")


def parse_listing_slug(url: str) -> dict[str, Any]:
    parts = urlsplit(url)
    if parts.netloc != "wasalt.sa":
        return {}
    match = LISTING_PATH.fullmatch(parts.path.rstrip("/"))
    if not match:
        return {}
    purpose, slug = match.groups()
    words = re.sub(r"-\d+$", "", unquote(slug)).replace("-", " ")
    title = clean_text(words).capitalize()
    if not title:
        return {}
    property_type = title.split(" ", 1)[0]
    area_match = re.search(r"(\d+(?:\.\d+)?)\s+sqm\b", words, re.IGNORECASE)
    bedrooms_match = re.search(r"(?:with\s+)?(\d+)\s+bedrooms?\b", words, re.IGNORECASE)
    return {
        "title": title,
        "purpose": purpose,
        "property_type": property_type,
        "area_sqm": area_match.group(1) if area_match else "",
        "bedrooms": bedrooms_match.group(1) if bedrooms_match else "",
    }


def parse_listing_page(html: str, url: str) -> dict[str, Any]:
    if "challenges.cloudflare.com" in html or "_Incapsula_Resource" in html:
        return {}
    fields = parse_listing_slug(url)
    if not fields:
        return {}
    soup = BeautifulSoup(html, "lxml")
    objects = structured_objects(soup, include_next=False)
    raw_details = next_data(soup).get("props", {}).get("pageProps", {}).get("propertyDetailsV3")
    details = raw_details if isinstance(raw_details, dict) else {}
    raw_info = details.get("propertyInfo")
    info = raw_info if isinstance(raw_info, dict) else {}
    if not soup.find("h1") and not objects and not info:
        return {}
    attributes = {
        item.get("key"): clean_text(item.get("value"))
        for item in (details.get("attributes") or [])
        if isinstance(item, dict) and item.get("key")
    }
    heading = soup.find("h1")
    fields["title"] = (
        (clean_text(heading.get_text(" ", strip=True)) if heading else "")
        or clean_text(info.get("title"))
        or meta_content(soup, "og:title")
        or fields["title"]
    )
    fields["description"] = (
        clean_text(info.get("description"))
        or first_string(objects, "description")
        or meta_content(soup, "description")
    )
    fields["purpose"] = clean_text(info.get("propertyFor")) or fields["purpose"]
    address = next((obj for obj in objects if "addressLocality" in obj), {})
    fields["city"] = clean_text(info.get("city")) or clean_text(address.get("addressLocality"))
    fields["district"] = clean_text(info.get("district")) or clean_text(
        address.get("streetAddress") or address.get("addressRegion")
    )
    fields["property_type"] = (
        clean_text(info.get("propertySubType"))
        or first_string(objects, "propertyType")
        or fields["property_type"]
    )
    offers = next((obj for obj in objects if "price" in obj), {})
    price = clean_text(
        info.get("salePrice") if fields["purpose"] == "sale" else info.get("expectedRent")
    ) or clean_text(offers.get("price"))
    currency = clean_text(info.get("currencyType")) or clean_text(offers.get("priceCurrency"))
    fields["price"] = f"{currency} {price}".strip() if price else ""
    fields["area_sqm"] = (
        attributes.get("builtUpArea")
        or first_match(r"(\d+(?:\.\d+)?)\s*SQM\b", fields["title"])
        or fields["area_sqm"]
    )
    fields["bedrooms"] = (
        attributes.get("noOfBedrooms")
        or first_string(objects, "numberOfBedrooms", "bedrooms")
        or fields["bedrooms"]
    )
    fields["bathrooms"] = attributes.get("noOfBathrooms") or first_string(
        objects, "numberOfBathrooms", "bathrooms"
    )
    return fields


def build_listing_document(
    fields: dict[str, Any], url: str, data_source: str = "listing_page"
) -> Document | None:
    if data_source == "sitemap_url":
        listing_id = urlsplit(url).path.rsplit("-", 1)[-1]
        property_type = clean_text(fields.get("property_type"))
        purpose = clean_text(fields.get("purpose"))
        if not property_type or not purpose or not listing_id.isdigit():
            return None
        fields = {
            "title": f"{property_type} for {purpose} (listing {listing_id})",
            "property_type": property_type,
            "purpose": purpose,
            "listing_id": listing_id,
        }
    title = clean_text(fields.get("title"))
    if not title:
        return None
    purpose = clean_text(fields.get("purpose"))
    sentences = [f"Wasalt {purpose} listing: {title}." if purpose else f"Wasalt listing: {title}."]
    for key, label in (
        ("city", "City"),
        ("district", "District"),
        ("property_type", "Property type"),
        ("price", "Price"),
        ("area_sqm", "Area"),
        ("bedrooms", "Bedrooms"),
        ("bathrooms", "Bathrooms"),
        ("description", ""),
    ):
        value = clean_text(fields.get(key))
        if value:
            if key == "area_sqm":
                value = f"{value} sqm"
            sentences.append(f"{label}: {value}." if label else f"{value.rstrip('.')}.")
    metadata = {"type": "listing", "data_source": data_source}
    metadata.update({key: value for key, value in fields.items() if value})
    return Document(
        id=stable_id("wasalt", url),
        source="wasalt",
        url=canonical_url(url),
        title=title,
        text=" ".join(sentences),
        metadata=metadata,
    )


class WasaltScraper(BaseScraper):
    def __init__(self, limit: int = 150) -> None:
        super().__init__()
        self.limit = min(max(limit, 1), 150)

    async def _listing_urls(self) -> list[str]:
        published = await self.sitemap_urls(BASE_URL)
        english = [url for url in published if "product_sitemap_en_sa" in url]
        candidates = english or [url for url in published if "rental_pdp_sitemap_en_sa" in url]
        if not candidates:
            self.errors.append("No English property sitemap was advertised in robots.txt")
            return []
        urls: list[str] = []
        for sitemap_url in candidates[:2]:
            try:
                entries, _children = parse_sitemap(await self.fetch(sitemap_url))
            except SiteBlockedError:
                raise
            except (OSError, ValueError, PermissionError, httpx.HTTPError, ParseError) as exc:
                self.errors.append(f"{sitemap_url}: {exc}")
                continue
            urls.extend(url for url in entries if parse_listing_slug(url))
            if len(urls) >= self.limit:
                break
        return list(dict.fromkeys(urls))[: self.limit]

    async def scrape(self) -> list[Document]:
        documents: list[Document] = []
        try:
            urls = await self._listing_urls()
            for url in urls:
                document = build_listing_document(parse_listing_slug(url), url, "sitemap_url")
                if document:
                    documents.append(document)
                else:
                    self.records_skipped += 1
            for index, url in enumerate(urls):
                try:
                    fields = parse_listing_page(await self.fetch(url), url)
                    full_document = build_listing_document(fields, url)
                    if full_document:
                        documents[index] = full_document
                    else:
                        self.records_skipped += 1
                except SiteBlockedError:
                    raise
                except (OSError, ValueError, PermissionError, httpx.HTTPError) as exc:
                    self.errors.append(f"{url}: {exc}")
        except SiteBlockedError as exc:
            self.blocked_reason = str(exc)
            logger.warning("Wasalt blocked listing pages: %s", exc)
        unique = dedupe_documents(documents)
        self.records_skipped += len(documents) - len(unique)
        return unique
