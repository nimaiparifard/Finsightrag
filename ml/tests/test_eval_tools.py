import json

from finsight.evaluation import golden
from finsight.evaluation.datasets import load_golden
from finsight.evaluation.gate import compare_to_baseline
from finsight.evaluation.judge import judge_answer
from finsight.interfaces import Chunk, Hit
from finsight.llm import FakeLLMProvider


def hits():
    return [Hit(Chunk("A_2023_10K", 2, "Net sales were 5,000 million.", meta={"company": "A"}), 1.0)]


def test_judge_scores_supported_fraction_and_relevancy():
    def responder(msgs):
        if "fact-checker" in msgs[0].content:
            return 'Sure: {"claims": [{"claim": "sales were 5,000", "supported": true}, {"claim": "margin 40%", "supported": false}]}'
        return '{"score": 5}'

    r = judge_answer(FakeLLMProvider(responder=responder), "What were sales?", "Sales were 5,000; margin 40%.", hits())
    assert r.faithfulness == 0.5 and r.answer_relevancy == 1.0 and r.claims == 2


def test_judge_skips_refusals_and_survives_garbage():
    llm = FakeLLMProvider(reply="not json at all")
    assert judge_answer(llm, "q", "Not found in the provided documents.", hits()).faithfulness is None
    assert not llm.calls  # a refusal costs no judge calls
    r = judge_answer(llm, "q", "Sales were 5,000.", hits())
    assert r.faithfulness is None and r.answer_relevancy is None


def test_gate_fails_on_drop_over_threshold_and_on_missing_metric():
    base = {"recall@5": 0.60, "faithfulness": 0.90, "mrr": 0.40}
    assert compare_to_baseline({"recall@5": 0.58, "faithfulness": 0.89, "mrr": 0.45}, base).passed
    bad = compare_to_baseline({"recall@5": 0.60, "faithfulness": 0.85, "mrr": 0.40}, base)
    assert not bad.passed and "FAIL" in bad.render()
    gone = compare_to_baseline({"recall@5": 0.60, "mrr": 0.40}, base)  # faithfulness vanished
    assert not gone.passed and "MISSING" in gone.render()
    assert compare_to_baseline({"recall@5": 0.10}, {}).passed  # nothing protected


def test_golden_generation_and_verified_filter(tmp_path):
    chunks = []
    for co, doc in [("Acme", "Acme_2023_10K"), ("Beta", "Beta_2023_10K")]:
        for p in range(4):
            chunks.append(Chunk(doc, p, f"{co} revenue 1,000 2,000 3,000 4,000 5,000 6,000 7,000 " + "text " * 120,
                                meta={"company": co, "year": "2023"}))
    llm = FakeLLMProvider(reply='{"question": "What was revenue?", "answer": "7,000"}')
    items = golden.generate(llm, chunks, mix={"factual": 3, "numeric": 3, "multihop": 2, "multidoc": 2, "unanswerable": 2})
    kinds = [i["type"] for i in items]
    assert kinds.count("multidoc") == 2 and kinds.count("unanswerable") == 2
    md = next(i for i in items if i["type"] == "multidoc")
    assert len({e["doc_id"] for e in md["evidence"]}) == 2  # really spans two companies
    assert all(i["verified"] is False for i in items) and all(not i["evidence"] for i in items if i["type"] == "unanswerable")

    path = str(tmp_path / "g.jsonl")
    golden.write_jsonl(items, path)
    assert load_golden(path) == []  # nothing verified yet -> nothing used for gating
    rows = [json.loads(line) for line in open(path)]
    rows[0]["verified"] = True
    open(path, "w").write("\n".join(json.dumps(r) for r in rows))
    assert [i.id for i in load_golden(path)] == [rows[0]["id"]]
    assert len(load_golden(path, only_verified=False)) == len(items)
    assert golden.summary(path)["verified"] == 1


def test_generation_drops_unparseable_llm_output():
    chunks = [Chunk("A_2023_10K", 0, "x " * 400, meta={"company": "A"})]
    items = golden.generate(FakeLLMProvider(reply="sorry, I cannot"), chunks, mix={"factual": 2})
    assert items == []
