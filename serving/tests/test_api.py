import json
import sys
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app  # noqa: E402
from finsight.config import Config  # noqa: E402
from finsight.embedders import HashEmbedder  # noqa: E402
from finsight.graph import RAGPipeline  # noqa: E402
from finsight.ingestion.pipeline import ingest  # noqa: E402
from finsight.llm import FakeLLMProvider  # noqa: E402


@pytest.fixture
def client(tmp_path):
    pdf = fitz.open()
    for t in ["Cover page", "Item 7. MD&A\nNet sales were 5,000 million in 2023, up from 4,000 million."]:
        pdf.new_page().insert_textbox(fitz.Rect(40, 40, 550, 780), t, fontsize=11)
    pdf.save(tmp_path / "Acme_2023_10K.pdf")
    cfg = Config.model_validate({"name": "t", "index_dir": str(tmp_path / "i"), "parsed_dir": str(tmp_path / "p"),
                                 "embedder": {"name": "hash"}, "retrieval": {"mode": "hybrid", "top_k": 3}})
    emb = HashEmbedder(256)
    store = ingest(cfg, {"Acme_2023_10K": str(tmp_path / "Acme_2023_10K.pdf")}, emb)
    llm = FakeLLMProvider(
        reply="Net sales were 5,000 million [Acme_2023_10K:1]. Growth <calc>(5000-4000)/4000*100</calc>%.")
    with TestClient(create_app(lambda: RAGPipeline(cfg, store, emb, llm=llm))) as c:
        yield c


def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "ok" and r["documents"] == 1


def test_query_json(client):
    r = client.post("/v1/query", json={"question": "What were Acme net sales?", "stream": False}).json()
    assert r["citations"] == [{"doc_id": "Acme_2023_10K", "page": 1}]
    assert "= 25" in r["answer"] and r["guardrails_ok"] is True and not r["refused"]


def test_query_sse_stream(client):
    with client.stream("POST", "/v1/query", json={"question": "What were Acme net sales?"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    blocks = body.strip().split("\n\n")
    events = [b.split("\n")[0].removeprefix("event: ") for b in blocks]
    assert events[0] == "retrieval" and events[-1] == "final" and "token" in events
    final = blocks[-1].split("data: ", 1)[1]
    assert "= 25" in json.loads(final)["answer"]  # calculator ran before the final event


def test_retrieve_debug_and_validation(client):
    r = client.post("/v1/retrieve", json={"question": "net sales 2023"}).json()
    assert r["chunks"][0]["doc_id"] == "Acme_2023_10K" and "retrieve" in r["timings"]
    assert client.post("/v1/query", json={"question": "x"}).status_code == 422


def test_metrics_endpoint(client):
    client.post("/v1/query", json={"question": "What were Acme net sales?", "stream": False})
    assert "finsight_requests_total" in client.get("/metrics").text


def test_reload_swaps_pipeline(client):
    r = client.post("/v1/admin/reload").json()
    assert r["status"] == "reloaded" and r["documents"] == 1


def test_compare_endpoint_uses_agent(client):
    r = client.post("/v1/compare", json={"question": "Compare Acme sales 2023 versus 2022"})
    assert r.status_code == 200 and "= 25" in r.json()["answer"]


def test_reload_requires_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("SERVING_ADMIN_TOKEN", "s3cret")
    assert client.post("/v1/admin/reload").status_code == 403
    assert client.post("/v1/admin/reload", headers={"X-Admin-Token": "nope"}).status_code == 403
    assert client.post("/v1/admin/reload", headers={"X-Admin-Token": "s3cret"}).status_code == 200
