import hashlib
import html
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from app.schemas.document import Document, PropertySource


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return " ".join(html.unescape(text).split())


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def stable_id(source: PropertySource, url: str) -> str:
    digest = hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()[:16]
    return f"{source}-{digest}"


def dedupe_documents(documents: list[Document]) -> list[Document]:
    seen: set[str] = set()
    result: list[Document] = []
    for document in documents:
        url = canonical_url(document.url)
        if url in seen or not document.title.strip() or not document.text.strip():
            continue
        seen.add(url)
        result.append(document)
    return result


def parse_sitemap(xml: str) -> tuple[list[str], list[str]]:
    root = ElementTree.fromstring(xml)
    kind = root.tag.rsplit("}", 1)[-1]
    urls = [
        clean_text(item.text)
        for item in root.iter()
        if item.tag.rsplit("}", 1)[-1] == "loc" and item.text
    ]
    if kind == "sitemapindex":
        return [], urls
    if kind == "urlset":
        return urls, []
    raise ValueError(f"Unsupported sitemap root: {kind}")


def next_data(soup: BeautifulSoup) -> dict[str, Any]:
    script = soup.select_one("script#__NEXT_DATA__")
    if not script:
        return {}
    try:
        payload = json.loads(script.string or script.get_text())
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def structured_objects(soup: BeautifulSoup, include_next: bool = True) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    selector = 'script[type="application/ld+json"]'
    if include_next:
        selector += ", script#__NEXT_DATA__"
    for script in soup.select(selector):
        try:
            payload = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        stack = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                objects.append(current)
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)
    return objects


def first_string(objects: list[dict[str, Any]], *keys: str) -> str:
    for obj in objects:
        for key in keys:
            value = obj.get(key)
            if isinstance(value, (str, int, float)) and clean_text(value):
                return clean_text(value)
    return ""


def meta_content(soup: BeautifulSoup, key: str) -> str:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return clean_text(tag.get("content")) if tag else ""


def first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""
