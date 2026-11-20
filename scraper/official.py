import ast
import re
from typing import Any

from bs4 import BeautifulSoup

from app.schemas.document import Document
from scraper.parsing import clean_text, stable_id

PORTFOLIO_URL = (
    "https://www.londonstockexchange.com/en/news/article/DAR/"
    "dar-global-half-year-2026-results/17802155"
)
COMPANY_URL = (
    "https://www.londonstockexchange.com/en/news/article/DAR/"
    "full-year-results/c246-7b-5a-3d-03-4ec7bf"
)
ARTICLE_BODY = re.compile(r'var articleBody=("(?:\\.|[^"\\])*")', re.DOTALL)
REGION_HEADING = re.compile(r"Our projects? (?:in )?(.+)", re.IGNORECASE)
END_HEADINGS = (
    "Strong Balance Sheet",
    "Outlook",
    "Financial Review",
    "Cautionary statement",
    "Responsibility statement",
)


def project_location(region: str, name: str, description: str) -> str:
    details = f"{name} {description}".casefold()
    for city in ("Ras Al Khaimah", "Jeddah", "Riyadh"):
        if city.casefold() in details:
            return city
    return region


def extract_article_html(page_html: str) -> str:
    match = ARTICLE_BODY.search(page_html)
    if not match:
        return page_html
    try:
        return ast.literal_eval(match.group(1)).replace("\\/", "/")
    except (SyntaxError, ValueError):
        return ""


def parse_issuer_announcement(page_html: str) -> dict[str, Any]:
    article_html = extract_article_html(page_html)
    if not article_html:
        return {}
    soup = BeautifulSoup(article_html, "lxml")
    paragraphs = soup.find_all("p")
    region: str | None = None
    projects: list[dict[str, str]] = []
    company_parts: list[str] = []
    in_about = False

    for paragraph in paragraphs:
        text = clean_text(paragraph.get_text(" ", strip=True))
        if text == "About Dar Global":
            in_about = True
            continue
        if in_about and text:
            if len(company_parts) < 3 and len(text) > 80:
                company_parts.append(text)
            elif len(company_parts) >= 3:
                in_about = False

        match = REGION_HEADING.fullmatch(text)
        if match:
            region = clean_text(match.group(1))
            continue
        if region and text.startswith(END_HEADINGS):
            region = None
        if not region or len(text) < 120:
            continue
        first_span = paragraph.find("span")
        if first_span is None:
            continue
        name = clean_text(first_span.get_text(" ", strip=True))
        if not 3 <= len(name) <= 110 or not text.startswith(name):
            continue
        description = text[len(name) :].lstrip(" -–")
        if len(description) < 100:
            continue
        status_table = next(
            (
                sibling
                for sibling in paragraph.find_next_siblings(limit=6)
                if sibling.name == "table" and "Status" in sibling.get_text(" ", strip=True)
            ),
            None,
        )
        if status_table is None:
            continue
        table_text = clean_text(status_table.get_text(" ", strip=True))
        status_match = re.search(r"Status\s+(.+?)\s+Launched\b", table_text)
        project = {
            "name": name,
            "location": project_location(region, name, description),
            "description": description[:700],
        }
        if status_match:
            project["status"] = clean_text(status_match.group(1))
        projects.append(project)

    return {"projects": projects, "company_overview": " ".join(company_parts)}


def build_portfolio_document(parsed: dict[str, Any], url: str) -> Document | None:
    projects = parsed.get("projects") or []
    if not projects:
        return None
    summaries = [
        f"{project['name']} in {project['location']}. {project['description']}"
        for project in projects
    ]
    return Document(
        id=stable_id("darglobal", url),
        source="darglobal",
        url=url,
        title="DarGlobal project portfolio (H1 2026 issuer announcement)",
        text="DarGlobal project portfolio. " + " ".join(summaries),
        metadata={
            "type": "portfolio",
            "data_source": "official_issuer_announcement",
            "report_date": "2026-09-24",
            "projects": projects,
        },
    )


def build_company_document(parsed: dict[str, Any], url: str) -> Document | None:
    overview = clean_text(parsed.get("company_overview"))
    if not overview:
        return None
    return Document(
        id=stable_id("darglobal", url),
        source="darglobal",
        url=url,
        title="DarGlobal company overview (FY 2025 issuer announcement)",
        text=overview[:4000],
        metadata={
            "type": "company",
            "data_source": "official_issuer_announcement",
            "report_date": "2026-03-11",
        },
    )
