import pytest

pytest.importorskip("llama_index.core")

from test_integration import PAGES, corpus, make_cfg  # noqa: E402,F401

from finsight.embedders import HashEmbedder  # noqa: E402
from finsight.graph import RAGPipeline  # noqa: E402
from finsight.ingestion.pipeline import ingest  # noqa: E402
from finsight.integrations.llamaindex_impl import LlamaIndexRAG  # noqa: E402
from finsight.llm import FakeLLMProvider  # noqa: E402


@pytest.mark.parametrize("mode", ["finsight", "native"])
def test_llamaindex_modes_answer_with_same_guardrails(tmp_path, corpus, mode):  # noqa: F811
    cfg = make_cfg(tmp_path, mode="hybrid")
    emb = HashEmbedder(256)
    seen = {}

    def respond(msgs):
        seen["prompt"] = msgs[0].content
        return "Net sales were 5,000 million [Acme_2023_10K:2]. Growth <calc>(5000-4000)/4000*100</calc>%."

    pipe = RAGPipeline(cfg, ingest(cfg, corpus, emb), emb, llm=FakeLLMProvider(responder=respond))
    ans, hits = LlamaIndexRAG.from_pipeline(pipe, mode).query("What were Acme net sales in 2023?")
    assert "[Acme_2023_10K:2]" in seen["prompt"] and "5,000 million" in seen["prompt"]
    assert ("Acme_2023_10K", 2) in {(h.chunk.doc_id, h.chunk.page) for h in hits}
    assert "= 25" in ans.text and ans.guardrails.ok
    assert ans.citations == [{"doc_id": "Acme_2023_10K", "page": 2}]


def test_langgraph_comparison_agent(tmp_path, corpus):  # noqa: F811
    pytest.importorskip("langgraph")
    from finsight.integrations.langgraph_agent import ComparisonAgent, is_comparison
    from finsight.interfaces import Message

    cfg = make_cfg(tmp_path, mode="hybrid")
    emb = HashEmbedder(256)
    calls = []

    def respond(msgs: list[Message]) -> str:
        sysmsg = msgs[0].content
        calls.append(sysmsg[:20])
        if "split it into" in sysmsg:  # planner
            return '["What were Acme net sales in 2023?", "What were Acme net sales in 2022?"]'
        if sysmsg.startswith("You are FinSight. Write a concise comparison"):
            return "Sales rose from 4,000 to 5,000 million [Acme_2023_10K:2]: <calc>(5000-4000)/4000*100</calc>%."
        return "Net sales were 5,000 million [Acme_2023_10K:2]; 4,000 million prior year [Acme_2023_10K:2]."

    pipe = RAGPipeline(cfg, ingest(cfg, corpus, emb), emb, llm=FakeLLMProvider(responder=respond))
    out = ComparisonAgent(pipe).run("Compare Acme net sales in 2023 versus 2022")
    assert len(out["findings"]) == 2
    assert "= 25" in out["answer"].text and out["answer"].guardrails.ok
    assert is_comparison("Compare Acme and Beta", {"Acme", "Beta"}) and not is_comparison("Acme sales?", {"Acme"})
