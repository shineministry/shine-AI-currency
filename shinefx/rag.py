import re
import time
from datetime import datetime, timezone

from .config import settings
from .db import Database, cosine_similarity
from .models import RagAnswer, RagDocument
from .vectors import CURRENCY_WORDS, OllamaClient, embed, hashing_embedding, model_available


def _fmt_ts(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_documents(db: Database, hours: int = 48) -> list[dict]:
    base = settings.base_currency
    rows = db.latest_observation_window(base, hours=hours)
    by_pair: dict[str, list[dict]] = {}
    for row in rows:
        by_pair.setdefault(row["quote"], []).append(row)

    docs = []
    for quote, obs in by_pair.items():
        obs.sort(key=lambda r: r["timestamp"])
        latest = obs[-1]
        rate = latest["rate"]
        values = [r["rate"] for r in obs]
        low = min(values)
        high = max(values)
        trend = "rising" if values[-1] > values[0] else ("falling" if values[-1] < values[0] else "flat")
        pct = (values[-1] - values[0]) / values[0] * 100 if values[0] else 0.0
        content = (
            f"Currency report: 1 {base} = {rate:.6f} {quote} as of {_fmt_ts(latest['timestamp'])} "
            f"(source {latest['source']}). Over the last {len(values)} recorded observations "
            f"({hours}h window) the rate ranged from {low:.6f} to {high:.6f} {quote}, "
            f"trend {trend}, change {pct:+.4f}%."
        )
        meta = {
            "base": base,
            "quote": quote,
            "latest_rate": rate,
            "low": low,
            "high": high,
            "trend": trend,
            "pct_change": round(pct, 6),
            "timestamp": latest["timestamp"],
            "source": latest["source"],
        }
        docs.append({"content": content, "meta": meta})
    return docs


def index_observations(db: Database, hours: int = 48) -> int:
    docs = build_documents(db, hours=hours)
    if not docs:
        return 0
    db.clear_documents()
    indexed = 0
    for doc in docs:
        vector, _ = embed(doc["content"])
        db.add_document(doc["content"], vector, doc["meta"])
        indexed += 1
    return indexed


def retrieve(db: Database, query: str, top_k: int = 5) -> list[RagDocument]:
    query_vector, used_ollama = embed(query)
    results = []
    for doc in db.all_documents():
        stored = _load_embedding(doc["embedding"])
        score = cosine_similarity(query_vector, stored)
        results.append(RagDocument(id=doc["id"], content=doc["content"], meta=doc["meta"], score=score))
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]


def _load_embedding(raw: str) -> list[float]:
    import json

    return json.loads(raw)


def _parse_amount(text: str) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)", text.replace(",", ""))
    if not match:
        return None
    return float(match.group(1))


_CODE_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(CURRENCY_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _ordered_codes(text: str) -> list[str]:
    lower = text.lower()
    matches = [(m.start(), CURRENCY_WORDS[m.group(0)]) for m in _CODE_PATTERN.finditer(lower)]
    codes = []
    for _, code in matches:
        if code not in codes:
            codes.append(code)
    if len(matches) < 2:
        return codes

    if "how many" in lower and " for " in lower:
        for_idx = lower.index(" for ")
        before = [c for p, c in matches if p < for_idx]
        after = [c for p, c in matches if p > for_idx]
        if before and after:
            return [after[0], before[0]]

    to_positions = [m.start() for m in re.finditer(r"\bto\b", lower)]
    if to_positions:
        to_idx = to_positions[0]
        before = [c for p, c in matches if p < to_idx]
        after = [c for p, c in matches if p > to_idx]
        if before and after:
            return [before[0], after[0]]

    return codes


def deterministic_answer(db: Database, query: str, sources: list[RagDocument]) -> RagAnswer:
    codes = _ordered_codes(query)
    rate = None
    base = None
    quote = None
    if len(codes) >= 2:
        first, second = codes[0], codes[1]
        latest = db.latest_rates(settings.base_currency)
        rate = _convert_rate(latest, first, second)
        base, quote = first, second
    elif len(codes) == 1:
        latest = db.latest_rates(settings.base_currency)
        code = codes[0]
        rate = _convert_rate(latest, settings.base_currency, code)
        base, quote = settings.base_currency, code

    if rate is not None:
        amount = _parse_amount(query)
        if amount is not None:
            answer = f"1 {base} = {rate:.6f} {quote}. {amount} {base} = {amount * rate:.4f} {quote}."
        else:
            answer = f"Latest recorded rate: 1 {base} = {rate:.6f} {quote}."
    else:
        snippets = [f"- {s.meta.get('base')}/{s.meta.get('quote')}: 1 {s.meta.get('base')} = {s.meta.get('latest_rate')}" for s in sources]
        context = "\n".join(snippets) if snippets else "No rate data indexed yet. Run `python -m shinefx.cli seed` first."
        answer = (
            f"I retrieved the following tracked currency data for your question:\n{context}\n"
            "Install Ollama to enable full conversational answers."
        )
    return RagAnswer(question=query, answer=answer, engine="shinefx-deterministic", used_ollama=False, sources=sources)


def _convert_rate(latest: dict[str, float], from_code: str, to_code: str) -> float | None:
    base = settings.base_currency
    if from_code == to_code:
        return 1.0
    if from_code == base and to_code in latest:
        return latest[to_code]
    if to_code == base and from_code in latest:
        return 1.0 / latest[from_code]
    if from_code in latest and to_code in latest:
        return latest[to_code] / latest[from_code]
    return None


def answer_question(db: Database, question: str, top_k: int = 5) -> RagAnswer:
    sources = retrieve(db, question, top_k=top_k)

    client = OllamaClient()
    if not client.is_up() or not model_available(settings.chat_model):
        return deterministic_answer(db, question, sources)

    context = "\n".join(f"Source {i + 1}: {s.content}" for i, s in enumerate(sources))
    messages = [
        {
            "role": "system",
            "content": (
                f"You are {settings.app_name}, a currency intelligence assistant. "
                "Answer using ONLY the retrieved currency data provided. "
                "If the data is insufficient, say so. Be concise and give exact numbers."
            ),
        },
        {
            "role": "user",
            "content": f"Retrieved currency data:\n{context or 'No data.'}\n\nQuestion: {question}",
        },
    ]
    content = client.chat(messages)
    if content is None:
        return deterministic_answer(db, question, sources)
    return RagAnswer(
        question=question,
        answer=content,
        engine="shinefx-rag",
        model=settings.chat_model,
        used_ollama=True,
        sources=sources,
    )


def convert(db: Database, amount: float, from_currency: str, to_currency: str) -> dict:
    from_code = from_currency.upper()
    to_code = to_currency.upper()
    latest = db.latest_rates(settings.base_currency)
    rate = _convert_rate(latest, from_code, to_code)
    if rate is None:
        raise LookupError(
            f"no tracked rate for {from_code}->{to_code}. Run `python -m shinefx.cli seed` to fetch live data."
        )
    timestamp = db.latest_timestamp(settings.base_currency) or int(time.time())
    return {
        "amount": amount,
        "from_currency": from_code,
        "to_currency": to_code,
        "rate": rate,
        "converted": amount * rate,
        "timestamp": timestamp,
        "source": "shinefx-tracker",
    }
