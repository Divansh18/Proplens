# Scraper reconnaissance (20 November 2026)

## DarGlobal

- `https://www.darglobal.co.uk/robots.txt` returned HTTP 200 with an Imperva/Incapsula challenge HTML page, not robots rules. It included `noindex,nofollow` and `/_Incapsula_Resource`.
- No trustworthy robots permissions or sitemap could be read from that host. We stopped there and did not request project or company pages. Indexed URLs suggest project pages can be root-level slugs and `/projects/...` collection pages, but direct page structure, JSON-LD, and `__NEXT_DATA__` could not be verified.
- The run writes `data/darglobal.json` as an empty list until the public site permits this crawler.

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
