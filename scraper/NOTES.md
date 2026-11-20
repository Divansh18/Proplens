# Scraper reconnaissance (20 November 2026)

## DarGlobal

- `www.darglobal.co.uk/robots.txt` and the apex `darglobal.co.uk/robots.txt` returned Imperva/Incapsula challenge HTML during reconnaissance. A later ordinary run briefly reached the main site's sitemap, then its first project URL (`/aida-360`) returned a challenge. The crawler stopped that host immediately; it did not solve or evade the challenge.
- `darglobal.com/robots.txt` redirected to `dar.io`, an unrelated DAR Group site, so it was excluded. `cdn.darglobal.co.uk/robots.txt` returned 404, but a publicly indexed DarGlobal interim report PDF on the CDN returned HTTP 403 Cloudflare challenge; we stopped that host. The UK FCA's `data.fca.org.uk/robots.txt` allowed the public filing path and one DarGlobal filing PDF returned HTTP 200; it was not needed because the issuer-announcement HTML below was more directly parseable.
- `www.londonstockexchange.com/robots.txt` allows the public DarGlobal issuer-announcement paths. The [2026 half-year results](https://www.londonstockexchange.com/en/news/article/DAR/dar-global-half-year-2026-results/17802155) and [2025 full-year results](https://www.londonstockexchange.com/en/news/article/DAR/full-year-results/c246-7b-5a-3d-03-4ec7bf) both returned HTTP 200 without a challenge. Their raw HTML embeds the issuer-authored article body in `articleBody`. The scraper extracts 20 named projects with locations and descriptions from the half-year announcement into one portfolio Document, plus a company overview Document from the full-year announcement. Both Documents cite the real announcement URLs.
- Browser-saved public project pages can be imported without network requests. The importer recovers canonical/`og:url`, uses JSON-LD, `__NEXT_DATA__`, meta tags and visible content where present, strips navigation/scripts/footer, and caps each page's text at 4,000 characters. The [manual page list](../data/raw/darglobal/README.md) contains 18 recommended URLs. Saved HTML files are gitignored; the normalized JSON snapshot is committed.

## Wasalt

- `https://wasalt.sa/robots.txt` was readable. Its default rules allow `/` but disallow `/search` and `/cdn-cgi/rum`. The scraper never visits those paths.
- Robots lists English sitemaps on `cdn.wasalt.sa`. The CDN's own `robots.txt` returned 404. The English product sitemap at `/sitemap/product_sitemap_en_sa.xml.gz` returned **uncompressed XML despite the `.gz` suffix**, with 60,000 `/en/property/sale/...` and `/en/property/rent/...` URLs (45,389 sale and 14,611 rent at inspection time).
- `https://wasalt.sa/sitemap.xml` and one linked English listing initially returned HTTP 403 Cloudflare challenges via a plain curl request. We stopped that reconnaissance attempt. A later ordinary run with the same declared user agent returned HTTP 200 for English listing pages; no challenge solving, proxy, or user-agent rotation was used.
- Accessible listing HTML contains both JSON-LD and `__NEXT_DATA__`. The scraper uses `props.pageProps.propertyDetailsV3.propertyInfo` and its `attributes` for title, city, district, subtype, sale/rent price, currency, area, bedrooms, and description. JSON-LD fills any gaps. Bathrooms are kept only when actually shown.
- Sitemap slugs sometimes omit decimal points in area values. A listing page's structured area takes precedence. If listing pages become blocked during a run, the fallback records retain only the URL-confirmed listing ID, purpose, and property type, tagged `data_source: sitemap_url`; area and bedroom numbers from slugs are not asserted as facts.
- The verified run saved 150 unique listing-page records. All 150 have city, district, and price; 146 have area, 136 have bedrooms, and 1 has a bathroom count. Missing fields are omitted rather than guessed.

## Limits and use

- Run `python -m scraper.run --source all --limit 150`. The runner checks robots before every host, applies a 1.25 second request interval, stops on bot challenges, and atomically saves whatever public facts it already collected.
- No login, browser challenge solving, proxy, or user-agent rotation is used. DarGlobal currently prevents extraction from this environment. Wasalt may intermittently challenge requests; stop if that happens and use the partial data transparently.
