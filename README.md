# PropLens

An AI property assistant for publicly available DarGlobal and Wasalt project information.

## Architecture

```text
Public DarGlobal / Wasalt pages → offline scraper → committed data/*.json
                                                    ↓ startup validation + chunks
Browser → FastAPI → rule-based filters → BM25 retrieval → ChatService → OpenRouter
                     ↘ 1-hour answer cache                  ↓
                                           grounded reply + cited source links
```

The retriever and LLM client are interfaces, so their implementations can be replaced without changing the chat route. At startup, the app validates the committed JSON data, splits long records into overlapping sentence chunks, and builds a BM25 index. Rule-based metadata filters handle location, bedrooms, property type, purpose, and price before ranking. The deployed app reads the snapshot and does not scrape at runtime.

## Local setup

Python 3.11 is required.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
# Set OPENROUTER_API_KEY in .env
make run
```

Open <http://localhost:8000>. `GET /health` reports loaded document counts per source. The chat API is `POST /api/chat` with a `message` and optional `history`. Answers use the OpenRouter free model configured in `.env` and include links to cited records. `nvidia/nemotron-3.5-lightning:free` is the default model; set `OPENROUTER_FALLBACK_MODELS` to a comma-separated list of other free model IDs to change the fallback order. If the requested information is absent, the app gives a helpful no-match response without calling the model.

## Design decisions

- BM25 needs no torch, embedding model, or vector database, keeping startup and memory use suitable for a 512 MB free tier. Its interface can be replaced later.
- Rule-based filters handle city, bedrooms, property type, purpose, and price before ranking. Price comparisons use the listing's numeric price and format the best three options directly from structured data, saving an LLM call.
- The model receives only retrieved public text and is instructed to cite numbered blocks. Listing fields and links are appended from structured data so missing fields and exact prices are handled consistently.
- Free-model fallbacks handle unavailable models. A 200-entry, one-hour in-memory cache reduces repeated calls for questions without history. If all available models are busy, the API returns a friendly 503 response.
- Scrapers respect `robots.txt` and stop at bot protection. The deployed app reads the committed snapshot and never scrapes at request time.

## Data collection

The scrapers check `robots.txt` and stop when a site serves a bot challenge. DarGlobal's main site uses Imperva protection; PropLens does not bypass it. The DarGlobal snapshot uses [official issuer announcements](https://www.londonstockexchange.com/en/news/article/DAR/dar-global-half-year-2026-results/17802155) published by the London Stock Exchange. You can also import public DarGlobal pages saved in your normal browser using the instructions in [data/raw/darglobal/README.md](data/raw/darglobal/README.md). Wasalt listings come from English URLs in its public sitemap. Both JSON files are snapshots to commit with the repository; the deployed app does not scrape at runtime.

```bash
python -m scraper.run --source all --limit 150
python -m scraper.run --source darglobal --from-html data/raw/darglobal/
```

The scraper writes `data/darglobal.json` and `data/wasalt.json` atomically. See [scraper notes](scraper/NOTES.md) for source details and access limits.

## Run with Docker

Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`. The key is read at runtime; `.dockerignore` excludes `.env` from the image.

```bash
docker build -t proplens .
docker run --rm --env-file .env -p 8000:8000 proplens
# Or: docker compose up --build
```

Open <http://localhost:8000> or check <http://localhost:8000/health>. The container listens on `${PORT:-8000}` at `0.0.0.0`; its health check uses the same port.

## Deploy

### Render

1. Create a [Render Web Service](https://render.com/docs/web-services) from the repository and select the Docker runtime. Render builds the included `Dockerfile`.
2. In the service's [Environment settings](https://render.com/docs/configure-environment-variables), add `OPENROUTER_API_KEY` as a secret environment value. Add any model overrides as ordinary environment variables. Do not upload `.env` or pass the key as a Docker build argument.
3. Set the health check path to `/health`. The container binds to Render's `PORT` automatically.

### Hugging Face Spaces

1. Create a [Docker Space](https://huggingface.co/docs/hub/main/spaces-sdks-docker) and push the repository. Add this YAML block at the top of the Space's `README.md`:

   ```yaml
   ---
   title: PropLens
   sdk: docker
   app_port: 7860
   ---
   ```

2. In Space Settings, set `PORT=7860` as a variable and `OPENROUTER_API_KEY` as a secret. The same image serves the chat page on port 7860. Do not commit `.env`.

Model availability can change; check [OpenRouter's current model catalog](https://openrouter.ai/docs/api/api-reference/models/get-models) before changing the default or fallbacks.

## Checks

```bash
make lint
make test
```
