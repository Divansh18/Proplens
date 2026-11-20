# Browser-saved DarGlobal pages

DarGlobal's main site challenges the automated crawler. In your normal browser, open a public page, choose **Save Page As → Webpage, HTML only** (Ctrl+S or Cmd+S), and save the `.html` file in this folder. Do not save challenge or login pages. Filenames do not matter; the importer reads each page's canonical or `og:url` tag.

Import the saved pages without making network requests:

```bash
python -m scraper.run --source darglobal --from-html data/raw/darglobal/
```

The importer skips pages with no official DarGlobal source URL, removes navigation and scripts, caps each page's text at 4,000 characters, and merges the result with the official issuer-announcement records. Only this README is eligible for version control from this folder; the saved HTML stays local.

## Suggested pages to save

Start with the projects listing and company overview, then save whichever individual projects you want the assistant to cover:

1. https://darglobal.co.uk/projects
2. https://darglobal.co.uk/about
3. https://darglobal.co.uk/trump-international-hotel-and-tower-dubai
4. https://darglobal.co.uk/d-villas-at-jge
5. https://darglobal.co.uk/the-astera
6. https://darglobal.co.uk/dg1
7. https://darglobal.co.uk/davinci-tower-by-pagani
8. https://darglobal.co.uk/urban-oasis-by-missoni
9. https://darglobal.co.uk/w-residences
10. https://darglobal.co.uk/tierra-viva
11. https://darglobal.co.uk/marea
12. https://darglobal.co.uk/les-vagues
13. https://darglobal.co.uk/lp/trump-international-qatar
14. https://darglobal.co.uk/landing-page/aida
15. https://darglobal.co.uk/the-mulliner
16. https://darglobal.co.uk/rayana/trump-mansions
17. https://darglobal.co.uk/neptune
18. https://darglobal.co.uk/trump-tower-jeddah
