from typing import Any, Optional

from pydantic import BaseModel, Field


class RateObservation(BaseModel):
    base: str
    quote: str
    rate: float
    timestamp: int
    source: str


class LiveRates(BaseModel):
    base: str
    source: str
    timestamp: int
    rates: dict[str, float]


class RateHistory(BaseModel):
    base: str
    quote: str
    source: str
    points: list[dict[str, Any]]


class ConvertRequest(BaseModel):
    amount: float = Field(gt=0)
    from_currency: str
    to_currency: str


class ConvertResponse(BaseModel):
    amount: float
    from_currency: str
    to_currency: str
    rate: float
    converted: float
    timestamp: int
    source: str


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)


class RagDocument(BaseModel):
    id: int
    content: str
    meta: dict[str, Any]
    score: float


class RagAnswer(BaseModel):
    question: str
    answer: str
    engine: str
    model: Optional[str] = None
    used_ollama: bool
    sources: list[RagDocument] = []


class IngestResult(BaseModel):
    ok: bool
    source: str
    fetched: int
    stored: int
    indexed: int
    timestamp: int
    error: Optional[str] = None


class Health(BaseModel):
    app: str
    version: str
    ollama_up: bool
    embed_model: Optional[str] = None
    chat_model: Optional[str] = None
    observations: int
    documents: int
    last_ingest: Optional[int] = None
