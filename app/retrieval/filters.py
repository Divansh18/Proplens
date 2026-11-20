import re
from dataclasses import dataclass
from typing import Literal

from app.schemas.document import Document, PropertySource

PROPERTY_TYPES = (
    "apartment",
    "villa",
    "townhouse",
    "penthouse",
    "mansion",
    "studio",
    "room",
    "floor",
    "building",
    "land",
    "plot",
)
BEDROOMS = re.compile(r"\b(\d+)\s*(?:-\s*)?(?:bedrooms?|beds?|br)\b", re.IGNORECASE)
MAX_PRICE = re.compile(
    r"\b(?:under|below|less than|up to|max(?:imum)?)\s*"
    r"(?:SAR|AED|USD|£|\$)?\s*(\d[\d,]*(?:\.\d+)?)\s*([mk])?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryFilters:
    city: str | None = None
    bedrooms: int | None = None
    property_type: str | None = None
    purpose: Literal["sale", "rent"] | None = None
    max_price: float | None = None
    source: PropertySource | None = None
    price_sort: Literal["asc", "desc"] | None = None


def mentioned_source(query: str) -> PropertySource | None:
    dar = bool(re.search(r"\bdar\s*global\b", query, re.IGNORECASE))
    wasalt = bool(re.search(r"\bwasalt\b", query, re.IGNORECASE))
    if dar and not wasalt:
        return "darglobal"
    if wasalt and not dar:
        return "wasalt"
    return None


def extract_filters(query: str, known_cities: frozenset[str]) -> QueryFilters:
    lowered = query.casefold()
    city = next(
        (
            candidate
            for candidate in sorted(known_cities, key=len, reverse=True)
            if re.search(rf"(?<!\w){re.escape(candidate.casefold())}(?!\w)", lowered)
        ),
        None,
    )
    bedroom_match = BEDROOMS.search(query)
    property_type = next(
        (kind for kind in PROPERTY_TYPES if re.search(rf"\b{kind}s?\b", lowered)), None
    )
    purpose: Literal["sale", "rent"] | None = None
    if re.search(r"\b(rent|rental|leasing|lease)\b", lowered):
        purpose = "rent"
    elif re.search(r"\b(sale|buy|purchase)\b", lowered):
        purpose = "sale"
    price_match = MAX_PRICE.search(query)
    max_price = None
    if price_match:
        max_price = float(price_match.group(1).replace(",", ""))
        max_price *= {"m": 1_000_000, "k": 1_000}.get((price_match.group(2) or "").lower(), 1)
    price_sort: Literal["asc", "desc"] | None = None
    if re.search(r"\b(cheapest|lowest|least expensive)\b", lowered):
        price_sort = "asc"
    elif re.search(r"\b(most expensive|priciest|highest price)\b", lowered):
        price_sort = "desc"
    return QueryFilters(
        city=city,
        bedrooms=int(bedroom_match.group(1)) if bedroom_match else None,
        property_type=property_type,
        purpose=purpose,
        max_price=max_price,
        source=mentioned_source(query),
        price_sort=price_sort,
    )


def numeric_price(value: object) -> float | None:
    if value is None:
        return None
    match = re.search(r"\d[\d,]*(?:\.\d+)?", str(value))
    return float(match.group().replace(",", "")) if match else None


def matches_filters(document: Document, filters: QueryFilters) -> bool:
    metadata = document.metadata
    if filters.source and document.source != filters.source:
        return False
    if filters.city:
        searchable = " ".join(
            (str(metadata.get("city", "")), str(metadata.get("projects", "")), document.text)
        ).casefold()
        if filters.city.casefold() not in searchable:
            return False
    if filters.bedrooms is not None:
        bedrooms = str(metadata.get("bedrooms", ""))
        if not re.search(rf"\b{filters.bedrooms}\b", bedrooms):
            return False
    if filters.property_type:
        searchable = f"{metadata.get('property_type', '')} {document.text}".casefold()
        if filters.property_type not in searchable:
            return False
    if filters.purpose and metadata.get("purpose") != filters.purpose:
        return False
    if filters.max_price is not None:
        price = numeric_price(metadata.get("price"))
        if price is None or price > filters.max_price:
            return False
    return True
