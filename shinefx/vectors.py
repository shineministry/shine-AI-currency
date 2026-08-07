import math
import re
import threading
import time

import httpx

from .config import settings

_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_FNV_MASK = (1 << 64) - 1

CURRENCY_WORDS = {
    "usd": "USD", "dollar": "USD", "dollars": "USD",
    "eur": "EUR", "euro": "EUR", "euros": "EUR",
    "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "sterling": "GBP",
    "inr": "INR", "rupee": "INR", "rupees": "INR",
    "jpy": "JPY", "yen": "JPY",
    "aud": "AUD",
    "cad": "CAD",
    "chf": "CHF", "franc": "CHF",
    "cny": "CNY", "yuan": "CNY", "renminbi": "CNY",
    "hkd": "HKD",
    "nzd": "NZD",
    "sek": "SEK",
    "nok": "NOK",
    "dkk": "DKK",
    "pln": "PLN", "zloty": "PLN",
    "try": "TRY", "lira": "TRY",
    "rub": "RUB", "ruble": "RUB", "rouble": "RUB",
    "zar": "ZAR", "rand": "ZAR",
    "brl": "BRL", "real": "BRL",
    "mxn": "MXN", "peso": "MXN",
    "sgd": "SGD",
}


def _tokenize(text: str) -> list[str]:
    lowered = text.lower()
    words = re.findall(r"[a-z0-9]{2,}", lowered)
    return [CURRENCY_WORDS.get(w, w) for w in words]


def _fnv1a64(data: bytes) -> int:
    h = _FNV_OFFSET
    for b in data:
        h ^= b
        h = (h * _FNV_PRIME) & _FNV_MASK
    return h


def hashing_embedding(text: str, dim: int = 384) -> list[float]:
    vector = [0.0] * dim
    for word in _tokenize(text):
        h = _fnv1a64(word.encode("utf-8"))
        idx = h % dim
        vector[idx] += 1.0 if (h >> 63) == 0 else -1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class OllamaClient:
    def __init__(self, base_url: str | None = None, timeout: float = 60.0) -> None:
        self.base_url = (base_url or settings.ollama_url).rstrip("/")
        self.timeout = httpx.Timeout(connect=3.0, read=timeout, write=timeout, pool=3.0)

    def is_up(self) -> bool:
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def available_models(self) -> list[str]:
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=10.0)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except httpx.HTTPError:
            return []

    def embed(self, text: str, model: str | None = None) -> list[float] | None:
        model = model or settings.embed_model
        try:
            resp = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": model, "input": [text]},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                emb = data.get("embeddings") or []
                if emb:
                    return emb[0]
                if data.get("embedding"):
                    return data["embedding"]
            resp = httpx.post(
                f"{self.base_url}/api/embeddings",
                json={"model": model, "prompt": text},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            emb = resp.json().get("embedding")
            return emb or None
        except httpx.HTTPError:
            return None

    def chat(self, messages: list[dict], model: str | None = None) -> str | None:
        model = model or settings.chat_model
        try:
            resp = httpx.post(
                f"{self.base_url}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content")
        except httpx.HTTPError:
            return None


_probe_lock = threading.Lock()
_probe_cache = {"at": 0.0, "up": False}
_models_cache = {"at": 0.0, "models": []}


def ollama_available(ttl: float = 30.0) -> bool:
    now = time.monotonic()
    with _probe_lock:
        if now - _probe_cache["at"] < ttl:
            return _probe_cache["up"]
        client = OllamaClient()
        up = client.is_up()
        _probe_cache["at"] = now
        _probe_cache["up"] = up
        return up


def available_models(ttl: float = 60.0) -> list[str]:
    now = time.monotonic()
    with _probe_lock:
        if now - _models_cache["at"] < ttl:
            return _models_cache["models"]
        client = OllamaClient()
        models = client.available_models()
        _models_cache["at"] = now
        _models_cache["models"] = models
        return models


def model_available(model: str) -> bool:
    return any(
        name == model or name.startswith(model + ":") for name in available_models()
    )


def embed(text: str) -> tuple[list[float], bool]:
    if ollama_available() and model_available(settings.embed_model):
        client = OllamaClient()
        model_embedding = client.embed(text)
        if model_embedding:
            return model_embedding, True
    return hashing_embedding(text), False
