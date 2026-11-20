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

## Refresh public data

```bash
python -m scraper.run --source all --limit 150
```

The scraper writes `data/darglobal.json` and `data/wasalt.json` atomically. It follows each host's robots rules and stops on bot challenges. See [scraper notes](scraper/NOTES.md) for the current access limits and source fields. The app reads committed JSON files and never scrapes at runtime.

```bash
make lint
make test
```
