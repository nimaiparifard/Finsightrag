from finsight.ingestion.table_summaries import summarize_tables
from finsight.interfaces import Chunk
from finsight.llm import FakeLLMProvider

RAW = "| item | 2023 | 2022 |\n|---|---|---|\n| revenue | 5,000 | 4,000 |\n| cost | 3,000 | 2,500 |"


def test_summary_is_embedded_but_raw_table_is_kept(tmp_path):
    t = Chunk("A_2023_10K", 4, RAW, "table", meta={"company": "A", "form": "10-K", "year": "2023"})
    tiny = Chunk("A_2023_10K", 4, "| a | b |\n|---|---|", "table")
    prose = Chunk("A_2023_10K", 4, "some text", "text")
    llm = FakeLLMProvider(reply="Income statement with revenue and cost of sales for 2023 and 2022, in millions.")
    cid, cache = t.id, tmp_path / "s.json"

    assert summarize_tables([t, tiny, prose], llm, cache_path=cache) == 1  # only the real table is summarized
    assert t.id == cid  # attaching a summary must not change the dedup id
    assert "Income statement" in t.embed_text(False) and "5,000" not in t.embed_text(False)
    assert t.text == RAW  # the LLM still reads the raw table at answer time
    assert t.embed_text(True).startswith("A | 10-K FY2023")
    assert prose.embed_text(False) == "some text" and "summary" not in tiny.meta

    # second run: served from the on-disk cache, zero LLM calls
    t2 = Chunk("A_2023_10K", 4, RAW, "table", meta={"company": "A"})
    assert summarize_tables([t2], FakeLLMProvider(), cache_path=cache) == 0
    assert "Income statement" in t2.meta["summary"]


def test_summary_failure_does_not_break_ingestion():
    class Boom:
        usage: dict = {}

        def generate(self, *a, **k):
            raise RuntimeError("llm down")

    t = Chunk("d", 1, "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |", "table")
    assert summarize_tables([t], Boom()) == 0
    assert "summary" not in t.meta and t.embed_text(False) == t.text


def test_max_per_doc_bounds_llm_cost():
    tables = [Chunk("d", i, RAW + f"\n| x | {i} | 0 |", "table") for i in range(10)]
    llm = FakeLLMProvider(reply="summary")
    assert summarize_tables(tables, llm, max_per_doc=3) == 3 and len(llm.calls) == 3
