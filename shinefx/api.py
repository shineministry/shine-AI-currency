import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import APP_NAME, __version__
from .config import settings
from .db import Database
from .fetcher import fetch_live, to_observations
from .models import (
    ConvertRequest,
    ConvertResponse,
    Health,
    IngestResult,
    LiveRates,
    QueryRequest,
    RagAnswer,
    RateHistory,
)
from .rag import answer_question, convert, index_observations
from .vectors import OllamaClient

db = Database()


def ingest_once() -> IngestResult:
    try:
        payload = fetch_live()
        observations = to_observations(payload)
        stored = db.store_observations(observations)
        indexed = index_observations(db)
        db.mark_source_ok(payload["source"])
        return IngestResult(
            ok=True,
            source=payload["source"],
            fetched=len(payload["rates"]),
            stored=stored,
            indexed=indexed,
            timestamp=payload["timestamp"],
        )
    except Exception as exc:  # noqa: BLE001
        db.mark_source_error(settings.fetch_source, str(exc))
        return IngestResult(
            ok=False,
            source=settings.fetch_source,
            fetched=0,
            stored=0,
            indexed=0,
            timestamp=int(time.time()),
            error=str(exc),
        )


def _background_loop() -> None:
    interval = max(settings.fetch_interval_min, 1) * 60
    while True:
        time.sleep(interval)
        ingest_once()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_ingest:
        thread = threading.Thread(target=_background_loop, daemon=True)
        thread.start()
    yield


app = FastAPI(
    title=f"{APP_NAME} Currency Intelligence",
    description=(
        f"{APP_NAME} is a self-hosted RAG/AI engine that fetches live exchange rates, "
        "indexes them into its own knowledge base, and answers currency questions "
        "with a local Ollama model."
    ),
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"app": APP_NAME, "version": __version__, "docs": "/docs"}


@app.get("/api/health", response_model=Health, tags=["meta"])
def health() -> Health:
    client = OllamaClient()
    return Health(
        app=APP_NAME,
        version=__version__,
        ollama_up=client.is_up(),
        embed_model=settings.embed_model if client.is_up() else None,
        chat_model=settings.chat_model if client.is_up() else None,
        observations=db.count_observations(),
        documents=db.count_documents(),
        last_ingest=db.source_status().get(settings.fetch_source, {}).get("last_success"),
    )


@app.get("/api/config", tags=["meta"])
def config() -> dict:
    return settings.to_dict()


@app.post("/api/ingest", response_model=IngestResult, tags=["tracking"])
def ingest() -> IngestResult:
    return ingest_once()


@app.get("/api/rates/live", response_model=LiveRates, tags=["tracking"])
def live_rates(base: str = Query(default=settings.base_currency)) -> LiveRates:
    rates = db.latest_rates(base.upper())
    if not rates:
        raise HTTPException(status_code=404, detail="no rates yet. POST /api/ingest or run `python -m shinefx.cli seed`")
    timestamp = db.latest_timestamp(base.upper()) or int(time.time())
    source = "shinefx-tracker"
    return LiveRates(base=base.upper(), source=source, timestamp=timestamp, rates=rates)


@app.get("/api/rates/history", response_model=RateHistory, tags=["tracking"])
def rate_history(
    base: str = Query(default=settings.base_currency),
    quote: str = Query(...),
    days: int = Query(default=7, ge=1, le=365),
) -> RateHistory:
    points = db.history(base.upper(), quote.upper(), days)
    if not points:
        raise HTTPException(status_code=404, detail=f"no history for {base.upper()}/{quote.upper()}")
    return RateHistory(base=base.upper(), quote=quote.upper(), source="shinefx-tracker", points=points)


@app.post("/api/convert", response_model=ConvertResponse, tags=["tracking"])
def convert_currency(req: ConvertRequest) -> ConvertResponse:
    try:
        result = convert(db, req.amount, req.from_currency, req.to_currency)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ConvertResponse(**result)


@app.post("/api/ai/query", response_model=RagAnswer, tags=["ai"])
def ai_query(req: QueryRequest) -> RagAnswer:
    return answer_question(db, req.question)


@app.get("/api/ai/context", tags=["ai"])
def ai_context(q: str = Query(...), top_k: int = Query(default=5, ge=1, le=20)):
    from .rag import retrieve

    return {"question": q, "retrieved": [s.model_dump() for s in retrieve(db, q, top_k=top_k)]}
