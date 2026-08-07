import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shinefx.config import settings
from shinefx.fetcher import fetch_ecb_history, fetch_google_history, fetch_google_quote, fetch_live, to_observations
from shinefx.vectors import hashing_embedding

GOOGLE_PAIRS = [
    "USD-EUR", "GBP-EUR", "INR-EUR", "JPY-EUR",
    "AUD-EUR", "CAD-EUR", "CHF-EUR", "CNY-EUR",
    "HKD-EUR", "SGD-EUR", "SEK-EUR", "NOK-EUR",
    "TRY-EUR", "ZAR-EUR", "BRL-EUR", "MXN-EUR",
    "THB-EUR", "PLN-EUR", "CZK-EUR", "HUF-EUR",
    "IDR-EUR", "PHP-EUR", "MYR-EUR", "RON-EUR",
    "DKK-EUR", "ISK-EUR", "KRW-EUR", "ILS-EUR",
    "NZD-EUR",
]

# Key pairs for Google Finance daily + intraday chart data (all major currencies)
GF_CHART_PAIRS = [
    "USD-EUR", "GBP-EUR", "INR-EUR", "JPY-EUR", "CHF-EUR", "CNY-EUR",
    "AUD-EUR", "CAD-EUR", "SGD-EUR", "HKD-EUR", "SEK-EUR", "NOK-EUR",
    "TRY-EUR", "ZAR-EUR", "BRL-EUR", "MXN-EUR", "THB-EUR", "PLN-EUR",
    "CZK-EUR", "HUF-EUR", "KRW-EUR", "ILS-EUR", "NZD-EUR", "DKK-EUR",
]


def _fetch_google_supplementary() -> dict:
    """Fetch rates from Google Finance as a secondary source.
    Returns a dict of {currency_code: rate_vs_EUR} for successful fetches."""
    rates = {}
    for pair in GOOGLE_PAIRS:
        from_code, to_code = pair.split("-")
        try:
            price = fetch_google_quote(pair)
            if price and price > 0:
                rates[from_code] = 1.0 / price
        except Exception:
            continue
    return rates


def _fetch_google_chart_data() -> dict:
    """Fetch daily + intraday chart data from Google Finance for key pairs.

    Returns {pair: {"daily": [{ts, price}], "intraday": [{ts, price}]}}.
    """
    gf_data = {}
    for pair in GF_CHART_PAIRS:
        try:
            hist = fetch_google_history(pair)
            if hist["daily"] or hist["intraday"]:
                gf_data[pair] = hist
        except Exception:
            continue
    return gf_data

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
DATA_DIR = DOCS_DIR / "data"
MAX_DAYS = 90
MAX_EVENTS = 2000
SPARK_POINTS = 30
BASE = settings.base_currency


def _load_existing() -> list[dict]:
    path = DATA_DIR / "history.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        events = data.get("events", [])
        if not isinstance(events, list):
            return []
        return events
    except (json.JSONDecodeError, OSError):
        return []


