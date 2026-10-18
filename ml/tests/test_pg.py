"""Needs a Postgres with pgvector:  docker run -d -p 55432:5432 -e POSTGRES_PASSWORD=test pgvector/pgvector:pg16
then FINSIGHT_TEST_PG_DSN=postgresql://postgres:test@localhost:55432/postgres  (skipped otherwise)."""

import os
import uuid

import pytest

DSN = os.environ.get("FINSIGHT_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FINSIGHT_TEST_PG_DSN not set")

from finsight.embedders import HashEmbedder  # noqa: E402
from finsight.interfaces import Chunk  # noqa: E402

CHUNKS = [
    Chunk("Acme_2023_10K", 2, "Net sales were 5,000 million in 2023, up from 4,000 million.", meta={"company": "Acme", "year": "2023"}),
    Chunk("Acme_2023_10K", 3, "The company leases office space in Ohio and employs 12,000 people.", meta={"company": "Acme", "year": "2023"}),
    Chunk("Beta_2022_10K", 1, "Beta revenue grew 12 percent driven by cloud subscriptions.", meta={"company": "Beta", "year": "2022"}),
]


@pytest.fixture
def store():
    from finsight.pg_store import PgVectorStore

    emb = HashEmbedder(64)
    s = PgVectorStore(DSN, 64, table=f"t_{uuid.uuid4().hex[:8]}")
    s.upsert(CHUNKS, emb.embed([c.text for c in CHUNKS]))
    yield s, emb
    with s.conn.cursor() as c:
        c.execute(f"DROP TABLE {s.table}, {s.table}_meta")
    s.close()


def test_dense_search_and_filters(store):
    s, emb = store
    hits = s.search(emb.embed(["net sales 2023"], is_query=True)[0], 3)
    assert hits[0].chunk.page == 2 and hits[0].chunk.meta["company"] == "Acme" and 0 < hits[0].score <= 1
    only_beta = s.search(emb.embed(["revenue"], is_query=True)[0], 3, {"company": ["beta"]})  # case-insensitive
    assert [h.chunk.doc_id for h in only_beta] == ["Beta_2022_10K"]
    assert s.search(emb.embed(["x"], is_query=True)[0], 3, {"doc_id": "Nope"}) == []


def test_keyword_search_and_injection_safety(store):
    s, _ = store
    kw = s.keyword_index()
    assert kw.search("office space Ohio", 3)[0].chunk.page == 3
    assert kw.search("cloud OR subscriptions; DROP TABLE x --", 3)[0].chunk.doc_id == "Beta_2022_10K"
    assert kw.search("!!! ???", 3) == []
    assert s.count() == 3  # table survived the injection attempt


def test_upsert_is_idempotent_and_helpers(store):
    s, emb = store
    s.upsert(CHUNKS, emb.embed([c.text for c in CHUNKS]))
    assert s.count() == 3 and s.doc_ids() == {"Acme_2023_10K", "Beta_2022_10K"} and s.companies() == {"Acme", "Beta"}


def test_index_version_switch_is_atomic(store):
    from finsight.pg_store import PgVectorStore

    s, emb = store
    v2 = PgVectorStore(DSN, 64, table=s.table, version=2)
    with pytest.raises(ValueError, match="empty"):
        v2.activate(2)  # nothing indexed yet: refuse to point readers at an empty index
    v2.upsert(CHUNKS[:1], emb.embed([CHUNKS[0].text]))
    assert s.active_version() == 1 and s.count() == 3  # v1 keeps serving during the re-index
    v2.activate(2)
    reader = PgVectorStore(DSN, 64, table=s.table)
    assert reader.version == 2 and reader.count() == 1
    with pytest.raises(ValueError, match="active"):
        reader.drop_version(2)
    assert reader.drop_version(1) == 3
    v2.close()
    reader.close()


def test_pipeline_end_to_end_on_pgvector(tmp_path, monkeypatch):
    import fitz

    from finsight.config import Config
    from finsight.graph import RAGPipeline
    from finsight.ingestion.pipeline import ingest
    from finsight.llm import FakeLLMProvider

    monkeypatch.setenv("FINSIGHT_PG_DSN", DSN)
    pdf = fitz.open()
    for t in ["cover", "Item 7. MD&A\nNet sales were 5,000 million in 2023."]:
        pdf.new_page().insert_textbox(fitz.Rect(40, 40, 550, 780), t, fontsize=11)
    pdf.save(tmp_path / "Acme_2023_10K.pdf")
    cfg = Config.model_validate({"name": "pg", "parsed_dir": str(tmp_path / "p"), "index_dir": str(tmp_path / "i"),
                                 "store": {"backend": "pgvector"}, "embedder": {"name": "hash"},
                                 "retrieval": {"mode": "hybrid", "top_k": 3}, "chunker": {"name": "section"}})
    emb = HashEmbedder(256)
    store = ingest(cfg, {"Acme_2023_10K": str(tmp_path / "Acme_2023_10K.pdf")}, emb)
    try:
        pipe = RAGPipeline(cfg, store, emb, llm=FakeLLMProvider(reply="Net sales were 5,000 million [Acme_2023_10K:1]."))
        res = pipe.query("What were Acme net sales in 2023?")
        assert res.answer.citations == [{"doc_id": "Acme_2023_10K", "page": 1}] and res.answer.guardrails.ok
        assert res.retrieval.route.filters == {"company": ["Acme"]}
    finally:
        with store.conn.cursor() as c:
            c.execute(f"DROP TABLE {store.table}, {store.table}_meta")
