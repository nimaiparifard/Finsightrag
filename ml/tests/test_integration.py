"""End to end on a tiny synthetic filing: ingest -> retrieve -> answer, no network, no GPU."""

import fitz
import pytest

from finsight.config import Config
from finsight.embedders import HashEmbedder
from finsight.evaluation.datasets import EvalItem
from finsight.evaluation.runner import run_eval
from finsight.graph import RAGPipeline
from finsight.ingestion.pipeline import ingest
from finsight.interfaces import Message
from finsight.llm import FakeLLMProvider

PAGES = [
    "Acme Corp annual report. Table of contents.",
    "Item 1A. Risk Factors\nSupply chain disruption could harm our manufacturing of widgets.",
    "Item 7. Management's Discussion\nNet sales were 5,000 million in 2023, up from 4,000 million in 2022.\n"
    "Operating income was 900 million.",
    "Item 8. Notes\nThe company leases office space in Ohio and employs 12,000 people.",
]


@pytest.fixture
def corpus(tmp_path):
    pdf = fitz.open()
    for text in PAGES:
        pdf.new_page().insert_textbox(fitz.Rect(40, 40, 550, 780), text, fontsize=11)
    path = tmp_path / "Acme_2023_10K.pdf"
    pdf.save(path)
    return {"Acme_2023_10K": str(path)}


def make_cfg(tmp_path, **retrieval):
    cfg = Config.model_validate({
        "name": "test", "index_dir": str(tmp_path / "idx"), "parsed_dir": str(tmp_path / "parsed"),
        "chunker": {"name": "section", "max_tokens": 120, "overlap_tokens": 10},
        "embedder": {"name": "hash", "params": {"dim": 256}},
        "retrieval": {"top_k": 3, **retrieval},
    })
    return cfg


@pytest.mark.parametrize("mode", ["dense", "hybrid"])
def test_ingest_retrieve_answer(tmp_path, corpus, mode):
    cfg = make_cfg(tmp_path, mode=mode)
    emb = HashEmbedder(256)
    store = ingest(cfg, corpus, emb)
    n = len(store.chunks)
    assert n >= 4
    assert len(ingest(cfg, corpus, emb).chunks) == n  # idempotent re-ingest

    def respond(msgs: list[Message]) -> str:
        assert "5,000 million" in msgs[0].content  # evidence reached the prompt
        return "Net sales were 5,000 million [Acme_2023_10K:2]. Growth was <calc>(5000-4000)/4000*100</calc>%."

    pipe = RAGPipeline(cfg, store, emb, llm=FakeLLMProvider(responder=respond))
    res = pipe.query("What were Acme net sales in 2023?")
    top5 = {(h.chunk.doc_id, h.chunk.page) for h in res.retrieval.hits}
    assert ("Acme_2023_10K", 2) in top5
    assert res.retrieval.route.filters == {"company": ["Acme"]}
    assert "= 25" in res.answer.text and res.answer.guardrails.ok
    assert res.answer.citations == [{"doc_id": "Acme_2023_10K", "page": 2}]


def test_refusal_below_threshold(tmp_path, corpus):
    cfg = make_cfg(tmp_path, min_score=0.99)
    emb = HashEmbedder(256)
    pipe = RAGPipeline(cfg, ingest(cfg, corpus, emb), emb, llm=FakeLLMProvider())
    res = pipe.query("What is the airspeed velocity of an unladen swallow?")
    assert res.answer.refused and not pipe.llm.calls  # never even called the LLM


def test_run_eval_reports_retrieval_metrics(tmp_path, corpus):
    cfg = make_cfg(tmp_path, mode="hybrid")
    emb = HashEmbedder(256)
    pipe = RAGPipeline(cfg, ingest(cfg, corpus, emb), emb, llm=FakeLLMProvider())
    items = [EvalItem("q1", "What were Acme net sales in 2023?", "5,000", [("Acme_2023_10K", 2)]),
             EvalItem("q2", "Where does Acme lease office space?", "Ohio", [("Acme_2023_10K", 3)])]
    out = run_eval(pipe, items)
    assert out["metrics"]["recall@5"] == 1.0 and out["metrics"]["mrr"] > 0.5


def test_semantic_cache_hit_skips_llm(tmp_path, corpus):
    from finsight.cache import InMemorySemanticCache

    cfg = make_cfg(tmp_path)
    emb = HashEmbedder(256)
    llm = FakeLLMProvider(reply="Net sales were 5,000 million [Acme_2023_10K:2].")
    pipe = RAGPipeline(cfg, ingest(cfg, corpus, emb), emb, llm=llm, cache=InMemorySemanticCache(0.95))
    first = pipe.query("What were Acme net sales in 2023?")
    again = pipe.query("What were Acme net sales in 2023?")
    other = pipe.query("Where does Acme lease office space?")
    assert not first.cached and again.cached and not other.cached
    assert again.answer.text == first.answer.text and len(llm.calls) == 2
    # a different filter set must not reuse the entry
    assert not pipe.query("What were Acme net sales in 2023?", {"company": "Acme"}).cached


def test_tracer_is_noop_without_keys():
    from finsight.tracing import Tracer

    t = Tracer()
    with t.trace("x", a=1) as span:
        span.update(output="y")
    assert not t.enabled


def test_eval_survives_a_failing_llm_call(tmp_path, corpus):
    cfg = make_cfg(tmp_path, mode="dense")
    emb = HashEmbedder(256)
    n = {"c": 0}

    def flaky(msgs):
        n["c"] += 1
        if n["c"] == 1:
            raise TimeoutError("ollama read timeout")
        return "Net sales were 5,000 million [Acme_2023_10K:2]."

    pipe = RAGPipeline(cfg, ingest(cfg, corpus, emb), emb, llm=FakeLLMProvider(responder=flaky))
    items = [EvalItem("q1", "What were Acme net sales in 2023?", "5,000", [("Acme_2023_10K", 2)]),
             EvalItem("q2", "What were Acme net sales in 2023?", "5,000", [("Acme_2023_10K", 2)])]
    out = run_eval(pipe, items, generate=True)
    assert out["metrics"]["errors"] == 1 and "TimeoutError" in out["rows"][0]["error"]
    assert out["metrics"]["numeric_em"] == 1.0  # the surviving question is still scored
