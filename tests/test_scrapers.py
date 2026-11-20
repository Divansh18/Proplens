import json
from pathlib import Path

import httpx
import pytest

from app.schemas.document import Document
from scraper.base import USER_AGENT, BaseScraper, SiteBlockedError, is_challenge
from scraper.darglobal import (
    DarGlobalScraper,
    build_project_document,
    import_saved_html,
    original_page_url,
    parse_project_page,
)
from scraper.official import (
    COMPANY_URL,
    PORTFOLIO_URL,
    build_company_document,
    build_portfolio_document,
    parse_issuer_announcement,
)
from scraper.parsing import dedupe_documents, parse_sitemap
from scraper.run import run_source, write_documents
from scraper.wasalt import build_listing_document, parse_listing_page, parse_listing_slug

FIXTURES = Path(__file__).parent / "fixtures"


def test_real_challenge_pages_are_not_parsed_as_properties() -> None:
    dar_html = (FIXTURES / "darglobal_blocked.html").read_text()
    wasalt_html = (FIXTURES / "wasalt_blocked.html").read_text()
    listing_url = (
        "https://wasalt.sa/en/property/sale/villa-333-sqm-facing-east-on-20m-width-street-5841671"
    )

    assert is_challenge(httpx.Response(200, text=dar_html))
    assert is_challenge(httpx.Response(403, text=wasalt_html))
    assert parse_project_page(dar_html) == {}
    assert parse_listing_page(wasalt_html, listing_url) == {}


def test_wasalt_real_sitemap_sample_builds_partial_records() -> None:
    urls, children = parse_sitemap((FIXTURES / "wasalt_sitemap.xml").read_text())

    assert children == []
    assert len(urls) == 2
    sale = parse_listing_slug(urls[0])
    rent = parse_listing_slug(urls[1])
    assert sale["purpose"] == "sale"
    assert sale["property_type"] == "Villa"
    assert sale["area_sqm"] == "333"
    assert rent["purpose"] == "rent"
    assert rent["bedrooms"] == "4"

    document = build_listing_document(sale, urls[0], "sitemap_url")
    assert document is not None
    assert "Villa for sale" in document.text
    assert document.metadata["data_source"] == "sitemap_url"
    assert "area_sqm" not in document.metadata
    assert "price" not in document.metadata
    assert dedupe_documents([document, document.model_copy(update={"url": urls[0] + "/"})]) == [
        document
    ]


def test_darglobal_json_ld_parser_and_summary() -> None:
    html = """
    <main><h1>The Example Residences</h1></main>
    <script type="application/ld+json">{
      "@type": "Residence", "description": "Apartments by the waterfront.",
      "address": {"addressLocality": "Dubai", "addressCountry": "UAE"},
      "propertyTypes": ["Apartment", "Penthouse"], "numberOfBedrooms": "1-3",
      "offers": {"priceCurrency": "AED", "price": "1,500,000"},
      "amenityFeature": [{"@type": "LocationFeatureSpecification", "name": "Pool"}]
    }</script>
    """
    fields = parse_project_page(html)
    document = build_project_document(fields, "https://www.darglobal.co.uk/example")

    assert fields["city"] == "Dubai"
    assert fields["country"] == "UAE"
    assert fields["starting_price"] == "AED 1,500,000"
    assert fields["amenities"] == ["Pool"]
    assert document is not None
    assert "DarGlobal project The Example Residences in Dubai, UAE" in document.text
    assert "Starting price: AED 1,500,000" in document.text


def test_wasalt_json_ld_parser_and_atomic_output(tmp_path: Path) -> None:
    url = "https://wasalt.sa/en/property/sale/villa-333-sqm-facing-east-on-20m-width-street-5841671"
    html = """
    <main><h1>Villa for sale</h1></main>
    <script type="application/ld+json">{
      "@type": "Product", "description": "A villa near a park.",
      "address": {"addressLocality": "Riyadh", "addressRegion": "Al Malqa"},
      "offers": {"priceCurrency": "SAR", "price": "2,000,000"},
      "numberOfBedrooms": 4, "numberOfBathrooms": 3
    }</script>
    """
    fields = parse_listing_page(html, url)
    document = build_listing_document(fields, url)
    assert document is not None
    assert fields["city"] == "Riyadh"
    assert fields["district"] == "Al Malqa"
    assert fields["price"] == "SAR 2,000,000"
    assert fields["bathrooms"] == "3"
    assert "Price: SAR 2,000,000" in document.text

    output = tmp_path / "wasalt.json"
    write_documents(output, [document])
    assert json.loads(output.read_text())[0]["id"] == document.id
    assert list(tmp_path.iterdir()) == [output]


