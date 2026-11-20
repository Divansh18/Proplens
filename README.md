# PropLens

An AI property assistant for publicly available DarGlobal and Wasalt project information.

## Architecture

```text
DarGlobal / Wasalt public pages
          ↓
       scraper
          ↓
   data/ JSON files
          ↓
    BM25 retriever
          ↓
     ChatService ──→ OpenRouter
          ↓
      FastAPI chat page
```

The retriever and LLM client are interfaces, so their implementations can be replaced without changing the chat route. The deployed app will read committed JSON data and will not scrape at runtime.

## Local setup

Python 3.11 is required.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
make run
```

Open <http://localhost:8000>. The current chat reply is a placeholder. Retrieval and OpenRouter integration are planned for step 3. Add an OpenRouter API key to `.env` when the LLM integration is implemented.

## Data collection

The scrapers check `robots.txt` and stop when a site serves a bot challenge. DarGlobal's main site uses Imperva protection; PropLens does not bypass it. The DarGlobal snapshot uses [official issuer announcements](https://www.londonstockexchange.com/en/news/article/DAR/dar-global-half-year-2026-results/17802155) published by the London Stock Exchange. You can also import public DarGlobal pages saved in your normal browser using the instructions in [data/raw/darglobal/README.md](data/raw/darglobal/README.md). Wasalt listings come from English URLs in its public sitemap. Both JSON files are snapshots to commit with the repository; the deployed app does not scrape at runtime.

```bash
python -m scraper.run --source all --limit 150
python -m scraper.run --source darglobal --from-html data/raw/darglobal/
```

The scraper writes `data/darglobal.json` and `data/wasalt.json` atomically. See [scraper notes](scraper/NOTES.md) for source details and access limits.

```bash
make lint
make test
```
