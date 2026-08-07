import calendar
import re
import time
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .config import settings

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
ECB_HIST_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
GOOGLE_FINANCE_URL = "https://www.google.com/finance/quote/{pair}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _headers() -> dict[str, str]:
    return {"User-Agent": USER_AGENT, "Accept": "*/*"}


def fetch_ecb(timeout: float = 30.0) -> dict:
    resp = httpx.get(ECB_URL, headers=_headers(), timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.content)
    ns = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
    rates = {}
    for cube in root.findall(".//e:Cube[@currency]", ns):
        rates[cube.get("currency")] = float(cube.get("rate"))
    return rates


def fetch_ecb_history(timeout: float = 60.0) -> list[dict]:
    """Daily ECB reference rates over the last ~90 days."""
    resp = httpx.get(ECB_HIST_URL, headers=_headers(), timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.content)
    ns = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
    events = []
    for cube in root.findall(".//e:Cube[@time]", ns):
        ts = calendar.timegm(time.strptime(cube.get("time"), "%Y-%m-%d"))
        rates = {}
        for child in cube:
            if child.get("currency"):
                rates[child.get("currency")] = float(child.get("rate"))
        events.append({"ts": ts, "rates": rates})
    events.sort(key=lambda e: e["ts"])
    return events


def fetch_google_quote(pair: str, timeout: float = 30.0) -> float:
    code = pair.upper().replace("_", "-").replace("/", "-")
    url = GOOGLE_FINANCE_URL.format(pair=code)
    resp = httpx.get(url, headers=_headers(), timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    node = soup.find(attrs={"data-last-price": True})
    if node is None:
        raise ValueError(f"no price found for {pair} at {url}")
    value = node.get("data-last-price")
    if value is None:
        raise ValueError(f"missing data-last-price for {pair}")
    return float(str(value).replace(",", ""))


def _cross_rate(base: str, rates_vs_base: dict[str, float], quote: str) -> float | None:
    if quote == base:
        return 1.0
    if quote in rates_vs_base:
        return rates_vs_base[quote]
    base_rate = rates_vs_base.get(base)
    quote_rate = rates_vs_base.get(quote)
    if base_rate and quote_rate:
        return quote_rate / base_rate
    return None


def fetch_live(base: str | None = None, source: str | None = None) -> dict:
    base = (base or settings.base_currency).upper()
    source = source or settings.fetch_source

    if source == "ecb":
        rates = fetch_ecb()
        timestamp = int(time.time())
        return {"base": "EUR", "rates": rates, "timestamp": timestamp, "source": "ecb"}

    if source == "google":
        pairs = [
            "USD-EUR",
            "GBP-EUR",
            "INR-EUR",
            "JPY-EUR",
            "AUD-EUR",
            "CAD-EUR",
            "CHF-EUR",
            "CNY-EUR",
        ]
        rates = {}
        for pair in pairs:
            from_code, to_code = pair.split("-")
            try:
                price = fetch_google_quote(pair)
                rates[from_code] = 1.0 / price if price else None
                if rates[from_code]:
                    rates[to_code] = price
            except (httpx.HTTPError, ValueError):
                continue
        if not rates:
            raise RuntimeError("google finance scraping returned no usable quotes")
        return {
            "base": base,
            "rates": rates,
            "timestamp": int(time.time()),
            "source": "google",
        }

    raise ValueError(f"unknown fetch source: {source}")


def to_observations(payload: dict) -> list[dict]:
    base = payload["base"]
    raw = payload["rates"]
    observations = []
    for quote, rate in raw.items():
        if not rate:
            continue
        if base == "EUR":
            observations.append({"base": "EUR", "quote": quote, "rate": rate, "source": payload["source"]})
        else:
            converted = _cross_rate(base, raw, quote)
            if converted:
                observations.append({"base": base, "quote": quote, "rate": converted, "source": payload["source"]})
    return observations
