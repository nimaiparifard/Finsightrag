import pytest

from finsight.evaluation.numeric import numeric_match
from finsight.evaluation.retrieval_metrics import mrr, ndcg_at_k, recall_at_k
from finsight.generation.calculator import CalculatorError, evaluate, run_calc_tags, run_calc_tags_detailed
from finsight.generation.guardrails import NOT_FOUND, check_answer, parse_citations
from finsight.ingestion.chunkers.recursive import RecursiveChunker, split_text
from finsight.ingestion.chunkers.section import SectionChunker
from finsight.interfaces import Chunk, Hit, Page, ParsedDocument
from finsight.retrieval.hybrid import reciprocal_rank_fusion
from finsight.text_utils import count_tokens, parse_doc_id


def hit(doc="A_2023_10K", page=1, text="x", score=1.0):
    return Hit(Chunk(doc, page, text, meta={"company": "A"}), score)


# ---- chunkers -------------------------------------------------------------------------------
def test_chunks_respect_max_tokens_and_overlap():
    text = "\n\n".join(f"Paragraph {i}. " + "revenue grew strongly " * 20 for i in range(40))
    chunks = split_text(text, max_tokens=200, overlap=40)
    assert len(chunks) > 3
    assert all(count_tokens(c) <= 200 for c in chunks)
    assert chunks[0][-30:] in chunks[1]  # tail of chunk N reappears in chunk N+1


def test_recursive_chunker_never_crosses_pages():
    doc = ParsedDocument("A_2023_10K", [Page("A_2023_10K", 0, "alpha " * 600), Page("A_2023_10K", 1, "beta " * 600)],
                         parse_doc_id("A_2023_10K"))
    for c in RecursiveChunker(200, 20).chunk(doc):
        assert ("alpha" in c.text) != ("beta" in c.text)


def test_section_chunker_tracks_items():
    page = Page("A_2023_10K", 3, "Intro text.\nItem 1A. Risk Factors\nWe face risks.\nItem 7. Management's Discussion\nRevenue up.")
    chunks = SectionChunker(200, 20).chunk(ParsedDocument("A_2023_10K", [page], {}))
    assert {c.section for c in chunks} == {"Front Matter", "Item 1A Risk Factors", "Item 7 MD&A"}
    risk = next(c for c in chunks if c.section.startswith("Item 1A"))
    assert "Revenue up" not in risk.text


def test_chunk_id_is_deterministic_for_dedup():
    assert Chunk("d", 1, "t").id == Chunk("d", 1, "t").id != Chunk("d", 2, "t").id


def test_contextual_header():
    c = Chunk("Apple_2023_10K", 5, "text", section="Item 7 MD&A", meta=parse_doc_id("Apple_2023_10K"))
    assert c.embed_text(True).startswith("Apple | 10-K FY2023 | Item 7 MD&A\n")
    assert c.embed_text(False) == "text"


# ---- retrieval ------------------------------------------------------------------------------
def test_rrf_math():
    a, b, c = hit(page=1), hit(page=2), hit(page=3)
    fused = reciprocal_rank_fusion([[a, b], [b, c]], k=60)
    scores = {h.chunk.page: h.score for h in fused}
    assert scores[2] == pytest.approx(1 / 62 + 1 / 61)
    assert scores[1] == pytest.approx(1 / 61)
    assert [h.chunk.page for h in fused][0] == 2


def test_retrieval_metrics():
    hits = [hit(page=9), hit(page=2), hit(page=2), hit(page=5)]
    gold = {("A_2023_10K", 2), ("A_2023_10K", 7)}
    assert recall_at_k(hits, gold, 5) == 0.5
    assert recall_at_k(hits, gold, 1) == 0.0
    assert mrr(hits, gold) == 0.5  # duplicate page collapsed, first relevant at rank 2
    assert 0 < ndcg_at_k(hits, gold, 5) < 1


# ---- calculator safety ----------------------------------------------------------------------
def test_calculator_basic():
    assert evaluate("(383,285 - 394,328) / 394,328 * 100") == pytest.approx(-2.8, abs=0.01)
    assert evaluate("10%") == pytest.approx(0.1)


@pytest.mark.parametrize("bad", ["__import__('os').system('echo hi')", "open('x')", "1; 2", "[1]", "a+1",
                                 "().__class__", "9**9**9", "1/0"])