def test_wasalt_real_next_data_sample_uses_exact_property_fields() -> None:
    url = "https://wasalt.sa/en/property/sale/apartment-675-sqm-with-3-bedrooms-5879365"
    payload = json.loads((FIXTURES / "wasalt_listing.json").read_text())
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'

    fields = parse_listing_page(html, url)

    assert fields["city"] == "Jeddah"
    assert fields["district"] == "Al Rabbwah"
    assert fields["property_type"] == "Apartment"
    assert fields["price"] == "SAR 340000"
    assert fields["area_sqm"] == "675"
    assert fields["bedrooms"] == "3"


@pytest.mark.asyncio
async def test_fetch_respects_robots_and_stops_on_first_block() -> None:
    requested: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        assert request.headers["User-Agent"] == USER_AGENT
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /search\n")
        return httpx.Response(403, text="Blocked")

    class TestScraper(BaseScraper):
        async def scrape(self) -> list[Document]:
            return []

    scraper = TestScraper(delay_s=0)
    await scraper.client.aclose()
    scraper.client = httpx.AsyncClient(
        transport=httpx.MockTransport(respond), headers={"User-Agent": USER_AGENT}
    )
    try:
        with pytest.raises(PermissionError):
            await scraper.fetch("https://example.com/search")
        with pytest.raises(SiteBlockedError):
            await scraper.fetch("https://example.com/en/property")
    finally:
        await scraper.close()
    assert requested == ["/robots.txt", "/en/property"]


def test_official_issuer_excerpt_extracts_projects_and_company() -> None:
    html = (FIXTURES / "darglobal_issuer_excerpt.html").read_text()
    parsed = parse_issuer_announcement(html)

    assert [project["name"] for project in parsed["projects"]] == ["Trump Tower", "DG1"]
    assert all(project["location"] == "Dubai" for project in parsed["projects"])
    assert "London Stock Exchange" in parsed["company_overview"]
    portfolio = build_portfolio_document(parsed, PORTFOLIO_URL)
    company = build_company_document(parsed, COMPANY_URL)
    assert portfolio is not None
    assert company is not None
    assert "Trump International Hotel & Tower Dubai" in portfolio.text
    assert company.metadata["type"] == "company"


@pytest.mark.asyncio
async def test_saved_html_import_uses_original_url_and_merges_official_data(tmp_path: Path) -> None:
    saved = (FIXTURES / "darglobal_saved_project.html").read_text()
    (tmp_path / "astera.html").write_text(saved)
    (tmp_path / "duplicate.htm").write_text(saved)
    assert original_page_url(saved) == "https://darglobal.co.uk/the-astera"
    assert (
        original_page_url('<meta property="og:url" content="https://darglobal.co.uk/dg1">')
        == "https://darglobal.co.uk/dg1"
    )

    imported, skipped, errors = import_saved_html(tmp_path)
    assert len(imported) == 1
    assert skipped == 1
    assert errors == []
    assert imported[0].title == "The Astera"
    assert imported[0].metadata["data_source"] == "browser_saved_html"
    assert "Beachfront residences" in imported[0].text
    assert "Residents can enjoy beach access" in imported[0].text
    assert "Navigation text" not in imported[0].text
    assert "Footer text" not in imported[0].text
    assert len(imported[0].text) <= 4000

    data_dir = tmp_path / "data"
    official = build_company_document(
        {"company_overview": "Dar Global PLC develops luxury real estate."}, COMPANY_URL
    )
    assert official is not None
    write_documents(data_dir / "darglobal.json", [official])
    await run_source("darglobal", 150, data_dir, from_html=tmp_path)
    rows = json.loads((data_dir / "darglobal.json").read_text())
    assert len(rows) == 2
    assert {row["metadata"]["data_source"] for row in rows} == {
        "official_issuer_announcement",
        "browser_saved_html",
    }


@pytest.mark.asyncio
async def test_darglobal_falls_back_to_official_issuer_pages_after_challenge() -> None:
    challenge = (FIXTURES / "darglobal_blocked.html").read_text()
    report = (FIXTURES / "darglobal_issuer_excerpt.html").read_text()
    requested: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host == "www.darglobal.co.uk":
            return httpx.Response(200, text=challenge, headers={"content-type": "text/html"})
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, text=report)

    scraper = DarGlobalScraper()
    scraper.delay_s = 0
    await scraper.client.aclose()
    scraper.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        documents = await scraper.scrape()
    finally:
        await scraper.close()

    assert len(documents) == 2
    assert {document.metadata["type"] for document in documents} == {"portfolio", "company"}
    assert scraper.blocked_reason is not None
    assert requested[0] == "https://www.darglobal.co.uk/robots.txt"
    assert all("darglobal.co.uk" not in url for url in requested[1:])
