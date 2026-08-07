import os

import pytest

os.environ["SHINEFX_AUTO_INGEST"] = "false"
os.environ["SHINEFX_DATA_DIR"] = os.path.join(os.path.dirname(__file__), "..", "data-test")

from fastapi.testclient import TestClient  # noqa: E402

from shinefx.api import app, db  # noqa: E402

client = TestClient(app)


def test_root():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["app"] == "ShineFX"


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "ollama_up" in body
    assert body["observations"] >= 0


def test_ingest_and_live_rates():
    ingest = client.post("/api/ingest")
    assert ingest.status_code == 200
    body = ingest.json()
    assert body["ok"] is True
    assert body["stored"] > 0

    live = client.get("/api/rates/live", params={"base": "EUR"})
    assert live.status_code == 200
    rates = live.json()["rates"]
    assert "USD" in rates
    assert rates["USD"] > 0


def test_convert():
    resp = client.post("/api/convert", json={"amount": 100, "from_currency": "EUR", "to_currency": "USD"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["converted"] == pytest.approx(100 * body["rate"])


def test_history():
    resp = client.get("/api/rates/history", params={"base": "EUR", "quote": "USD"})
    assert resp.status_code == 200
    points = resp.json()["points"]
    assert len(points) > 0
    assert "rate" in points[0]


def test_ai_query_works_offline():
    resp = client.post("/api/ai/query", json={"question": "how many dollars for 100 euros?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["engine"] in {"shinefx-rag", "shinefx-deterministic"}
    assert body["answer"]


def test_ai_context():
    resp = client.get("/api/ai/context", params={"q": "euro dollar rate", "top_k": 3})
    assert resp.status_code == 200
    assert "retrieved" in resp.json()