def _fmt_ts(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def _series(events: list[dict], quote: str) -> list[float]:
    points = []
    seen = set()
    for event in reversed(events):
        ts = event.get("ts", 0)
        if ts in seen:
            continue
        seen.add(ts)
        rate = event.get("rates", {}).get(quote)
        if rate:
            points.append(rate)
    points.reverse()
    return points


def _trim(events: list[dict]) -> list[dict]:
    cutoff = int(time.time()) - MAX_DAYS * 86400
    events = [e for e in events if e.get("ts", 0) >= cutoff]
    return events[-MAX_EVENTS:]


def _date_key(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _merge_by_day(*event_lists: list[dict]) -> list[dict]:
    by_day: dict[str, dict] = {}
    for events in event_lists:
        for ev in events:
            ts = ev.get("ts", 0)
            key = _date_key(ts)
            current = by_day.get(key)
            if current is None or ts > current.get("ts", 0):
                by_day[key] = ev
    return [by_day[k] for k in sorted(by_day)]


def build() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    payload = fetch_live()
    observations = to_observations(payload)
    ts = payload["timestamp"]
    source = payload["source"]

    rates = {o["quote"]: o["rate"] for o in observations}
    if BASE not in rates:
        rates[BASE] = 1.0

    google_rates = _fetch_google_supplementary()
    for code, rate in google_rates.items():
        if code not in rates and rate:
            rates[code] = rate
            source = "ecb+google"

    existing = _load_existing()
    live_event = {"ts": ts, "source": source, "rates": rates}
    try:
        historical = fetch_ecb_history()
    except Exception:
        historical = []
    events = _merge_by_day(existing, historical, [live_event])
    events = _trim(events)

    quotes = sorted({q for e in events for q in e.get("rates", {}) if q != BASE})

    trends = {}
    for quote in quotes:
        series = _series(events, quote)
        if not series:
            continue
        latest = series[-1]
        low = min(series)
        high = max(series)
        first = series[0]
        pct = (latest - first) / first * 100 if first else 0.0
        trend = "rising" if latest > first else ("falling" if latest < first else "flat")
        trends[quote] = {
            "latest": latest,
            "low": low,
            "high": high,
            "change_pct": round(pct, 6),
            "trend": trend,
            "n": len(series),
            "spark": [round(v, 6) for v in series[-SPARK_POINTS:]],
        }

    docs = []
    for quote, t in trends.items():
        content = (
            f"Currency report: 1 {BASE} = {t['latest']:.6f} {quote} as of {_fmt_ts(ts)} "
            f"(source {source}). Over the last {t['n']} recorded observations "
            f"({MAX_DAYS}d window) the rate ranged from {t['low']:.6f} to {t['high']:.6f} {quote}, "
            f"trend {t['trend']}, change {t['change_pct']:+.4f}%."
        )
        docs.append(
            {
                "content": content,
                "meta": {
                    "base": BASE,
                    "quote": quote,
                    "latest_rate": t["latest"],
                    "low": t["low"],
                    "high": t["high"],
                    "trend": t["trend"],
                    "pct_change": t["change_pct"],
                    "timestamp": ts,
                    "source": source,
                },
                "embedding": [round(v, 6) for v in hashing_embedding(content)],
            }
        )

    latest = {
        "base": BASE,
        "timestamp": ts,
        "source": source,
        "currencies": sorted(quotes),
        "rates": {q: rates[q] for q in quotes},
        "trends": trends,
        "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
    }

    (DATA_DIR / "latest.json").write_text(
        json.dumps(latest, indent=1), encoding="utf-8"
    )
    (DATA_DIR / "history.json").write_text(
        json.dumps({"events": events}, indent=1), encoding="utf-8"
    )
    (DATA_DIR / "context.json").write_text(
        json.dumps({"base": BASE, "docs": docs}, indent=1), encoding="utf-8"
    )
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    # Fetch Google Finance chart data (daily + intraday) for key pairs
    try:
        gf_data = _fetch_google_chart_data()
        (DATA_DIR / "gf_history.json").write_text(
            json.dumps(gf_data, indent=1), encoding="utf-8"
        )
        # Add Google Finance data to context docs for AI
        for pair, hist in gf_data.items():
            daily = hist.get("daily", [])
            if len(daily) < 2:
                continue
            from_code, to_code = pair.split("-")
            first_price = daily[0]["price"]
            last_price = daily[-1]["price"]
            # GF stores X per 1 EUR; convert to EUR/X
            first_rate = 1.0 / first_price if first_price else 0
            last_rate = 1.0 / last_price if last_price else 0
            pct = ((last_rate - first_rate) / first_rate * 100) if first_rate else 0
            trend = "rising" if pct > 0.05 else ("falling" if pct < -0.05 else "flat")
            gf_doc = (
                f"Google Finance data for {from_code}: 1 EUR = {last_rate:.6f} {from_code} "
                f"(source: Google Finance). Over {len(daily)} daily observations "
                f"the rate ranged from {min(1.0/d['price'] for d in daily if d['price']):.6f} to "
                f"{max(1.0/d['price'] for d in daily if d['price']):.6f} {from_code}, "
                f"trend {trend}, change {pct:+.4f}%."
            )
            docs.append({
                "content": gf_doc,
                "meta": {
                    "base": BASE,
                    "quote": from_code,
                    "latest_rate": last_rate,
                    "low": min(1.0/d["price"] for d in daily if d["price"]),
                    "high": max(1.0/d["price"] for d in daily if d["price"]),
                    "trend": trend,
                    "pct_change": round(pct, 6),
                    "timestamp": daily[-1]["ts"],
                    "source": "google_finance",
                },
                "embedding": [round(v, 6) for v in hashing_embedding(gf_doc)],
            })
        print(f"  Google Finance chart data: {len(gf_data)} pairs")
    except Exception as exc:
        print(f"  Google Finance chart fetch failed: {exc}")

    # Rewrite context.json with GF docs included
    (DATA_DIR / "context.json").write_text(
        json.dumps({"base": BASE, "docs": docs}, indent=1), encoding="utf-8"
    )

    print(f"OK: {len(quotes)} pairs, {len(events)} events, {len(docs)} context docs, ts={ts}, source={source}")


if __name__ == "__main__":
    build()
