# ShineFX — Currency Intelligence RAG/AI

Your own named RAG/AI engine for tracking live currency. No third-party currency
API. ShineFX periodically fetches live exchange rates, stores every observation,
indexes them into its own vector knowledge base, and answers currency questions
through a local AI model (Ollama).

## How it works

```
Live rate fetcher  ──►  SQLite store (rate observations)  ──►  Vector index (embeddings)
(ECB feed / web                │                                       │
 scraping)                     ▼                                       ▼
                        /api/rates/*                          RAG retriever
                                                                     │
                                                                     ▼
                                                      Local LLM (Ollama) ──► answer
```

- **Track** — fetches rates from a public feed (ECB daily reference rates by
  default) or scrapes Google Finance quote pages, on a schedule (`/api/ingest`
  or the background loop).
- **Store** — every fetch is kept in SQLite (`data/shinefx.db`) as a time-series
  of observations, so live rates and history are always available.
- **RAG** — observations are turned into currency report documents, embedded,
  and stored in a self-built vector store (no external vector DB).
- **Answer** — your question is embedded, the top matching reports are retrieved,
  and a local Ollama model answers using only that retrieved data. If Ollama is
  not installed it degrades to a deterministic converter so the API still works.

## Setup

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional but recommended — local AI (free, offline):

1. Install Ollama from https://ollama.com
2. Pull the models:
   ```powershell
   ollama pull llama3.2        # chat
   ollama pull nomic-embed-text # embeddings
   ```

Configuration via environment variables (copy `.env.example` values):

| Variable | Default | Purpose |
|---|---|---|
| `SHINEFX_DATA_DIR` | `data` | where the DB lives |
| `SHINEFX_OLLAMA_URL` | `http://localhost:11434` | Ollama server |
| `SHINEFX_EMBED_MODEL` | `nomic-embed-text` | embedding model |
| `SHINEFX_CHAT_MODEL` | `llama3.2` | chat model |
| `SHINEFX_BASE_CURRENCY` | `EUR` | base currency for tracking |
| `SHINEFX_FETCH_SOURCE` | `ecb` | `ecb` or `google` (web scraping) |
| `SHINEFX_FETCH_INTERVAL_MIN` | `60` | live-tracking interval |
| `SHINEFX_AUTO_INGEST` | `true` | background live tracking on server start |

## Usage

```powershell
# fetch live rates and index them into the RAG store
python -m shinefx.cli seed

# ask the RAG/AI engine
python -m shinefx.cli query "how many dollars for 100 euros?"
python -m shinefx.cli query "trend of USD to INR this week" -v

# engine status
python -m shinefx.cli status

# run the API server (default http://127.0.0.1:8000)
python run.py
# or
python -m shinefx.cli serve
```

## API

Interactive docs at http://127.0.0.1:8000/docs

| Endpoint | Description |
|---|---|
| `GET  /api/health` | engine + Ollama status |
| `GET  /api/rates/live?base=EUR` | latest tracked rates |
| `GET  /api/rates/history?base=EUR&quote=USD&days=7` | rate history |
| `POST /api/ingest` | fetch + index now (live tracking) |
| `POST /api/convert` | `{amount, from_currency, to_currency}` |
| `POST /api/ai/query` | `{question}` — RAG/AI answer |
| `GET  /api/ai/context?q=...` | inspect what the retriever finds |

Example:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/ai/query -Method Post -ContentType "application/json" `
  -Body '{"question":"how many dollars for 100 euros?"}'
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Deploy to GitHub Pages (currency.shine-ministry.com)

GitHub Pages can't run Python, so the site is built as **static files** and the
RAG runs entirely in the browser (same hashing-embedding engine, bit-identical
results). A GitHub Actions workflow fetches rates hourly, appends them to the
committed history, and deploys `docs/` to the `gh-pages` branch.

1. Create a repo for the site and push this folder to it:
   ```powershell
   git init
   git add .
   git commit -m "ShineFX"
   gh repo create currency-shine-ministry --public --source=. --push
   ```
2. Enable Pages: repo **Settings → Pages → Source: Deploy from a branch →
   branch `gh-pages` / root** → Save.
3. Set the custom domain: Settings → Pages → Custom domain →
   `currency.shine-ministry.com` → Save (GitHub will validate via the CNAME below).
4. In your DNS provider for `shine-ministry.com`, add:
   ```
   CNAME  currency  ->  <your-github-username>.github.io
   ```
   Wait for DNS to propagate (GitHub shows the green lock when done).
5. Run the workflow once manually (Actions → Build & Deploy ShineFX site →
   Run workflow). After that it auto-runs every hour at :17.

The hourly workflow fetches rates (ECB feed), appends to `docs/data/history.json`
for the history chart, regenerates the RAG context (`docs/data/context.json`),
commits the new data, and redeploys the site.

## Notes

- The "live" data ultimately comes from a public feed (ECB reference rates) or
  scraped quote pages; no paid/third-party currency API is used. You can point
  `SHINEFX_FETCH_SOURCE=google` to exercise the web-scraping path.
- All tracking, storage, retrieval and reasoning is your own engine — the only
  external dependency is a local, free Ollama model for embeddings/chat.
- `data/` holds the local SQLite DB (API mode) and is gitignored; the static
  site data lives in `docs/data/*.json` and IS committed.