def test_calculator_rejects_unsafe(bad):
    with pytest.raises(CalculatorError):
        evaluate(bad)


def test_calc_tags_replaced():
    text, vals = run_calc_tags("Margin is <calc>(10-4)/10*100</calc>% and <calc>os.system('x')</calc>.")
    assert "= 60" in text and vals == [60.0]
    assert "os.system" in text  # unsafe expr left as plain text, never executed


# ---- citations & guardrails -----------------------------------------------------------------
def test_citation_parser():
    assert parse_citations("Sales rose [A_2023_10K:41]. Costs [B_2022_10K:7][A_2023_10K:41].") == [
        ("A_2023_10K", 41), ("B_2022_10K", 7), ("A_2023_10K", 41)]


def test_guardrails_flag_bad_citation_and_ungrounded_number():
    hits = [hit(page=4, text="Net sales were $383,285 million.")]
    ok = check_answer("Net sales were $383,285 million [A_2023_10K:4].", hits)
    assert ok.ok
    bad = check_answer("Net sales were $999,111 million [A_2023_10K:99].", hits)
    assert not bad.ok and bad.invalid_citations == [("A_2023_10K", 99)] and "999111" in bad.ungrounded_numbers
    assert check_answer(NOT_FOUND, hits).ok


def test_guardrails_accept_calculator_results():
    hits = [hit(page=4, text="Revenue 100 and 80.")]
    out, vals, exprs = run_calc_tags_detailed("Growth is <calc>(100-80)/80*100</calc>% [A_2023_10K:4].")
    assert check_answer(out, hits, vals, exprs).ok
    out, vals, exprs = run_calc_tags_detailed("Growth is <calc>(100-77)/77*100</calc>% [A_2023_10K:4].")
    rep = check_answer(out, hits, vals, exprs)
    assert not rep.ok and "77" in rep.ungrounded_numbers  # operand not in the context


# ---- numeric EM -----------------------------------------------------------------------------
@pytest.mark.parametrize("pred,gold,expected", [
    ("Capex was $1,577 million", "$1577.00", True),
    ("about 1.577 billion dollars", "$1577.00", True),
    ("Capex was $1,700 million", "$1577.00", False),
    ("Yes, it is capital intensive", "Yes", None),
    ("The ratio is 0.65", "0.65", True),
])
def test_numeric_match(pred, gold, expected):
    assert numeric_match(pred, gold) is expected


def test_data_dir_env_relocates_paths(monkeypatch, tmp_path):
    from finsight.config import Config

    assert Config().index_dir == "data/processed/index"
    monkeypatch.setenv("FINSIGHT_DATA_DIR", str(tmp_path))
    c = Config()
    assert c.index_dir == str(tmp_path / "processed" / "index") and c.parsed_dir == str(tmp_path / "interim" / "parsed")
    assert Config(index_dir="/abs/elsewhere").index_dir == "/abs/elsewhere"  # absolute paths untouched


def test_config_extends_chain():
    from finsight.config import Config

    c = Config.load("ml/configs/hybrid_rerank_ctx.yaml")
    assert (c.name, c.retrieval.mode, c.retrieval.rerank, c.contextual_headers) == ("hybrid_rerank_ctx", "hybrid", True, True)
    assert c.embedder.params["model"] == "BAAI/bge-base-en-v1.5"  # inherited from baseline
    base = Config.load("ml/configs/baseline.yaml").index_key()
    assert Config.load("ml/configs/hybrid_rerank.yaml").index_key() == base  # same ingestion -> shared index
    assert c.index_key() != base  # contextual headers change the embedded text -> needs its own index


def test_rrf_weights():
    a, b = hit(page=1), hit(page=2)
    # equal weights: a (rank 1 in list 1) and b (rank 1 in list 2) tie; a 0.1 weight on list 2 makes a win clearly
    tie = {h.chunk.page: h.score for h in reciprocal_rank_fusion([[a], [b]], k=60)}
    assert tie[1] == pytest.approx(tie[2])
    w = reciprocal_rank_fusion([[a], [b]], k=60, weights=[1.0, 0.1])
    assert [h.chunk.page for h in w] == [1, 2] and w[1].score == pytest.approx(0.1 / 61)
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[a], [b]], weights=[1.0])
