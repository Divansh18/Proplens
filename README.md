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

Open <http://localhost:8000>. The current chat reply is a placeholder. Scraping is planned for step 2; retrieval and OpenRouter integration are planned for step 3. Add an OpenRouter API key to `.env` when the LLM integration is implemented.

```bash
make lint
make test
```
